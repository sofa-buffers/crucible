#!/usr/bin/env python3
"""Encode-invariance oracle — one implementation's encode surfaces against each other.

The family is **byte-canonical**: a value has exactly one encoding. The generated API
offers up to three ways to produce it (crucible#132), and the round-trip oracle
exercises exactly one of them — whichever the driver happens to call:

* `SOFAB_ENCODE=new`    — the allocating `encode()` → a fresh buffer
* `SOFAB_ENCODE=to`     — the caller-buffer `encodeTo(dst, cap)` / `EncodeTo(w)`
* `SOFAB_ENCODE=stream` — the streaming `serialize(os)` into an `OStream`

For one implementation and one decoded value, all three must emit **identical bytes**.
And `SOFAB_FLUSH=n` — an `n`-byte `OStream` buffer, so the sink is handed the message in
`n`-byte pieces — must not change them either. That is the encode-side mirror of
`SOFAB_CHUNK=1`: it walks the encoder across a buffer boundary at every offset, which is
where an encoder that mismanages its own buffer state shows up.

Like `chunk_invariance.py` and unlike every other oracle here, this is **not
differential** — it compares an implementation against itself. So it needs no second
implementation to be useful, drivers opt in one at a time, and it is the only kind of
gate that can catch a defect the whole family shares.

Two things are checked per driver:

1. **Agreement.** Every surface the backend has produces the whole corpus's canonical
   lines identically, at every flush size.
2. **The contract's hard-fail.** Asking for a surface the backend does *not* have must
   make the driver exit non-zero (CONTRACT.md, "Encode side"). A driver that quietly
   falls back to another surface would report a mode as passing that never ran — which
   is the failure this whole file exists to prevent, so it is asserted rather than
   assumed.

`meta`'s `encode_surfaces` says which surfaces a backend has, and its `min_output_buffer`
says the smallest streaming buffer the port accepts (CORELIB_PLAN §5.1). A driver that
ignores the variables emits byte-identical output, indistinguishable from passing, so the
drivers to run are named explicitly by the caller and never inferred.
"""

import argparse
import os
import re
import struct
import subprocess
import sys

import roster

ROOT = roster.ROOT
DRIVERS = roster.drivers(roster.gate_tag())
BUILDERS = {name: builder for name, builder, _, _, _ in roster.rows(roster.gate_tag())}

# OStream buffer sizes for the streaming surface. The smallest a port accepts is the
# strong one — the sink sees the message in the least it will take, so every internal
# buffer boundary is crossed. The rest are cheap and land the boundary at different
# offsets inside varints and payloads. Sizes below a port's declared minimum are not in
# its sweep at all (see flush_sizes).
FLUSH_SIZES = (1, 2, 3, 5, 8, 16)

ALL_SURFACES = ("new", "to", "stream")


def flush_sizes(minbuf):
    """The flush sizes to sweep for a port declaring `minbuf` (CORELIB_PLAN §5.1).

    §5.1 no longer fixes the floor at one byte for everyone. A port declares the
    smallest streaming buffer it accepts — 1 if it splits atomic units, otherwise the
    largest run it reserves as one piece, capped at 20 — and the two halves of the
    clause are what this sweep asserts:

    * **at or above the declaration**, every size MUST work and MUST produce output
      byte-identical to the one-shot path, so those sizes are swept;
    * **below it**, a buffer MUST be refused where it is handed over.

    The declaration itself is always included, even when it is not one of the standard
    sizes. That is what keeps the sweep honest for a port with a high floor: it is
    walked across a buffer boundary at its own minimum, so the sweep can never be empty
    and "every size was inapplicable" — the shape that let corelib-ts#94 sit behind a
    green gate — cannot recur by construction.
    """
    return tuple(sorted({minbuf} | {n for n in FLUSH_SIZES if n > minbuf}))


# Same cap, same reason as chunk_invariance.FEED_TIMEOUT: one run carries the whole
# corpus, so a fuzzed corpus needs more than the hand-written ones this was sized for.
FEED_TIMEOUT = int(os.environ.get("ENCODE_FEED_TIMEOUT", "120"))


def run(path, inputs, env=None):
    """Run a driver over `inputs`; returns (lines, returncode, stderr)."""
    blob = b"".join(struct.pack("<I", len(d)) + d for d in inputs)
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([path], input=blob, capture_output=True, env=e,
                       timeout=FEED_TIMEOUT)
    return (p.stdout.decode(errors="replace").splitlines(), p.returncode,
            p.stderr.decode(errors="replace").strip())


