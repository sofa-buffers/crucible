#!/usr/bin/env python3
"""Structured-corpus generator — the value-space source for Crucible's cross-encode
oracle (PLAN §6, DESIGN.md "Two corpus tracks").

The malformed track (the mutator + hand seeds) feeds *wire* bytes and mostly
exercises decoders on reject/incomplete paths. This generator instead emits
*valid, value-rich* `probe` messages, so the whole family's encoders and decoders
are cross-checked on the value space (float specials, unicode, boundary ints) that
wire-mutation almost never reaches.

Because the family is byte-canonical (every corelib's encoder emits identical wire
for a value — the arena reference-wire invariant), the cross-encode invariant
"encode in A, decode in B, compare" is realized by feeding these messages through
the existing round-trip + decode-agreement oracle (`scripts/run.sh`): all 12 drivers
must emit the same `A <hex>`. A divergence is a real encoder/decoder asymmetry.

This is a *reference* encoder for the full-scale `schema/probe.sofab.yaml`. It is
deliberately canonical (fields in id order, defaults omitted, the struct/array
sequences always emitted) so its output equals each corelib's re-encoding — but the
oracle only requires the 12 drivers to agree with *each other*, so a non-canonical
(but valid) encoding would work too.

Covers the top-level scalars (u8..i64), the `nested` struct (fp32/fp64/string/blob),
the numeric arrays (id 100: u8..i64 + nested fp32/fp64) and the `string_array`
(id 200, the index-keyed element sequence — F-0008's neighbourhood). Writes raw wire
(no length prefix) to corpus/structured/.

Usage: python3 engine/structured/gen.py [out_dir]   (default corpus/structured)
"""
import os
import struct
import sys

# --- wire primitives (CORELIB_PLAN §4) --------------------------------------
def varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint is unsigned")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def zigzag(n: int) -> int:
    return (n << 1) if n >= 0 else ((-n) << 1) - 1

# wire types (low 3 bits of a field header)
WT_U, WT_S, WT_FIX, WT_SEQ_BEG, WT_SEQ_END = 0, 1, 2, 6, 7
# fixlen subtypes (low 3 bits of the length-header)
FL_FP32, FL_FP64, FL_STRING, FL_BLOB = 0, 1, 2, 3

def hdr(field_id: int, wtype: int) -> bytes:
    return varint((field_id << 3) | wtype)

def scalar_u(field_id: int, value: int) -> bytes:
    return hdr(field_id, WT_U) + varint(value)

def scalar_s(field_id: int, value: int) -> bytes:
    return hdr(field_id, WT_S) + varint(zigzag(value))

def fixlen(field_id: int, subtype: int, payload: bytes) -> bytes:
    return hdr(field_id, WT_FIX) + varint((len(payload) << 3) | subtype) + payload

def fp32(field_id, v):  return fixlen(field_id, FL_FP32, struct.pack("<f", v))
def fp64(field_id, v):  return fixlen(field_id, FL_FP64, struct.pack("<d", v))
def fstr(field_id, s):  return fixlen(field_id, FL_STRING, s.encode("utf-8"))
def fblob(field_id, b): return fixlen(field_id, FL_BLOB, b)

# array wire types (low 3 bits of a field header)
WT_ARR_U, WT_ARR_S, WT_ARR_FIX = 3, 4, 5

def arr_u(field_id, vals):   # unsigned: header, count, count varints
    return hdr(field_id, WT_ARR_U) + varint(len(vals)) + b"".join(varint(v) for v in vals)

def arr_s(field_id, vals):   # signed: header, count, count zigzag varints
    return hdr(field_id, WT_ARR_S) + varint(len(vals)) + b"".join(varint(zigzag(v)) for v in vals)

def arr_fp(field_id, vals, fmt, subtype):  # fixlen array: header, count, fixlen-word, payload
    width = 4 if fmt == "<f" else 8
    word = varint((width << 3) | subtype)
    payload = b"".join(struct.pack(fmt, v) for v in vals)
    return hdr(field_id, WT_ARR_FIX) + varint(len(vals)) + word + payload

# top-level scalar fields: (id, signed?)
SCALARS = [("u8", 0, False), ("i8", 1, True), ("u16", 2, False), ("i16", 3, True),
           ("u32", 4, False), ("i32", 5, True), ("u64", 6, False), ("i64", 7, True)]

