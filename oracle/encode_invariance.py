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

`meta`'s `encode_surfaces` says which surfaces a backend has. A driver that ignores the
variables emits byte-identical output, indistinguishable from passing, so the drivers to
run are named explicitly by the caller and never inferred.
"""

import argparse
import os
import struct
import subprocess
import sys

import roster

ROOT = roster.ROOT
DRIVERS = roster.drivers(roster.gate_tag())
BUILDERS = {name: builder for name, builder, _, _, _ in roster.rows(roster.gate_tag())}

# OStream buffer sizes for the streaming surface. 1 is the strong one — the sink sees
# the message one byte at a time, so every internal buffer boundary is crossed. The rest
# are cheap and land the boundary at different offsets inside varints and payloads.
FLUSH_SIZES = (1, 2, 3, 5, 8, 16)

ALL_SURFACES = ("new", "to", "stream")


def run(path, inputs, env=None):
    """Run a driver over `inputs`; returns (lines, returncode, stderr)."""
    blob = b"".join(struct.pack("<I", len(d)) + d for d in inputs)
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([path], input=blob, capture_output=True, env=e, timeout=120)
    return (p.stdout.decode(errors="replace").splitlines(), p.returncode,
            p.stderr.decode(errors="replace").strip())


def configs(surfaces):
    """(label, env) for every encode surface this backend has, flush sizes included."""
    for s in ALL_SURFACES:
        if s not in surfaces:
            continue
        yield f"SOFAB_ENCODE={s}", {"SOFAB_ENCODE": s}
        if s == "stream":
            for n in FLUSH_SIZES:
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
        for label, env in configs(surfaces):
            tried += 1
            lines, rc, err = run(path, inputs, env)
            if rc != 0 or len(lines) != len(inputs):
                print(f"  [{name}] {label}: rc={rc}, {len(lines)} lines, expected "
                      f"{len(inputs)}: {err}", file=sys.stderr)
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

        status = "OK" if not bad else "FAIL"
        have = ",".join(s for s in ALL_SURFACES if s in surfaces)
        print(f"[{name}] {len(inputs)} input(s) x {tried} config(s), surfaces={have} — "
              f"{bad} mismatch(es)  [{status}]")
        failures += bad

    print(f"\nTOTAL: {failures} encode-invariance mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
