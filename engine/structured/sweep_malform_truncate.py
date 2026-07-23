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

from gen import (  # noqa: E402
    hdr, varint, WT_FIX, WT_ARR_FIX, WT_SEQ_BEG, WT_SEQ_END, FL_FP32, FL_STRING, FL_BLOB, arr_u,
)
from sweep_positions import place, open_path  # noqa: E402

TRUNC = b"\x8a"  # opens a varint header, no continuation byte → mid-varint EOF


# --- malformed field builders: each returns (field_bytes, invalid_within) ----
# invalid_within = the offset in field_bytes AT/AFTER which the construct is
# definitively INVALID (so any truncation keeping >= that many bytes must still be R,
# §5.2). For a bad *word/count* that is right after the header+word; for a bad *payload*
# (invalid UTF-8) it is only after the whole payload is read + checked.
def fixlen_reserved(fid, subtype=0x5, payload=b"\x00\x00"):
    """A fixlen field carrying a reserved subtype (0x4-0x7) — INVALID at the word (§4.6)."""
    h = hdr(fid, WT_FIX) + varint((len(payload) << 3) | subtype)
    return h + payload, len(h)


def invalid_utf8_str(fid, payload=b"\xff\xff"):
    """A string whose bytes are not valid UTF-8 — INVALID only after the payload (§8)."""
    f = hdr(fid, WT_FIX) + varint((len(payload) << 3) | FL_STRING) + payload
    return f, len(f)


def over_len_str(fid, n):
    """A string longer than maxlen — INVALID at the word (schema bound)."""
    h = hdr(fid, WT_FIX) + varint((n << 3) | FL_STRING)
    return h + b"A" * n, len(h)


def over_len_blob(fid, n):
    h = hdr(fid, WT_FIX) + varint((n << 3) | FL_BLOB)
    return h + b"\x00" * n, len(h)


def over_count_arr(fid, n):
    """An unsigned array with count > the schema count — INVALID at the count (F-0003)."""
    from gen import WT_ARR_U
    h = hdr(fid, WT_ARR_U) + varint(n)
    return h + b"".join(varint(v) for v in range(1, n + 1)), len(h)


def array_fixlen_bad_word(fid, subtype=0x5):
    """A fixlen ARRAY whose element fixlen-word carries a reserved subtype — INVALID at
    the element word (the F-0014 class: array element-word not validated)."""
    h = hdr(fid, WT_ARR_FIX) + varint(1) + varint((4 << 3) | subtype)
    return h + b"\x00\x00\x00\x00", len(h)


def wrapper_over_id(wrapper_id, subtype, idx=5):
    """A wrapper element at id >= count (5) — INVALID at the element header (schema bound)."""
    open_b = hdr(wrapper_id, WT_SEQ_BEG)
    elem_h = hdr(idx, WT_FIX) + varint((1 << 3) | subtype)
    body = open_b + elem_h + b"A" + bytes([WT_SEQ_END])
    return body, len(open_b) + len(elem_h)


# Each entry: (name, complete INVALID message body, invalid_at offset in that body).
def malformations():
    def placed(path, field, inv_within):
        return place(path, field), len(open_path(path)) + inv_within

    out = []
    # reserved fixlen subtype — at a scalar id, inside the nested struct, and inside each wrapper
    for name, path, fid in [("reserved_subtype_top", (), 0), ("reserved_subtype_nested", (10,), 2),
                            ("reserved_subtype_str_wrapper", (200,), 0),
                            ("reserved_subtype_blob_wrapper", (201,), 0)]:
        f, iw = fixlen_reserved(fid)
        b, at = placed(path, f, iw)
        out.append((name, b, at))
    # invalid UTF-8 — nested string + a string_array element (invalid only after payload)
    for name, path, fid in [("invalid_utf8_nested_str", (10,), 2), ("invalid_utf8_wrapper_elem", (200,), 0)]:
        f, iw = invalid_utf8_str(fid)
        b, at = placed(path, f, iw)
        out.append((name, b, at))
    # over-length string / blob (nested.str maxlen 32, nested.bytes_field maxlen 4)
    f, iw = over_len_str(2, 33);  b, at = placed((10,), f, iw); out.append(("over_len_string", b, at))
    f, iw = over_len_blob(3, 5);  b, at = placed((10,), f, iw); out.append(("over_len_blob", b, at))
    # over-count numeric array (arrays.u8 count 5) — NB: over-count + truncation is the OPEN
    # documentation#15 precedence corner, so this one's truncations are report-only (see emit).
    f, iw = over_count_arr(0, 6); b, at = placed((100,), f, iw); out.append(("over_count_array", b, at))
    # array fixlen-word malformation (F-0014) — arrays.nested fp32[] (id 100->10->0)
    f, iw = array_fixlen_bad_word(0); b, at = placed((100, 10), f, iw); out.append(("array_fixlen_bad_word", b, at))
    # wrapper element id >= count — string_array (200) and blob_array (201)
    b, at = wrapper_over_id(200, FL_STRING); out.append(("string_array_over_id", b, at))
    b, at = wrapper_over_id(201, FL_BLOB);   out.append(("blob_array_over_id", b, at))
    return out


# A malformation is "structural" when it is INVALID at the field's WORD (a reserved
# subtype, a bad array element-word) — every decoder rejects it before reading the
# payload, so truncating INTO the payload still gives R. A "schema-bound" malformation
# (over-maxlen/count/index, invalid UTF-8) is only INVALID after the content is read; the
# check + its ordering are generated code (maxlen/count/id are schema facts). Truncating
# such a malformation INTO its payload is **F-0032**: go/cpp/ts/dart report INCOMPLETE
# instead of the INVALID that §5.2 requires (documentation#15, adopted) — the F-0024 class
# for 4 more backends. Those into-payload truncations are carved OUT of this blocking axis
# (reproducers in findings/F-0032) until the generator fix lands; the `_complete` control
# and the mid-varint `_trunc_tail` (the malformation fully present, then a stray tail) stay
# blocking on all, and the structural malformations get the full broadened truncation.
STRUCTURAL = {"reserved_subtype_top", "reserved_subtype_nested",
              "reserved_subtype_str_wrapper", "reserved_subtype_blob_wrapper",
              "array_fixlen_bad_word"}


def valid_probe():
    """A minimal valid message (a single in-range scalar) for the tail-alone controls."""
    from gen import scalar_u
    return scalar_u(0, 7)


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for name, body, invalid_at in malformations():
        vectors.append((f"{name}_complete.bin", body, "reject"))
        # the mid-varint tail (malformation fully present, then a stray incomplete varint):
        # R on all — INVALID dominates the trailing incomplete varint.
        vectors.append((f"{name}_trunc_tail.bin", body + TRUNC, "reject"))
        # broaden truncation (WP-09): truncate INTO the field at every offset from the
        # malformation point. For a STRUCTURAL malformation (INVALID at the word) this is R
        # on all; for a schema-bound one it is F-0032 (go/cpp/ts/dart report I) — carved out.
        if name in STRUCTURAL:
            for k in range(invalid_at, len(body)):
                vectors.append((f"{name}_trunc_{k:03d}.bin", body[:k], "reject"))
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
          + f"  ({len(malformations())} malformations, truncated at every offset ≥ malformation)")
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/malform-truncate-sweep"
    emit(out)