# numeric array fields inside the `arrays` struct (id 100): (msg-key, id, signed?)
NUM_ARRAYS = [("au8", 0, False), ("ai8", 1, True), ("au16", 2, False), ("ai16", 3, True),
              ("au32", 4, False), ("ai32", 5, True), ("au64", 6, False), ("ai64", 7, True)]

def encode(msg: dict) -> bytes:
    """msg: {scalar-name: int, 'f32'|'f64': float, 'str': str, 'blob': bytes}.
    Missing / default (0 / 0.0 / '' / b'') fields are omitted (sparse-canonical)."""
    out = bytearray()
    for name, fid, signed in SCALARS:
        v = msg.get(name, 0)
        if v:
            out += scalar_s(fid, v) if signed else scalar_u(fid, v)
    # nested struct (id 10) — always emitted; children omitted when default
    out += hdr(10, WT_SEQ_BEG)
    if msg.get("f32", 0.0) or _is_special(msg.get("f32")): out += fp32(0, msg["f32"])
    if msg.get("f64", 0.0) or _is_special(msg.get("f64")): out += fp64(1, msg["f64"])
    if msg.get("str", ""):   out += fstr(2, msg["str"])
    if msg.get("blob", b""): out += fblob(3, msg["blob"])
    out += bytes([WT_SEQ_END])
    # arrays struct (id 100) — always emitted; each array omitted when empty
    out += hdr(100, WT_SEQ_BEG)
    for name, fid, signed in NUM_ARRAYS:
        vals = msg.get(name)
        if vals:
            out += arr_s(fid, vals) if signed else arr_u(fid, vals)
    # arrays.nested (id 10) — always emitted; fp arrays inside
    out += hdr(10, WT_SEQ_BEG)
    if msg.get("afp32"): out += arr_fp(0, msg["afp32"], "<f", FL_FP32)
    if msg.get("afp64"): out += arr_fp(1, msg["afp64"], "<d", FL_FP64)
    out += bytes([WT_SEQ_END])   # close arrays.nested
    out += bytes([WT_SEQ_END])   # close arrays
    # string_array (id 200) — a sequence of index-keyed fixlen-string elements;
    # a default (empty) element is omitted (stored at its wire index on decode).
    out += hdr(200, WT_SEQ_BEG)
    for i, sv in enumerate(msg.get("strarr", [])):
        if sv:
            out += fstr(i, sv)
    out += bytes([WT_SEQ_END])
    return bytes(out)

def _is_special(v):
    return isinstance(v, float) and (v != v or v in (float("inf"), float("-inf")))

# --- value vectors: one interesting value per field, plus combos ------------
U = {"u8": 0xFF, "u16": 0xFFFF, "u32": 0xFFFFFFFF, "u64": (1 << 64) - 1}
SMAX = {"i8": 127, "i16": 32767, "i32": 2**31 - 1, "i64": 2**63 - 1}
SMIN = {"i8": -128, "i16": -32768, "i32": -2**31, "i64": -2**63}

