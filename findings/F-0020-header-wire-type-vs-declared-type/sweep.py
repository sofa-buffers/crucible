#!/usr/bin/env python3
"""Enumerate the header-wire-type axis for schema/probe.sofab.yaml.

  python3 sweep.py <outdir> [single|pairs]

`single` (default) emits one field per vector: every top-level field id x every
wire type -> 66 vectors, of which 11 are correctly typed (the controls) and 55
are mismatches. `pairs` emits the same field id twice with differing wire types
(330 vectors) — the repetition axis, kept here because it was how the finding was
first hit; the single-field sweep is the one that isolates it.

Wire types 5 (array-fixlen) and 7 (bare sequence-end) are omitted: 5 needs an
element word this sweep would have to invent, 7 is not a field encoding.
"""
import itertools, os, sys

def varint(n):
    b = bytearray()
    while True:
        x = n & 0x7F; n >>= 7
        b.append(x | (0x80 if n else 0))
        if not n:
            return bytes(b)

def hdr(fid, wt):
    return varint((fid << 3) | wt)

BODY = {
    0: bytes([0x05]),        # unsigned varint = 5
    1: bytes([0x06]),        # signed varint, zigzag 6 -> 3
    2: bytes([0x0a, 0x41]),  # fixlen: word (len 1, subtype 2 = string) + 'A'
    3: bytes([0x01, 0x05]),  # array unsigned: count 1, value 5
    4: bytes([0x01, 0x06]),  # array signed:   count 1, zigzag 6
    6: bytes([0x07]),        # sequence start -> immediate sequence end
}
TYPES = sorted(BODY)

# top-level ids and their declared wire type (the 11 controls)
DECLARED = {0: 0, 1: 1, 2: 0, 3: 1, 4: 0, 5: 1, 6: 0, 7: 1, 10: 6, 100: 6, 200: 6}

out = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "single"
os.makedirs(out, exist_ok=True)

n = 0
if mode == "single":
    for fid, t in itertools.product(DECLARED, TYPES):
        open(f"{out}/f{fid:03d}_t{t}.bin", "wb").write(hdr(fid, t) + BODY[t])
        n += 1
    matches = sum(1 for fid, t in itertools.product(DECLARED, TYPES) if DECLARED[fid] == t)
    print(f"{n} vectors ({matches} correctly typed, {n - matches} mismatched)")
else:
    for fid, (t1, t2) in itertools.product(DECLARED, itertools.permutations(TYPES, 2)):
        open(f"{out}/f{fid:03d}_t{t1}_t{t2}.bin", "wb").write(
            hdr(fid, t1) + BODY[t1] + hdr(fid, t2) + BODY[t2])
        n += 1
    print(f"{n} vectors ({len(DECLARED)} fields x {len(TYPES)}x{len(TYPES)-1} type pairs)")
