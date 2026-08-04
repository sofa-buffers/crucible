#!/usr/bin/env python3
"""Chunk-invariance oracle — one driver against itself, split versus whole.

CORELIB_PLAN §6.4 states it for UTF-8 and §7.2 item 4 for the decoder at large: **a
chunk boundary must not change the outcome**. So however a record is cut up on its way
into one decoder, the canonical line must be the one feeding it whole produces.

Three ways of cutting it, because they find different things (drivers/common/CONTRACT.md,
"The streaming axes"):

* `SOFAB_SPLIT=k` — two chunks, `[0,k)` then `[k,end)`. Swept over every interior `k`, so
  every metadata/payload boundary in the message is cut, without the harness needing to
  know where those boundaries are. When it fails it also says *which* boundary.
* `SOFAB_CHUNK=n` — fixed-size chunks. `n=1` is the strong one: every varint, length word
  and payload is split, so any parse state a decoder fails to carry across a `feed` shows
  up. A two-way split can straddle exactly the boundary that breaks; byte-at-a-time
  cannot miss it.
* `SOFAB_CHUNK_SCRUB=1` — overwrite each chunk's buffer once `feed` returns. This one is
  not about boundaries at all: a decoder that *borrows* from a fed chunk instead of
  copying out of it reads back scrubbed bytes. crucible#132 reports corelib-zig doing
  exactly that for a `string`/`blob` arriving whole in one chunk.

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

A driver opts in by honouring the variables. A driver that ignores them emits
byte-identical output, which is indistinguishable from passing — so drivers are
named explicitly by the caller and never inferred.
"""

import argparse
import os
import struct
import subprocess
import sys

import roster

ROOT = roster.ROOT

# name -> absolute path, from drivers/roster — the one place the roster is stated.
DRIVERS = roster.drivers(roster.gate_tag())

# Fixed chunk sizes to try. 1 is the one that matters — it splits every varint, length
# word and payload. The rest are cheap and catch a decoder that carries state correctly
# across a 1-byte feed but not across a boundary landing mid-payload. Sizes >= the
# longest input degrade to the whole-message case and are dropped.
CHUNK_SIZES = (1, 2, 3, 5, 8, 16)


def feed(path, inputs, env=None):
    """Run a driver over `inputs`, returning one canonical line per input."""
    blob = b"".join(struct.pack("<I", len(d)) + d for d in inputs)
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run([path], input=blob, capture_output=True, env=e, timeout=120)
    return p.stdout.decode(errors="replace").splitlines()


def configs(maxlen, modes):
    """(label, env, applies) for every chunking to try against the whole-message line.

    `applies(n)` says whether the config actually cuts an input of length `n`. A config
    that does not cut it degrades to the whole-message case, which is trivially equal and
    only dilutes the count.
    """
    if "split" in modes:
        # k = 0 and k = len are the whole-message case and add nothing.
        for k in range(1, maxlen):
            yield f"SOFAB_SPLIT={k}", {"SOFAB_SPLIT": str(k)}, (lambda n, k=k: k < n)
    if "chunk" in modes:
        for c in CHUNK_SIZES:
            if c < maxlen:
                yield f"SOFAB_CHUNK={c}", {"SOFAB_CHUNK": str(c)}, (lambda n, c=c: c < n)
    if "scrub" in modes:
        # Scrubbing is a lifetime check, not a boundary one, so it only needs the
        # cut that guarantees every field is touched: one byte at a time.
        yield ("SOFAB_CHUNK=1 SOFAB_CHUNK_SCRUB=1",
               {"SOFAB_CHUNK": "1", "SOFAB_CHUNK_SCRUB": "1"},
               (lambda n: n > 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--drivers", required=True,
                    help="comma/space-separated driver names that honour the variables")
    ap.add_argument("--modes", default="split,chunk,scrub",
                    help="which cuts to try: split, chunk, scrub (default: all)")
    args = ap.parse_args()

    names = [n for n in args.drivers.replace(",", " ").split() if n]
    unknown = [n for n in names if n not in DRIVERS]
    if unknown:
        print(f"unknown driver(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    modes = {m for m in args.modes.replace(",", " ").split() if m}

    files = sorted(f for f in os.listdir(args.corpus)
                   if not f.endswith(".md") and f != ".gitkeep")
    inputs = [open(os.path.join(args.corpus, f), "rb").read() for f in files]
    if not inputs:
        print("empty corpus", file=sys.stderr)
        return 2
    maxlen = max(len(d) for d in inputs)

    failures = 0
    for name in names:
        path = DRIVERS[name]
        whole = feed(path, inputs)
        if len(whole) != len(inputs):
            print(f"  [{name}] emitted {len(whole)} lines for {len(inputs)} inputs — "
                  "not contract-conformant, skipping", file=sys.stderr)
            failures += 1
            continue

        bad = tried = 0
        for label, env, applies in configs(maxlen, modes):
            tried += 1
            split = feed(path, inputs, env)
            if len(split) != len(inputs):
                print(f"  [{name}] {label}: {len(split)} lines, expected "
                      f"{len(inputs)}", file=sys.stderr)
                bad += 1
                continue
            for i, (a, b) in enumerate(zip(whole, split)):
                if a != b and applies(len(inputs[i])):
                    print(f"  [{name}] {files[i]} under {label}: whole={a!r} "
                          f"chunked={b!r}", file=sys.stderr)
                    bad += 1
        status = "OK" if not bad else "FAIL"
        print(f"[{name}] {len(inputs)} input(s) x {tried} chunking(s) — "
              f"{bad} mismatch(es)  [{status}]")
        failures += bad

    print(f"\nTOTAL: {failures} chunk-invariance mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