def configs(surfaces, minbuf):
    """(label, env) for every encode surface this backend has, flush sizes included."""
    for s in ALL_SURFACES:
        if s not in surfaces:
            continue
        yield f"SOFAB_ENCODE={s}", {"SOFAB_ENCODE": s}
        if s == "stream":
            for n in flush_sizes(minbuf):
                yield f"SOFAB_ENCODE=stream SOFAB_FLUSH={n}", {
                    "SOFAB_ENCODE": "stream", "SOFAB_FLUSH": str(n)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--drivers", required=True,
                    help="comma/space-separated driver names that honour SOFAB_ENCODE")
    ap.add_argument("--skip-hard-fail", action="store_true",
                    help="do not assert that an absent surface exits non-zero")
    args = ap.parse_args()

    names = [n for n in args.drivers.replace(",", " ").split() if n]
    unknown = [n for n in names if n not in DRIVERS]
    if unknown:
        print(f"unknown driver(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    files = sorted(f for f in os.listdir(args.corpus)
                   if not f.endswith(".md") and f != ".gitkeep")
    inputs = [open(os.path.join(args.corpus, f), "rb").read() for f in files]
    if not inputs:
        print("empty corpus", file=sys.stderr)
        return 2

    failures = 0
    for name in names:
        path = DRIVERS[name]
        surfaces = roster.encode_surfaces(BUILDERS[name])
        if not surfaces:
            print(f"  [{name}] meta declares no encode_surfaces — nothing to compare",
                  file=sys.stderr)
            failures += 1
            continue

        # §5.1 requires the port to expose this; the gate requires the driver to
        # declare it. Defaulting to 1 here would reinstate the assumption this replaced.
        minbuf = roster.min_output_buffer(BUILDERS[name])
        if minbuf is None:
            print(f"  [{name}] meta declares no min_output_buffer — CORELIB_PLAN §5.1 "
                  "makes it normative, and the flush sweep cannot be sized without it",
                  file=sys.stderr)
            failures += 1
            continue
        if not 1 <= minbuf <= 20:
            print(f"  [{name}] min_output_buffer={minbuf} is outside §5.1's range "
                  "(1..20)", file=sys.stderr)
            failures += 1
            continue

        # The baseline is the driver's own default path, unchanged: whatever it calls
        # today with none of these variables set. Every surface must reproduce it, so a
        # driver that reads the variable but wires it to the wrong call is caught too.
        base, rc, err = run(path, inputs)
        if rc != 0 or len(base) != len(inputs):
            print(f"  [{name}] baseline run failed (rc={rc}, {len(base)} lines): {err}",
                  file=sys.stderr)
            failures += 1
            continue

        bad = tried = 0
        for label, env in configs(surfaces, minbuf):
            tried += 1
            lines, rc, err = run(path, inputs, env)
            # Exit 3 = "this backend cannot operate at this configuration"
            # (CONTRACT.md). For a missing *surface* that is a legitimate answer,
            # asserted separately below. For a buffer *size* it is a conformance
            # failure — but only because every size swept here is one §5.1 says MUST
            # work: `flush_sizes` never offers a size below the port's declaration.
            # Sizes below it are not skipped, they are asserted to be refused, further
            # down. (Until documentation#46/#48, 2026-08-11, §5.1 fixed the floor at one
            # byte for every port and this test needed no declaration at all.)
            if rc == 3 and "SOFAB_FLUSH" in env:
                print(f"  [{name}] {label}: backend refuses a buffer size at or above "
                      f"its own declared MIN_OUTPUT_BUFFER={minbuf} — §5.1 says any "
                      f"such buffer MUST work: {err}", file=sys.stderr)
                bad += 1
                continue
            if rc != 0 or len(lines) != len(inputs):
                print(f"  [{name}] {label}: rc={rc}, {len(lines)} lines, expected "
                      f"{len(inputs)}: {err}", file=sys.stderr)
                bad += 1
                continue
            # The announcement is the ONLY evidence that the driver honoured the
            # variable rather than ignored it — when the surfaces are correct their
            # stdout is byte-identical, so agreement proves nothing on its own.
            # CONTRACT.md has required it since the axis was written; until
            # 2026-08-16 it was captured here and thrown away, which made the whole
            # mechanism decorative. `new` is exempt: it is the default path, where
            # "honoured" and "ignored" are the same run by construction, and the
            # drivers deliberately stay quiet.
            missing = [tok for tok in
                       ([f"enc={env['SOFAB_ENCODE']}"] if env["SOFAB_ENCODE"] != "new" else [])
                       + ([f"flush={env['SOFAB_FLUSH']}"] if "SOFAB_FLUSH" in env else [])
                       if tok not in err]
            if missing:
                print(f"  [{name}] {label}: stderr does not announce "
                      f"{', '.join(missing)} — CONTRACT.md requires the driver to say "
                      "which configuration it ran, because stdout cannot distinguish "
                      f"honouring the variable from ignoring it. stderr was: {err!r}",
                      file=sys.stderr)
                bad += 1
                continue
            for i, (a, b) in enumerate(zip(base, lines)):
                if a != b:
                    print(f"  [{name}] {files[i]} under {label}: default={a!r} "
                          f"surface={b!r}", file=sys.stderr)
                    bad += 1

        # The contract's hard-fail: a surface the backend does not have must be an error,
        # never a silent fallback to one it does have.
        missing = [s for s in ALL_SURFACES if s not in surfaces]
        if not args.skip_hard_fail:
            for s in missing:
                tried += 1
                _, rc, _ = run(path, inputs, {"SOFAB_ENCODE": s})
                if rc == 0:
                    print(f"  [{name}] SOFAB_ENCODE={s}: backend has no such surface "
                          "(meta) but the driver exited 0 — a silent fallback reports a "
                          "mode as passing that never ran", file=sys.stderr)
                    bad += 1

        # The other half of §5.1: a streaming buffer *below* the declaration MUST be
        # refused where it is handed over, never accepted and worked around. Without
        # this a port could declare 20 to opt out of the hard sizes and still accept 1,
        # which is the declaration doing no work at all.
        #
        # Only testable for a port declaring more than 1: one short of 1 is a zero-byte
        # buffer, and SOFAB_FLUSH=0 is how the drivers spell "unset". A port declaring 1
        # therefore has no below-minimum case to check, which is correct — it accepts
        # every size the sweep can express.
        if "stream" in surfaces and minbuf > 1:
            tried += 1
            n = minbuf - 1
            _, rc, err = run(path, inputs, {"SOFAB_ENCODE": "stream",
                                            "SOFAB_FLUSH": str(n)})
            if rc != 3:
                print(f"  [{name}] SOFAB_ENCODE=stream SOFAB_FLUSH={n}: one byte below "
                      f"the declared MIN_OUTPUT_BUFFER={minbuf}, so §5.1 requires it to "
                      f"be refused at the handover — the driver exited {rc}: {err}",
                      file=sys.stderr)
                bad += 1

        # --- the §5.1 pass-through permission -------------------------------------
        #
        # An encoder MAY hand a string/blob run to its sink DIRECTLY instead of copying
        # it through the output buffer. It is wire-neutral by construction — "the output
        # is byte-identical either way" — which is precisely why neither the round-trip
        # nor the materialized oracle can see it, and why it belongs here: this gate is
        # the one that compares a *configuration* against the same driver's default.
        #
        # Optional, so `no` is a statement about the port and not a defect; only an
        # ABSENT declaration is an error, the same rule `min_output_buffer` follows.
        pt = roster.pass_through(BUILDERS[name])
        pt_note = ""
        if pt is None:
            print(f"  [{name}] meta declares no pass_through — CORELIB_PLAN §5.1 makes "
                  "the permission optional, but which ports take it must be written "
                  "down, or a port that implements it goes untested", file=sys.stderr)
            bad += 1
        elif pt and "stream" in surfaces:
            tried += 1
            env = {"SOFAB_ENCODE": "stream", "SOFAB_FLUSH": str(minbuf),
                   "SOFAB_PASSTHROUGH": "1"}
            lines, rc, err = run(path, inputs, env)
            if rc != 0 or len(lines) != len(inputs):
                print(f"  [{name}] pass-through: rc={rc}, {len(lines)} lines, expected "
                      f"{len(inputs)}: {err}", file=sys.stderr)
                bad += 1
            else:
                # (1) The permission must not change a single byte.
                diff = [files[i] for i, (a, b) in enumerate(zip(base, lines)) if a != b]
                for f in diff[:5]:
                    print(f"  [{name}] {f} under pass-through: output differs from the "
                          "default path — §5.1 requires the bytes to be identical "
                          "either way", file=sys.stderr)
                bad += len(diff)
                # (2) …and it must actually have happened. A port that accepted the
                # permission and quietly copied anyway produces identical bytes and
                # would pass (1) trivially, so the driver reports how often its sink
                # received memory that was not the output buffer. Zero means the run
                # proved nothing — the vacuous-green shape this gate exists to refuse,
                # the same reasoning behind the flush sweep's declared-minimum rule.
                m = re.search(r"passthrough handovers=(\d+)", err)
                if not m:
                    print(f"  [{name}] pass-through: driver reports no handover count "
                          "— CONTRACT.md requires it, because identical bytes cannot "
                          f"distinguish a used permission from an ignored one: {err!r}",
                          file=sys.stderr)
                    bad += 1
                elif int(m.group(1)) == 0:
                    print(f"  [{name}] pass-through: 0 handovers over {len(inputs)} "
                          "input(s) — the permission was granted and never exercised, "
                          "so this configuration asserts nothing. Either the corpus "
                          "carries no payload above the port's threshold, or the "
                          "permission is not wired.", file=sys.stderr)
                    bad += 1
                else:
                    pt_note = f", pass-through {m.group(1)} handover(s)"

        status = "OK" if not bad else "FAIL"
        have = ",".join(s for s in ALL_SURFACES if s in surfaces)
        if pt is False:
            # Said out loud rather than skipped quietly: a port that declares `no` is
            # not checked on this axis at all, because the other drivers do not yet
            # recognise SOFAB_PASSTHROUGH and would exit 0 having ignored it. Making
            # that refusal assertable is per-driver work, tracked in docs/TODO.md.
            pt_note = ", pass-through declared absent (not exercised)"
        print(f"[{name}] {len(inputs)} input(s) x {tried} config(s), surfaces={have}, "
              f"min_output_buffer={minbuf}{pt_note} — {bad} mismatch(es)  [{status}]")
        failures += bad

    print(f"\nTOTAL: {failures} encode-invariance mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
