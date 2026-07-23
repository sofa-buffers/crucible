#!/usr/bin/env python3
"""Minimal isolates — clean inputs that a finding's *original* reproducer can't express.

Most resolved findings kept their original reproducer in `findings/<id>/`, and that file
is the regression test. Some findings' originals are **contaminated**: they trip the
still-open INVALID-vs-INCOMPLETE precedence spec-hole
([documentation#15](https://github.com/sofa-buffers/documentation/issues/15)) *as well
as* the bug they were filed for, so the family legitimately splits on them and they can
never join a green gate. Their write-ups instead assert the fix against a **clean
isolate** quoted only as prose hex (the F-0004 lesson: characterize a divergence with a
minimal isolate, not a raw fuzzer input).

This script materializes those isolates as real files, so a claim like "all 13 agree"
is executable rather than prose. Wire primitives are imported from `gen.py` — the one
reference encoder — so an encoding change cannot silently desync them.

Each isolate declares its own destination: a *green* isolate goes to
`corpus/regression/` (the gate); a *diverging* one is a finding reproducer and goes to
`findings/<id>/`. Regenerating is idempotent — the committed bytes are the contract.

Usage: python3 engine/structured/isolates.py [repo_root]   (default: cwd)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, arr_u, fstr, hdr

# schema/probe.sofab.yaml: every array is `count: 5`; string_array is id 200.
SCHEMA_COUNT = 5


def f0003_overcount_clean() -> bytes:
    """F-0003 / generator#100 — a *clean* (non-truncated) over-count scalar array.

    `a6 06 03 08 01 02 03 04 05 06 07 08 07` — the arrays struct (id 100) carrying a u8
    array (id 0) whose wire count is 8, over the schema's count of 5. Per MESSAGE_SPEC
    §3+§7 an over-count array is INVALID, so every driver must reject (`R`).

    Contrast the kept original `array_overflow.bin`, which is over-count *and*
    truncated: there rust reports `I` (lazy — runs out of bytes first) and the family
    `R`, which is documentation#15's precedence hole, not the over-count axis. This is
    the exact input STATUS.md / FINDINGS.md quote as the 2026-07-15 re-verification.
    """
    return (
        hdr(100, WT_SEQ_BEG)
        + arr_u(0, [1, 2, 3, 4, 5, 6, 7, 8])  # count 8 > schema count 5
        + bytes([WT_SEQ_END])
    )


def f0012_overindex_clean() -> bytes:
    """F-0013 / G-0013 — a string_array element at an index at/beyond the schema count.

    `c6 0c c2 07 0a 78 07` — string_array (id 200) opened, one fixlen-string element at
    wire index 120 (>= the schema count of 5), closed. Complete and non-truncated, so it
    isolates the over-index axis alone (no documentation#15 precedence contamination).

    The family splits on the *value*, all accepting: the fixed-capacity profiles (c,
    cpp-c-cpp, rust-nostd) drop the element per MESSAGE_SPEC §5.1, while every heap
    profile keeps it at index 120. See the finding's NOTES.md.
    """
    return (
        hdr(200, WT_SEQ_BEG)
        + fstr(120, "x")  # element index 120 >= schema count 5
        + bytes([WT_SEQ_END])
    )


def f0012_overindex_amplify() -> bytes:
    """F-0013 / G-0013 — the memory-amplification probe (same shape, huge index).

    `c6 0c 82 c8 d0 07 0a 78 07` — 9 bytes claiming element index 2,000,000. The heap
    profiles' unbounded `while (len <= id) push(default)` fill materializes id+1
    elements, so this 9-byte input costs cpp ~226 MB / go ~122 MB of RSS while the
    fixed-capacity profiles stay flat at ~8 MB. The index is a varint (up to 2^64), so
    an attacker raises it until OOM. Not a gate input — it is the DoS evidence.
    """
    return (
        hdr(200, WT_SEQ_BEG)
        + fstr(2_000_000, "x")
        + bytes([WT_SEQ_END])
    )


# (destination dir, filename, builder)
ISOLATES = [
    ("corpus/regression", "F0003_overcount_clean.bin", f0003_overcount_clean),
    ("findings/F-0013-overindex-string-array-element-kept-vs-dropped",
     "overindex_clean.bin", f0012_overindex_clean),
    ("findings/F-0013-overindex-string-array-element-kept-vs-dropped",
     "overindex_amplify.bin", f0012_overindex_amplify),
]


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    for subdir, name, fn in ISOLATES:
        out_dir = os.path.join(root, subdir)
        os.makedirs(out_dir, exist_ok=True)
        data = fn()
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        print(f"{subdir}/{name:26s} {len(data):3d} B  {data.hex()}")


if __name__ == "__main__":
    main()
