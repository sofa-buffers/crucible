#!/usr/bin/env python3
"""Chunk-invariance oracle — one driver against itself, split versus whole.

CORELIB_PLAN §6.4 states it for UTF-8 and §7.2 item 4 for the decoder at large: **a
chunk boundary must not change the outcome**. So for input `d` and split point `k`,
feeding `d[:k]` then `d[k:]` into one decoder must yield the canonical line that
feeding `d` whole yields.

Two properties this checks that nothing else in the suite can:

1. **Chunk invariance.** The replay driver feeds each record whole, so a defect that
   only appears at a chunk boundary is invisible to every differential gate.
2. **Resumability.** An `I` must actually resume. corelib-cpp's raw blob read
   returned `INVALID` and then dropped the buffered tail, so the message never
   completed even after the remaining bytes arrived (crucible#130). A harness that
   reads only the first feed's label cannot see that class at all.

Unlike every other oracle here this one is **not differential** — it compares a
driver against itself. That is what makes it worth landing one driver at a time, and
it is also the only way to catch a defect the whole family shares.

A driver opts in by honouring `SOFAB_SPLIT=k`. A driver that ignores it emits
byte-identical output, which is indistinguishable from passing — so drivers are
named explicitly by the caller and never inferred.
"""

import argparse
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# name -> path, mirroring scripts/run.sh.
DRIVERS = {
    "c": "drivers/c/build/driver",
    "go": "drivers/go/build/driver",
    "rust-std": "drivers/rust/build/rs/target/debug/harness",
    "rust-nostd": "drivers/rust/build/rs-no-std/target/debug/harness",
    "cpp": "drivers/cpp/build/cpp/driver",
    "cpp-c-cpp": "drivers/cpp/build/c-cpp/driver",
    "py-cython": "drivers/python/build/py-cython",
    "py-pure": "drivers/python/build/py-pure",
    "java": "drivers/java/build/driver",
    "typescript": "drivers/ts/build/driver",
    "csharp": "drivers/cs/build/driver",
    "zig": "drivers/zig/build/driver",
    "dart": "drivers/dart/build/driver",
}


def feed(path, inputs, env=None):
    """Run a driver over `inputs`, returning one canonical line per input."""
    blob = b"".join(struct.pack("<I", len(d)) + d for d in inputs)
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([path], input=blob, capture_output=True, env=e, timeout=120)
    return p.stdout.decode(errors="replace").splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--drivers", required=True,
                    help="comma/space-separated driver names that honour SOFAB_SPLIT")
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
        path = os.path.join(ROOT, DRIVERS[name])
        whole = feed(path, inputs)
        if len(whole) != len(inputs):
            print(f"  [{name}] emitted {len(whole)} lines for {len(inputs)} inputs — "
                  "not contract-conformant, skipping", file=sys.stderr)
            failures += 1
            continue

        # Sweep every interior split point. k = 0 and k = len are the whole-message
        # case and add nothing; every metadata/payload boundary is covered by
        # construction, without the harness needing to know where they are.
        maxlen = max(len(d) for d in inputs)
        bad = 0
        for k in range(1, maxlen):
            split = feed(path, inputs, {"SOFAB_SPLIT": str(k)})
            if len(split) != len(inputs):
                print(f"  [{name}] SOFAB_SPLIT={k}: {len(split)} lines, expected "
                      f"{len(inputs)}", file=sys.stderr)
                bad += 1
                continue
            for i, (a, b) in enumerate(zip(whole, split)):
                if a != b and k < len(inputs[i]):
                    print(f"  [{name}] {files[i]} split at {k}: whole={a!r} "
                          f"split={b!r}", file=sys.stderr)
                    bad += 1
        status = "OK" if not bad else "FAIL"
        print(f"[{name}] {len(inputs)} input(s) x {maxlen - 1} split point(s) — "
              f"{bad} mismatch(es)  [{status}]")
        failures += bad

    print(f"\nTOTAL: {failures} chunk-invariance mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
