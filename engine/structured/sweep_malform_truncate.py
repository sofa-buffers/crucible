#!/usr/bin/env python3
"""Malformation × truncation sweep (MESSAGE_SPEC §5.2 precedence) — the sixth sweep axis.

§5.2: INVALID is *"malformed regardless of what follows"* — it **dominates** INCOMPLETE.
So a message that contains a definitively-malformed construct **and then** ends mid-item
(truncated) must still decode to **INVALID** (`R`), never INCOMPLETE (`I`). The earlier
precedence findings each pinned one impl on one construct (F-0006/F-0007 C/Py fixlen,
F-0012 TS skip-path, F-0014 array element word); F-0024 showed the whole class is still
open in the Rust backend, where the generated `try_decode` propagates `feed`'s
`Err(Incomplete)` via `?` *before* the visitor's sticky `inv` flag is consulted — so a
malformation followed by any truncation flips `R` → `I`.

This axis generalizes F-0024: for **every** kind of definitively-INVALID construct, emit
two vectors —

  * `<m>_complete`  — the malformation as a whole message           → expect **reject**
                      (the control: establishes the construct *is* INVALID; a divergence
                      here is a different bug, a plain malformation split.)
  * `<m>_trunc`     — the same malformation **+ a truncated tail**   → expect **reject**
                      (the §5.2 test: INVALID must still win. An impl that emits `I` here
                      let INCOMPLETE override the malformation — the F-0024 shape.)

The truncated tail is a lone `0x8a`: a byte that opens a varint header with no
continuation, so a naive decoder ends mid-varint (`at_boundary()` false → Incomplete)
unless the earlier INVALID is remembered. A pair of **valid**-message controls
(`valid_complete` → accept, `valid_trunc` → not_reject) anchors that the tail alone does
not force a reject.

Two oracles (engine/structured/sweep_run.py): agreement (all 13 same verdict) +
conformance (expect=reject ⇒ every driver `R`). A family-wide `I` on a `_trunc` vector is
agreement-green but conformance-red — exactly the §5.2 gap this axis exists to catch.

Positions / primitives come from `sweep_positions.py` / `gen.py`; the reserved-subtype
builder is shared with `sweep_reserved_subtype.py`.

Usage: python3 engine/structured/sweep_malform_truncate.py [out_dir]
       (default corpus/malform-truncate-sweep)
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import hdr, varint, WT_FIX, WT_SEQ_BEG, WT_SEQ_END, FL_STRING, FL_BLOB, arr_u  # noqa: E402
from sweep_positions import place  # noqa: E402

TRUNC = b"\x8a"  # opens a varint header, no continuation byte → mid-varint EOF


def fixlen_reserved(fid, subtype=0x5, payload=b"\x00\x00"):
    """A fixlen field carrying a reserved subtype (0x4-0x7) — INVALID per §4.6."""
    return hdr(fid, WT_FIX) + varint((len(payload) << 3) | subtype) + payload


def invalid_utf8_str(fid, payload=b"\xff\xff"):
    """A string field whose bytes are not valid UTF-8 — INVALID per §8 (F-0004)."""
    return hdr(fid, WT_FIX) + varint((len(payload) << 3) | FL_STRING) + payload


def over_len_str(fid, n):
    """A string longer than the field's maxlen — INVALID (schema bound)."""
    return hdr(fid, WT_FIX) + varint((n << 3) | FL_STRING) + b"A" * n


def over_len_blob(fid, n):
    """A blob longer than the field's maxlen — INVALID (schema bound)."""
    return hdr(fid, WT_FIX) + varint((n << 3) | FL_BLOB) + b"\x00" * n


def over_count_arr(fid, n):
    """An unsigned array with more elements than the schema count — INVALID (F-0003)."""
    return arr_u(fid, list(range(1, n + 1)))


def string_array_over_id(idx=5):
    """A string_array wrapper element at id >= count (5) — INVALID (schema bound)."""
    elem = hdr(idx, WT_FIX) + varint((1 << 3) | FL_STRING) + b"A"
    return hdr(200, WT_SEQ_BEG) + elem + bytes([WT_SEQ_END])


# Each entry: (name, definitively-INVALID complete message body).
# Placed at a schema-appropriate position so the *only* irregularity is the malformation.
def malformations():
    out = []
    # reserved fixlen subtype — invalid anywhere; test at a scalar id and inside a scope
    out.append(("reserved_subtype_top",      fixlen_reserved(0)))
    out.append(("reserved_subtype_nested",   place((10,), fixlen_reserved(2))))
    out.append(("reserved_subtype_wrapper",  place((200,), fixlen_reserved(0))))
    # invalid UTF-8 — at the nested string field and at a string_array element
    out.append(("invalid_utf8_nested_str",   place((10,), invalid_utf8_str(2))))
    out.append(("invalid_utf8_wrapper_elem", place((200,), invalid_utf8_str(0))))
    # over-length string / blob (nested.str maxlen 32, nested.bytes_field maxlen 4)
    out.append(("over_len_string",           place((10,), over_len_str(2, 33))))
    out.append(("over_len_blob",             place((10,), over_len_blob(3, 5))))
    # over-count numeric array (arrays.u8 count 5) — 6 elements
    out.append(("over_count_array",          place((100,), over_count_arr(0, 6))))
    # string_array element id >= count
    out.append(("string_array_over_id",      string_array_over_id(5)))
    return out


def valid_probe():
    """A minimal valid message (a single in-range scalar) for the tail-alone controls."""
    from gen import scalar_u
    return scalar_u(0, 7)


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for name, body in malformations():
        vectors.append((f"{name}_complete.bin", body, "reject"))
        vectors.append((f"{name}_trunc.bin", body + TRUNC, "reject"))
    # tail-alone controls: the truncation byte must not, by itself, force a reject
    v = valid_probe()
    vectors.append(("valid_complete.bin", v, "accept"))
    vectors.append(("valid_trunc.bin", v + TRUNC, "not_reject"))

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items()))
          + f"  ({len(malformations())} malformations × {{complete, trunc}} + 2 controls)")
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/malform-truncate-sweep"
    emit(out)
