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

Slice 1 covers the top-level scalars (u8..i64) and the `nested` struct
(fp32/fp64/string/blob). The numeric arrays (id 100) and `string_array` (id 200) are
emitted empty for now — their element encoding (the `_StrSeq` index form, cf F-0008)
is the next slice. Writes raw wire (no length prefix) to corpus/structured/.

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

# The `arrays` (id 100) and `string_array` (id 200) sequences are always present in
# the canonical form even when empty; slice 1 emits them empty, verbatim.
EMPTY_ARRAYS = bytes.fromhex("a606560707")   # arrays{ nested{} }
EMPTY_STRARR = bytes.fromhex("c60c07")        # string_array{}

# top-level scalar fields: (id, signed?)
SCALARS = [("u8", 0, False), ("i8", 1, True), ("u16", 2, False), ("i16", 3, True),
           ("u32", 4, False), ("i32", 5, True), ("u64", 6, False), ("i64", 7, True)]

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
    out += EMPTY_ARRAYS + EMPTY_STRARR
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
    # blobs — only full-maxlen (4-byte) blobs here: a *sub*-maxlen blob is the
    # F-0009 divergence (the C object API pads a blob to maxlen / drops all-zero),
    # tracked as a finding rather than kept in this green cross-encode gate.
    out.append(("blob_full", {"blob": bytes([0x00, 0xFF, 0x7F, 0x80])}))
    out.append(("blob_full2", {"blob": bytes([0xDE, 0xAD, 0xBE, 0xEF])}))
    # a couple of dense combos
    out.append(("combo_scalars", {"u8": 200, "i8": -100, "u32": 12345, "i64": -99999}))
    out.append(("combo_nested", {"u32": 7, "f32": 2.5, "f64": -3.14159,
                                  "str": "Sofab ✓", "blob": bytes([0xde, 0xad, 0xbe, 0xef])}))
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
