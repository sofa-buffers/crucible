#!/usr/bin/env python3
"""Over-bound sweep (MESSAGE_SPEC §7.1) — the third sweep axis.

§7.1: a declared `count` (array) or `maxlen` (string/blob) binds **every** target
regardless of allocation strategy; a value exceeding it is malformed input and MUST
decode as `INVALID` on all implementations. F-0013 (over-index / over-count) and
F-0015 (over-maxlen) established this at specific positions. This sweep applies it at
**every** bounded position and every depth, to catch a codegen that enforces the
bound at some positions but not others (the §7.3 piecemeal-guard pattern).

For each bounded position it emits an over-bound value and expects **all 13 to
reject** (`R`), plus an at-bound control that all 13 must **accept**:

  * count:5 numeric array  -> 6 elements (M>N)          expect R ; control: 5 elements
  * count:5 fp array       -> 6 elements                expect R ; control: 5
  * maxlen:32 string       -> 33 bytes                  expect R ; control: 32
  * maxlen:4  blob         -> 5 bytes                    expect R ; control: 4
  * string_array element   -> a 65-byte element (maxlen 64)  expect R ; control: 64
  * string_array           -> an element id >= count 5 (over-index)  expect R
  * blob_array element      -> the blob analogue of both (over-maxlen + over-index);
                              exercises the _BlobSeq heap path F-0013 left untested.

WP-07 adds, per bounded position, a **mid-magnitude** over (2×bound) and a **large**
over (index `BIG` = 100_000, declared but not materialized — a well-formed element at
a huge index, small input), all expect `R`: F-0013 showed the memory-amplification bug
is a *large-index* class, and a decoder must reject at the header word without sizing a
container to the declared magnitude. (A large *over-maxlen* is inherently declared-huge
+ truncated — the §5.2 precedence corner — so it lives on the malform×truncation axis,
WP-09, not here.)

Positions and wire primitives come from `sweep_positions.py` / `gen.py`.

Usage: python3 engine/structured/sweep_overbound.py [out_dir]
       (default corpus/overbound-sweep)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    WT_FIX, WT_SEQ_BEG, WT_SEQ_END, FL_FP32, FL_FP64, FL_STRING, FL_BLOB,
    hdr, varint, fixlen, arr_u, arr_s, arr_fp,
)
from sweep_positions import POSITIONS, place  # noqa: E402

# A "large but harness-safe" over-bound (WP-07): big enough to catch a decoder that
# allocates per the DECLARED length/count/index (the F-0013 amplification class), small
# enough in *actual* bytes that a conformant decoder rejects at the header word and never
# materializes it. Not so large it OOMs the test if a driver *does* amplify (100k slots /
# 100 KB, not F-0013's 2 M) — a timeout/OOM here is itself a DoS finding.
BIG = 100_000


def _big_fixlen(fid, subtype, declared_len, payload=b"AAAA"):
    """A fixlen field whose word DECLARES `declared_len` bytes but carries only a short
    payload — over FIXLEN/maxlen, so a conformant decoder rejects at the word (§7.1)
    without reading (or allocating) the declared length."""
    return hdr(fid, WT_FIX) + varint((declared_len << 3) | subtype) + payload


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
            # WP-07: mid-magnitude over (2N elements) — still R (a count-prefixed array
            # can't declare a huge count without materializing the elements, so no BIG here).
            mk = arr_u if p.cat == "arr_u" else arr_s
            vectors.append((f"{tag}_overcount_2x.bin",
                            place(p.path, mk(p.fid, list(range(1, 2 * n + 1)))), "reject"))
        elif p.cat in ("arr_fp32", "arr_fp64"):
            n = p.count
            fmt, st = ("<f", FL_FP32) if p.cat == "arr_fp32" else ("<d", FL_FP64)
            over = arr_fp(p.fid, [1.0] * (n + 1), fmt, st)
            at = arr_fp(p.fid, [1.0] * n, fmt, st)
            vectors.append((f"{tag}_overcount.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atcount_ctl.bin", place(p.path, at), "accept"))
            vectors.append((f"{tag}_overcount_2x.bin",
                            place(p.path, arr_fp(p.fid, [1.0] * (2 * n), fmt, st)), "reject"))
        elif p.cat == "str":
            m = p.maxlen
            over = fixlen(p.fid, FL_STRING, b"A" * (m + 1))
            at = fixlen(p.fid, FL_STRING, b"A" * m)
            vectors.append((f"{tag}_overmaxlen.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atmaxlen_ctl.bin", place(p.path, at), "accept"))
            # WP-07: mid (2*maxlen bytes) + large declared-but-not-materialized (BIG)
            vectors.append((f"{tag}_overmaxlen_2x.bin",
                            place(p.path, fixlen(p.fid, FL_STRING, b"A" * (2 * m))), "reject"))
            # NB: a large *over-maxlen* is inherently a declared-huge-length + short-payload
            # fixlen, i.e. over-maxlen AND truncated — the §5.2 over-length-vs-INCOMPLETE
            # precedence corner (splits R-vs-I; documentation#15-adjacent). That belongs to
            # the malform×truncation axis (WP-09), not this clean-magnitude axis, so the
            # large over-len case is deliberately NOT here — the large over-INDEX below is
            # the amplification test (declared big, complete element, small input).
        elif p.cat == "blob":
            m = p.maxlen
            over = fixlen(p.fid, FL_BLOB, b"\x11" * (m + 1))
            at = fixlen(p.fid, FL_BLOB, b"\x11" * m)
            vectors.append((f"{tag}_overmaxlen.bin", place(p.path, over), "reject"))
            vectors.append((f"{tag}_atmaxlen_ctl.bin", place(p.path, at), "accept"))
            vectors.append((f"{tag}_overmaxlen_2x.bin",
                            place(p.path, fixlen(p.fid, FL_BLOB, b"\x11" * (2 * m))), "reject"))
        elif p.cat == "seq_wrapper":
            m, n = p.maxlen, p.count
            # element fixlen subtype follows the wrapper's declared element type
            # (str -> FL_STRING, blob -> FL_BLOB) so the ONLY irregularity is the bound.
            st = FL_BLOB if p.elem == "blob" else FL_STRING
            def _wrap(elem):  # one element inside the wrapper sequence
                return hdr(p.fid, WT_SEQ_BEG) + elem + bytes([WT_SEQ_END])
            # over-maxlen element (element 0, m+1 bytes) -> reject
            vectors.append((f"{tag}_elem_overmaxlen.bin",
                            place(p.path, _wrap(fixlen(0, st, b"A" * (m + 1)))), "reject"))
            # over-index element (id == count n, i.e. >= n) -> reject
            vectors.append((f"{tag}_elem_overindex.bin",
                            place(p.path, _wrap(fixlen(n, st, b"A"))), "reject"))
            # at-bound control: element 0, m bytes -> accept
            vectors.append((f"{tag}_elem_atmaxlen_ctl.bin",
                            place(p.path, _wrap(fixlen(0, st, b"A" * m))), "accept"))
            # WP-07: mid + large over-INDEX (element id 2N / BIG — declared, small input;
            # a decoder must reject without sizing a container to the index — the F-0013
            # amplification class). The element itself is well-formed, so no truncation.
            vectors.append((f"{tag}_elem_overindex_2x.bin",
                            place(p.path, _wrap(fixlen(2 * n, st, b"A"))), "reject"))
            vectors.append((f"{tag}_elem_overindex_big.bin",
                            place(p.path, _wrap(fixlen(BIG, st, b"A"))), "reject"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, exp in vectors:
        by[exp] = by.get(exp, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


# --- union pass (schema/probe-union.sofab.yaml) ------------------------------
# WP-01: §7.1 over the union schema's bounded members — as_text (maxlen 16) and
# as_blob (maxlen 8). A member over its maxlen is malformed input and MUST decode as
# INVALID on all implementations, exactly like a bounded field at any other position;
# an at-bound member is a valid single-member union (accept control). maxlen is a
# schema fact, so a divergence here points at generated code, not the corelib.
def emit_union(out_dir):
    from sweep_positions import UNION_MEMBER_POSITIONS, place  # noqa: E402
    vectors = []
    for p in UNION_MEMBER_POSITIONS:
        if p.cat not in ("str", "blob"):
            continue
        st = FL_STRING if p.cat == "str" else FL_BLOB
        fill = b"A" if p.cat == "str" else b"\x11"
        m = p.maxlen
        vectors.append((f"u_{p.tag()}_overmaxlen.bin",
                        place(p.path, fixlen(p.fid, st, fill * (m + 1))), "reject"))
        vectors.append((f"u_{p.tag()}_atmaxlen_ctl.bin",
                        place(p.path, fixlen(p.fid, st, fill * m)), "accept"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/overbound-sweep"
    emit(out)
