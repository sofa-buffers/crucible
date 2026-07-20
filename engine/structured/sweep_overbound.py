#!/usr/bin/env python3
"""Over-bound sweep (MESSAGE_SPEC §7.1) — the third sweep axis.

§7.1: a declared `count` (array) or `maxlen` (string/blob) binds **every** target
regardless of allocation strategy; a value exceeding it is malformed input and MUST
decode as `INVALID` on all implementations. F-0013 (over-index / over-count) and
F-0015 (over-maxlen) established this at specific positions. This sweep applies it at
**every** bounded position and every depth, to catch a codegen that enforces the
bound at some positions but not others (the §7.3 piecemeal-guard pattern).

For each bounded position it emits an over-bound value and expects **all 12 to
reject** (`R`), plus an at-bound control that all 12 must **accept**:

  * count:5 numeric array  -> 6 elements (M>N)          expect R ; control: 5 elements
  * count:5 fp array       -> 6 elements                expect R ; control: 5
  * maxlen:32 string       -> 33 bytes                  expect R ; control: 32
  * maxlen:4  blob         -> 5 bytes                    expect R ; control: 4
  * string_array element   -> a 65-byte element (maxlen 64)  expect R ; control: 64
  * string_array           -> an element id >= count 5 (over-index)  expect R

Positions and wire primitives come from `sweep_positions.py` / `gen.py`.

Usage: python3 engine/structured/sweep_overbound.py [out_dir]
       (default corpus/overbound-sweep)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    WT_SEQ_BEG, WT_SEQ_END, FL_FP32, FL_FP64, FL_STRING, FL_BLOB,
    hdr, fixlen, arr_u, arr_s, arr_fp,
)
from sweep_positions import POSITIONS, place  # noqa: E402


def emit(out_dir):
    vectors = []  # (name, bytes, expect)  expect in {"reject","accept"}

    for p in POSITIONS:
        tag = p.tag()
        if p.cat in ("arr_u", "arr_s"):
            n = p.count
            over = arr_u(p.fid, list(range(1, n + 2))) if p.cat == "arr_u" \
                else arr_s(p.fid, list(range(1, n + 2)))
            at = arr_u(p.fid, list(range(1, n + 1))) if p.cat == "arr_u" \
                else arr_s(p.fid, list(range(1, n + 1)))
            vectors.append((f"{tag}_overcount.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atcount_ctl.bin", place(p.path, at), "accept"))
        elif p.cat in ("arr_fp32", "arr_fp64"):
            n = p.count
            fmt, st = ("<f", FL_FP32) if p.cat == "arr_fp32" else ("<d", FL_FP64)
            over = arr_fp(p.fid, [1.0] * (n + 1), fmt, st)
            at = arr_fp(p.fid, [1.0] * n, fmt, st)
            vectors.append((f"{tag}_overcount.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atcount_ctl.bin", place(p.path, at), "accept"))
        elif p.cat == "str":
            m = p.maxlen
            over = fixlen(p.fid, FL_STRING, b"A" * (m + 1))
            at = fixlen(p.fid, FL_STRING, b"A" * m)
            vectors.append((f"{tag}_overmaxlen.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atmaxlen_ctl.bin", place(p.path, at), "accept"))
        elif p.cat == "blob":
            m = p.maxlen
            over = fixlen(p.fid, FL_BLOB, b"\x11" * (m + 1))
            at = fixlen(p.fid, FL_BLOB, b"\x11" * m)
            vectors.append((f"{tag}_overmaxlen.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atmaxlen_ctl.bin", place(p.path, at), "accept"))
        elif p.cat == "seq_wrapper":
            m, n = p.maxlen, p.count
            # over-maxlen element (element 0, m+1 bytes) -> reject
            over_len = hdr(p.fid, WT_SEQ_BEG) + fixlen(0, FL_STRING, b"A" * (m + 1)) + bytes([WT_SEQ_END])
            vectors.append((f"{tag}_elem_overmaxlen.bin", place(p.path, over_len), "reject"))
            # over-index element (id == count n, i.e. >= n) -> reject
            over_idx = hdr(p.fid, WT_SEQ_BEG) + fixlen(n, FL_STRING, b"A") + bytes([WT_SEQ_END])
            vectors.append((f"{tag}_elem_overindex.bin", place(p.path, over_idx), "reject"))
            # at-bound control: element 0, m bytes -> accept
            at = hdr(p.fid, WT_SEQ_BEG) + fixlen(0, FL_STRING, b"A" * m) + bytes([WT_SEQ_END])
            vectors.append((f"{tag}_elem_atmaxlen_ctl.bin", place(p.path, at), "accept"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, exp in vectors:
        by[exp] = by.get(exp, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/overbound-sweep"
    emit(out)
