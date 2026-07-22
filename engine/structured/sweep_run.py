#!/usr/bin/env python3
"""Sweep runner — the two-oracle harness for the structured sweep family.

A sweep vector carries an **expected behaviour**, so the runner checks *two*
independent things the plain differential cannot:

  1. **Agreement** — do all 13 drivers produce the same canonical line? A
     disagreement is a divergence (the classic oracle; a finding).
  2. **Conformance** — does the agreed behaviour match what the spec requires for
     that vector? `expect=reject` means every driver MUST emit `R`; `expect=accept`
     MUST be `A`. A *family-wide* wrong answer (all 13 uniformly accept an
     over-bound value) is **agreement-green but conformance-red** — invisible to a
     differential-only oracle, and exactly the gap a "must reject" sweep exists to
     catch.

(For `merge` / `replace` / `lastwins` the required *value* is intricate to recompute
here, so those are checked as `accept` + agreement; their semantic correctness is
asserted in the finding write-ups. Only the accept-vs-reject conformance is machine
-checked, which is where the family-wide gaps hide.)

Runs every registered axis, prints per-axis {divergences, conformance failures},
exits non-zero if either is non-empty.

Usage: python3 engine/structured/sweep_run.py [axis ...]   (default: all)
"""
import importlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))  # repo root for oracle.comparator

from oracle.comparator import run_driver, parse  # noqa: E402

AXES = ["wiretype_sweep", "sweep_repeated_id", "sweep_overbound", "sweep_reserved_subtype",
        "sweep_truncation", "sweep_malform_truncate", "sweep_varint"]

# `sweep_varint` (WP-03, §2 varint canonicality) is blocking but **agreement-only** for
# its non-minimal vectors (`expect="agree"`): the spec is silent on whether a
# non-minimal-but-≤64-bit varint is accepted-and-normalized or rejected, so the runner
# asserts only that all 13 agree (they do — accept + normalize to the one canonical form)
# and does NOT assert accept-vs-reject conformance for those vectors, per ground rule 6,
# until the upstream clause lands (docs/spec-proposals.md). The minimal-accept controls
# and the >64-bit overflow-reject contrast ARE spec-defined (CORELIB_PLAN §4.1 / F-0016).

# The 13-driver roster, mirroring scripts/run.sh. Built by ./scripts/run.sh already.
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DRIVERS = [
    ("c",          f"{ROOT}/drivers/c/build/driver"),
    ("go",         f"{ROOT}/drivers/go/build/driver"),
    ("rust-std",   f"{ROOT}/drivers/rust/build/rs/target/debug/harness"),
    ("rust-nostd", f"{ROOT}/drivers/rust/build/rs-no-std/target/debug/harness"),
    ("cpp",        f"{ROOT}/drivers/cpp/build/cpp/driver"),
    ("cpp-c-cpp",  f"{ROOT}/drivers/cpp/build/c-cpp/driver"),
    ("py-cython",  f"{ROOT}/drivers/python/build/py-cython"),
    ("py-pure",    f"{ROOT}/drivers/python/build/py-pure"),
    ("java",       f"{ROOT}/drivers/java/build/driver"),
    ("typescript", f"{ROOT}/drivers/ts/build/driver"),
    ("csharp",     f"{ROOT}/drivers/cs/build/driver"),
    ("zig",        f"{ROOT}/drivers/zig/build/driver"),
    ("dart",       f"{ROOT}/drivers/dart/build/driver"),
]


def run_axis(name):
    mod = importlib.import_module(name)
    with tempfile.TemporaryDirectory() as d:
        vectors = mod.emit(d)                       # [(fname, bytes, expect)]
    corpus = [(fn, data) for fn, data, _ in vectors]
    expect = {fn: exp for fn, _, exp in vectors}

    # verdict per driver per input
    outs = {}
    for dn, path in DRIVERS:
        lines, fail_idx, _, kind = run_driver(path, corpus, timeout=60.0)
        if fail_idx is not None:
            print(f"  [{name}] driver {dn} {kind} on {corpus[fail_idx][0]}")
        outs[dn] = lines

    divergences, conformance, soft = [], [], []
    for i, (fn, _) in enumerate(corpus):
        vals = {dn: (outs[dn][i] or "") for dn, _ in DRIVERS}
        verds = {dn: parse(v)[0] for dn, v in vals.items()}
        pays = {dn: parse(v)[1] for dn, v in vals.items()}
        # Axis-aware, matching oracle/policy.yaml (as comparator.py does): a verdict
        # split (A/I/R) is HARD; an accept-value split (agreed A, differing hex) is
        # HARD; an incomplete-value payload (agreed I) or a reject-class (agreed R)
        # difference is SOFT — a warning, not a divergence.
        if len(set(verds.values())) > 1:
            divergences.append((fn, vals))
            continue
        v = next(iter(verds.values()))
        if v == "A" and len(set(pays.values())) > 1:
            divergences.append((fn, vals))           # accept_value — hard
            continue
        if v in ("I", "R", "L") and len(set(pays.values())) > 1:
            soft.append(fn)                          # incomplete_value / reject_class — soft
        # agreed on the hard axes — now check conformance
        exp = expect[fn]
        if exp == "reject" and v != "R":
            conformance.append((fn, f"expected R, all 13 emit {v}"))
        elif exp == "accept" and v != "A":
            conformance.append((fn, f"expected A, all 13 emit {v}"))
        # merge/replace/lastwins -> treated as accept
        elif exp in ("merge", "replace", "lastwins") and v != "A":
            conformance.append((fn, f"expected A ({exp}), all 13 emit {v}"))
        # a prefix of a valid message is A (complete) or I (incomplete), never R
        elif exp == "not_reject" and v == "R":
            conformance.append((fn, "prefix of a valid message emitted R (INVALID)"))
    return len(corpus), divergences, conformance, soft


def main():
    axes = sys.argv[1:] or AXES
    total_div = total_conf = 0
    for name in axes:
        n, div, conf, soft = run_axis(name)
        total_div += len(div); total_conf += len(conf)
        status = "OK" if not div and not conf else "FAIL"
        softnote = f", {len(soft)} soft (incomplete_value/reject_class)" if soft else ""
        print(f"[{name}] {n} vectors — {len(div)} divergence(s), "
              f"{len(conf)} conformance failure(s){softnote}  [{status}]")
        for fn, vals in div[:8]:
            camps = {}
            for dn, v in vals.items():
                camps.setdefault(v[:22] or "(empty)", []).append(dn)
            print(f"    DIVERGE {fn}: "
                  + " | ".join(f"[{outv}] {','.join(ds)}" for outv, ds in camps.items()))
        for fn, msg in conf[:8]:
            print(f"    NONCONFORM {fn}: {msg}")
    print(f"\nTOTAL: {total_div} divergence(s), {total_conf} conformance failure(s)")
    return 1 if (total_div or total_conf) else 0


if __name__ == "__main__":
    sys.exit(main())