def vectors():
    out = []  # (name, msg)
    out.append(("00_defaults", {}))
    # each unsigned scalar at 1 and at max
    for name, fid, signed in SCALARS:
        if signed:
            out.append((f"s_{name}_1", {name: 1}))
            out.append((f"s_{name}_max", {name: SMAX[name]}))
            out.append((f"s_{name}_min", {name: SMIN[name]}))
            out.append((f"s_{name}_neg1", {name: -1}))
        else:
            out.append((f"s_{name}_1", {name: 1}))
            out.append((f"s_{name}_max", {name: U[name]}))
    # floats: specials in both widths
    for w, mk in (("f32", "f32"), ("f64", "f64")):
        for tag, val in [("zero_neg", -0.0), ("one", 1.0), ("negone", -1.0),
                         ("inf", float("inf")), ("ninf", float("-inf")),
                         ("nan", float("nan")), ("big", 3.4e38 if w == "f32" else 1.7e308),
                         ("small", 1.2e-38 if w == "f32" else 2.2e-308)]:
            out.append((f"{w}_{tag}", {w: val}))
    # strings: empty (default → omitted), ascii, unicode, longer
    out.append(("str_ascii", {"str": "hello"}))
    out.append(("str_unicode", {"str": "äöü\U0001F600"}))
    out.append(("str_max32", {"str": "x" * 32}))
    out.append(("str_ctrl", {"str": "a\tb\nc"}))
    # blobs — full-maxlen and sub-maxlen. Sub-maxlen blobs were the F-0009
    # divergence (the C object API padded to maxlen / dropped all-zero); fixed in
    # sofabgen 0.17.1 (sized blob descriptor, generator#128), so they now round-trip
    # and belong in the green cross-encode gate.
    out.append(("blob_full", {"blob": bytes([0x00, 0xFF, 0x7F, 0x80])}))
    out.append(("blob_full2", {"blob": bytes([0xDE, 0xAD, 0xBE, 0xEF])}))
    out.append(("blob_short", {"blob": bytes([0x01])}))            # sub-maxlen (F-0009)
    out.append(("blob_zero", {"blob": bytes([0x00])}))            # sub-maxlen, all-zero (F-0009)
    out.append(("blob_short2", {"blob": bytes([0x00, 0x01])}))     # sub-maxlen, 2 bytes
    # --- slice 2: the array value space (arrays id 100, string_array id 200) ---
    # numeric arrays: full-count with 1s, and boundary values
    out.append(("arr_u8_ones", {"au8": [1, 2, 3, 4, 5]}))
    out.append(("arr_u8_max", {"au8": [U["u8"]] * 5}))
    out.append(("arr_i8_neg", {"ai8": [-1, -2, -3, -4, -5]}))
    out.append(("arr_i8_bounds", {"ai8": [SMIN["i8"], SMAX["i8"], 0, 1, -1]}))
    out.append(("arr_u32_seq", {"au32": [1, 2, 3, 4, 5]}))
    out.append(("arr_u64_max", {"au64": [U["u64"]] * 5}))
    out.append(("arr_i64_bounds", {"ai64": [SMIN["i64"], SMAX["i64"], 0, 1, -1]}))
    # NB: an *under*-count array (0 < wire count < schema count) re-encodes
    # divergently (F-0010: fixed-storage langs pad to capacity, dynamic langs keep
    # the wire count) — kept OUT of this green gate; reproducers in findings/F-0010.
    out.append(("arr_empty", {"au8": []}))          # count 0 (explicit empty) — agrees
    # fp arrays (arrays.nested): specials in both widths
    out.append(("arr_fp32_specials", {"afp32": [0.0, 1.0, -1.0, float("inf"), float("nan")]}))
    out.append(("arr_fp64_specials", {"afp64": [float("-inf"), 2.5, -3.5, 1e308, 0.0]}))
    # string_array (id 200): the index-keyed element sequence (F-0008's neighbourhood)
    out.append(("sa_full", {"strarr": ["one", "two", "three", "four", "five"]}))
    out.append(("sa_unicode", {"strarr": ["äöü", "日本語", "x", "y", "z"]}))
    out.append(("sa_partial", {"strarr": ["only-first"]}))          # element at index 0
    out.append(("sa_sparse", {"strarr": ["a", "", "c", "", "e"]}))  # empty middle elements omitted
    out.append(("sa_last_index", {"strarr": ["", "", "", "", "idx4"]}))  # only the max valid index (4)
    out.append(("sa_maxlen", {"strarr": ["Z" * 64]}))              # maxlen-64 string element
    # dense combos across arrays + scalars + nested
    out.append(("combo_scalars", {"u8": 200, "i8": -100, "u32": 12345, "i64": -99999}))
    out.append(("combo_nested", {"u32": 7, "f32": 2.5, "f64": -3.14159,
                                  "str": "Sofab ✓", "blob": bytes([0xde, 0xad, 0xbe, 0xef])}))
    out.append(("combo_arrays", {"au8": [1, 2, 3, 4, 5], "ai32": [-1, 2, -3, 4, -5],
                                  "afp64": [1.5, -2.5, 0.0, float("inf"), float("nan")],
                                  "strarr": ["alpha", "beta", "gamma", "delta", "epsilon"]}))
    return out

def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "corpus/structured"
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for i, (name, msg) in enumerate(vectors()):
        wire = encode(msg)
        with open(os.path.join(out_dir, f"{i:03d}_{name}.bin"), "wb") as fh:
            fh.write(wire)
        n += 1
    sys.stderr.write(f"[structured] wrote {n} valid messages to {out_dir}\n")

if __name__ == "__main__":
    main()
