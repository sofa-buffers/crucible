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
the existing round-trip + decode-agreement oracle (`scripts/run.sh`): all drivers
must emit the same `A <hex>`. A divergence is a real encoder/decoder asymmetry.

This is a *reference* encoder for the full-scale `schema/probe.sofab.yaml`. It is
deliberately canonical (fields in id order, defaults omitted — including a whole
sequence whose value equals its declared default, per the uniform ≠-default rule of
MESSAGE_SPEC §2: an all-default struct/wrapper is *omitted*, not framed empty) so
its output equals each corelib's re-encoding — but the oracle only requires the 13
drivers to agree with *each other*, so a non-canonical (but valid) encoding would
work too. The consequence pinned by `000_00_defaults.bin`: the all-default message
is the **empty byte string** (§2).

Covers the top-level scalars (u8..i64), the `nested` struct (fp32/fp64/string/blob),
the numeric arrays (id 100: u8..i64 + nested fp32/fp64), the `string_array` (id 200,
the index-keyed element sequence — F-0008's neighbourhood) and the `blob_array`
(id 201, its blob analogue — F-0013's _BlobSeq path) and the `struct_array` (id 202,
the array-of-struct whose elements are themselves sequences). Writes raw wire (no
length prefix) to corpus/structured/.

Array lengths follow documentation#31: `count` is a **capacity**, so the wire count
is the array's length — nothing is trimmed on encode and nothing is filled on decode,
and in a wrapper the last element is always written even when it equals its default.

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

# fp values may be a Python float (struct-packed) OR raw bytes — the latter lets a
# vector pin an EXACT bit pattern (subnormal, sNaN, NaN payload, -NaN) that a
# float round-trip through Python might canonicalize (WP-06).
def fp32(field_id, v):
    return fixlen(field_id, FL_FP32, v if isinstance(v, bytes) else struct.pack("<f", v))
def fp64(field_id, v):
    return fixlen(field_id, FL_FP64, v if isinstance(v, bytes) else struct.pack("<d", v))

def f32b(bits):  return struct.pack("<I", bits)   # an fp32 by its 32-bit pattern
def f64b(bits):  return struct.pack("<Q", bits)   # an fp64 by its 64-bit pattern
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
    # An element may be given as raw bytes to pin an EXACT bit pattern that a round
    # trip through a Python float would canonicalize — the same escape the scalar
    # fp32()/fp64() take. CORELIB_PLAN §6.5 requires bit-exactness at the array
    # element position too, not only at a scalar fp32.
    payload = b"".join(v if isinstance(v, bytes) else struct.pack(fmt, v) for v in vals)
    return hdr(field_id, WT_ARR_FIX) + varint(len(vals)) + word + payload

# top-level scalar fields: (id, signed?)
SCALARS = [("u8", 0, False), ("i8", 1, True), ("u16", 2, False), ("i16", 3, True),
           ("u32", 4, False), ("i32", 5, True), ("u64", 6, False), ("i64", 7, True)]

# numeric array fields inside the `arrays` struct (id 100): (msg-key, id, signed?)
NUM_ARRAYS = [("au8", 0, False), ("ai8", 1, True), ("au16", 2, False), ("ai16", 3, True),
              ("au32", 4, False), ("ai32", 5, True), ("au64", 6, False), ("ai64", 7, True)]

def _leaf_elements(items, enc, empty):
    """Wrapper-array body for leaf elements under the §2 sparse rule: interior
    defaults omitted (id gap), the last element always written."""
    out = bytearray()
    for i, v in enumerate(items):
        if v != empty or i == len(items) - 1:
            out += enc(i, v)
    return bytes(out)


def _framed(fid, body):
    """Frame body as sequence fid iff it is non-empty; an all-default sequence is
    omitted outright (MESSAGE_SPEC §2 uniform ≠-default rule — the frame carries no
    information, absence reconstructs the same value)."""
    return hdr(fid, WT_SEQ_BEG) + body + bytes([WT_SEQ_END]) if body else b""


def encode(msg: dict) -> bytes:
    """msg: {scalar-name: int, 'f32'|'f64': float, 'str': str, 'blob': bytes}.
    Missing / default (0 / 0.0 / '' / b'') fields are omitted (sparse-canonical);
    per §2 that includes each sequence as a whole, so the all-default message is
    the empty byte string."""
    out = bytearray()
    for name, fid, signed in SCALARS:
        v = msg.get(name, 0)
        if v:
            out += scalar_s(fid, v) if signed else scalar_u(fid, v)
    # nested struct (id 10) — children omitted when default; the whole frame
    # omitted when all of them are (§2)
    nested = bytearray()
    if msg.get("f32", 0.0) or _is_special(msg.get("f32")): nested += fp32(0, msg["f32"])
    if msg.get("f64", 0.0) or _is_special(msg.get("f64")): nested += fp64(1, msg["f64"])
    if msg.get("str", ""):   nested += fstr(2, msg["str"])
    if msg.get("blob", b""): nested += fblob(3, msg["blob"])
    out += _framed(10, bytes(nested))
    # arrays struct (id 100) — each array omitted when empty, arrays.nested (id 10)
    # omitted when both fp arrays are, the whole frame omitted when everything is
    arrays = bytearray()
    for name, fid, signed in NUM_ARRAYS:
        vals = msg.get(name)
        if vals:
            arrays += arr_s(fid, vals) if signed else arr_u(fid, vals)
    anested = bytearray()
    if msg.get("afp32"): anested += arr_fp(0, msg["afp32"], "<f", FL_FP32)
    if msg.get("afp64"): anested += arr_fp(1, msg["afp64"], "<d", FL_FP64)
    arrays += _framed(10, bytes(anested))
    out += _framed(100, bytes(arrays))
    # string_array (id 200) / blob_array (id 201) — index-keyed leaf elements. §2
    # sparse rule: an *interior* default element is omitted (an id gap the decoder
    # restores), the **last** element is ALWAYS written, because the length is
    # *highest present id + 1* and eliding it would shorten the array. An empty
    # array omits the wrapper itself (its declared default is the empty collection).
    out += _framed(200, _leaf_elements(msg.get("strarr", []), fstr, ""))
    out += _framed(201, _leaf_elements(msg.get("blobarr", []), fblob, b""))
    # struct_array (id 202, WP-05) — the wrapper whose elements are struct sequences
    # {k: u32 (id 0), v: string (id 1)}. The SAME rule as the leaf wrappers above
    # (§2, one rule for both element kinds): an interior all-default element is a
    # gap, the last element is always written — as an EMPTY FRAME when it is itself
    # all-default — and an empty array omits the wrapper.
    selems = msg.get("structarr", [])
    sw = bytearray()
    for i, e in enumerate(selems):
        body = b""
        if e.get("k", 0): body += scalar_u(0, e["k"])
        if e.get("v", ""): body += fstr(1, e["v"])
        if body or i == len(selems) - 1:          # interior all-default -> gap
            sw += hdr(i, WT_SEQ_BEG) + body + bytes([WT_SEQ_END])
    out += _framed(202, bytes(sw))
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
    # WP-06: exact bit-pattern fp specials (raw bytes — no Python float
    # canonicalization). Subnormals, the four NaN variants, and an explicit +0.0.
    # The materialized oracle compares floats as raw bits (oracle/materialized.md), so
    # a NaN payload a driver drops (py/ts materialize fp32 through a double —
    # canonical.md:107-109) is directly visible here.
    out.append(("f32_subnorm_min",  {"f32": f32b(0x00000001)}))          # min +subnormal
    out.append(("f32_subnorm_max",  {"f32": f32b(0x007FFFFF)}))          # max subnormal
    # CORELIB_PLAN §6.5 requires bit-exactness at every fp32 position. The scalar sNaN was
    # held out while F-0049 was open — dart's generated raw-bits companion was library-private,
    # so no consumer could read it. Fixed in generator#275 ("the fp32 raw-bits companion must be
    # consumer-visible"); the walker reads it since 2026-08-02, and materialize.sh is green on
    # all drivers. Back in the gate, where a regression now fails CI.
    out.append(("f32_snan",         {"f32": f32b(0x7F800001)}))          # signaling NaN
    out.append(("f32_qnan_payload", {"f32": f32b(0x7FC00001)}))          # quiet NaN, nonzero payload
    out.append(("f32_nan_neg",      {"f32": f32b(0xFFC00000)}))          # negative NaN
    out.append(("f32_zero_pos",     {"f32": f32b(0x00000000)}))          # explicit +0.0 (canonicalizes to omitted)
    out.append(("f64_subnorm_min",  {"f64": f64b(0x0000000000000001)}))
    out.append(("f64_subnorm_max",  {"f64": f64b(0x000FFFFFFFFFFFFF)}))
    out.append(("f64_snan",         {"f64": f64b(0x7FF0000000000001)}))
    out.append(("f64_qnan_payload", {"f64": f64b(0x7FF8000000000001)}))
    out.append(("f64_nan_neg",      {"f64": f64b(0xFFF8000000000000)}))
    out.append(("f64_zero_pos",     {"f64": f64b(0x0000000000000000)}))
    # WP-06: unsigned mid values (had only 1 and type-max; 0 == default == 00_defaults).
    for name, fid, signed in SCALARS:
        if not signed:
            out.append((f"s_{name}_mid", {name: (U[name] // 2) + 1}))
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
    # --- `count` is a CAPACITY (documentation#31): the wire count IS the length ---
    # An array shorter than its schema `count` is simply a shorter array — no longer
    # the F-0010 "under-count" divergence, which existed only under the retired
    # fixed-length reading. These pin that a trailing default element is a VALUE, not
    # padding: the pairs must round-trip to DIFFERENT bytes.
    out.append(("cap_u8_short", {"au8": [1, 2, 3]}))                 # 3 elements, M=3
    out.append(("cap_u8_trailing_zeros", {"au8": [1, 2, 3, 0, 0]}))  # 5 elements, M=5
    out.append(("cap_i8_trailing_zero", {"ai8": [-1, 0]}))           # 2 elements, M=2
    out.append(("cap_fp32_trailing_zero", {"afp32": [1.0, 0.0]}))    # 2 elements, M=2
    out.append(("cap_u8_one", {"au8": [7]}))                         # 1 element
    # the wrapper side of the same rule: the LAST element is always written, so these
    # three are three distinct values (§2 last-element rule)
    out.append(("cap_sa_last_default", {"strarr": ["a", ""]}))       # 2 elements
    out.append(("cap_sa_one", {"strarr": ["a"]}))                    # 1 element
    out.append(("cap_sa_all_default", {"strarr": ["", ""]}))         # 2 elements, id 1 only
    out.append(("cap_ba_last_default", {"blobarr": [b"\x01", b""]}))  # 2 elements
    # NB: the former "arr_empty" ({"au8": []}) vector is retired — under the §2
    # uniform ≠-default rule an empty array field is *omitted*, so its wire was
    # byte-identical to 00_defaults.
    # fp arrays (arrays.nested): specials in both widths
    out.append(("arr_fp32_specials", {"afp32": [0.0, 1.0, -1.0, float("inf"), float("nan")]}))
    # CORELIB_PLAN §6.5 requires bit-exactness at **every** fp32 position — "a scalar
    # fp32 (§4.6) **and** each element of an fp32 array (§4.8)". Only the scalar
    # position was covered; a defect confined to the array path would have been
    # invisible. Raw bytes, so Python cannot canonicalize the payloads.
    out.append(("arr_fp32_nan_bits", {"afp32": [f32b(0x7F800001),   # signaling NaN
                                                f32b(0x7FC00001),   # quiet NaN, payload
                                                f32b(0xFFC00000),   # negative NaN
                                                f32b(0x00000001),   # min subnormal
                                                f32b(0x3F800000)]}))  # 1.0, plain control
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
                                  "strarr": ["alpha", "beta", "gamma", "delta", "epsilon"],
                                  "blobarr": [b"\x00", b"\x11\x22", b"\xde\xad\xbe\xef", b"\xff", b"\x5a"]}))
    # blob_array (id 201): the index-keyed element sequence — blob analogue of 200.
    # Appended last so existing indices don't renumber. F-0013 hardened the string
    # path but `probe` had no blob array; these exercise the _BlobSeq encode/decode
    # value space (binary bytes, sub-/full-maxlen elements).
    out.append(("ba_full", {"blobarr": [b"\x01", b"\x02\x03", b"\xde\xad", b"\xff", b"\x00\x10"]}))
    out.append(("ba_partial", {"blobarr": [b"\xaa\xbb"]}))               # element at index 0
    out.append(("ba_sparse", {"blobarr": [b"\x01", b"", b"\x03", b"", b"\x05"]}))  # empty middles omitted
    out.append(("ba_last_index", {"blobarr": [b"", b"", b"", b"", b"\x04"]}))  # only max valid index (4)
    out.append(("ba_maxlen", {"blobarr": [b"\x5a" * 64]}))              # maxlen-64 blob element
    out.append(("ba_binary", {"blobarr": [bytes(range(8)), b"\x00\x00", b"\xff\xfe\xfd"]}))  # raw binary
    # struct_array (id 202, WP-05): the sequence-element value space — where the §2
    # empty-frame ELEMENT rules live (an interior all-default element stays framed;
    # the trailing run elides; the all-default array omits the wrapper).
    out.append(("sw_full", {"structarr": [{"k": 1, "v": "one"}, {"k": 2, "v": "two"},
                                          {"k": 3, "v": "three"}, {"k": 4, "v": "four"},
                                          {"k": 5, "v": "five"}]}))
    out.append(("sw_partial", {"structarr": [{"k": 7, "v": "seven"}]}))  # element 0 only
    out.append(("sw_k_only", {"structarr": [{"k": 42}]}))                # v at default inside
    out.append(("sw_v_only", {"structarr": [{"v": "val"}]}))             # k at default inside
    # an interior ALL-DEFAULT element: encodes as an empty frame between two real
    # ones — present, counted, MUST NOT be dropped (§2 element rule / §5.1 length)
    out.append(("sw_hole_mid", {"structarr": [{"k": 1, "v": "a"}, {}, {"k": 3, "v": "c"}]}))
    # trailing all-default elements: elided from the wire (fixed count, §5.1) — the
    # value round-trips against a default-initialised destination
    out.append(("sw_trailing_default", {"structarr": [{"k": 9, "v": "last-real"}, {}, {}]}))
    out.append(("sw_maxlen_v", {"structarr": [{"k": 0xFFFFFFFF, "v": "x" * 16}]}))  # boundary k + maxlen v
    out.append(("sw_unicode", {"structarr": [{"k": 1, "v": "äöü✓"}]}))
    return out

# --- union message (schema/probe-union.sofab.yaml) — WP-02 ------------------
# The union probe: tag (id 0, u32), choice (id 1, union), trailer (id 2, u8). The
# union `choice` is a sequence carrying at most one member; member ids select the
# option: as_u16=0 (WT_U), as_i32=1 (WT_S), as_text=2 (fixlen string maxlen16),
# as_blob=3 (fixlen blob maxlen8). A default union (default_id carrying that
# option's default) is canonically OMITTED (§2/§4.2 — absence yields the same
# value); a member at its own default reduces to the same omission (the §4.2
# identity loss: the option id cannot survive a round-trip).
def encode_union(msg: dict) -> bytes:
    """msg: {'tag': int, 'member': (kind, value)|None, 'trailer': int}. kind in
    {'u16','i32','text','blob'}; member=None or a member at its default → the union
    is omitted (§2). tag/trailer are omitted when default (sparse-canonical)."""
    out = bytearray()
    if msg.get("tag"):
        out += scalar_u(0, msg["tag"])
    choice = bytearray()
    m = msg.get("member")
    if m is not None:
        kind, v = m
        if kind == "u16":
            if v: choice += scalar_u(0, v)
        elif kind == "i32":
            if v: choice += scalar_s(1, v)
        elif kind == "text":
            if v: choice += fstr(2, v)
        elif kind == "blob":
            if v: choice += fblob(3, v)
        else: raise ValueError(f"unknown union member {kind!r}")
    if choice:
        out += hdr(1, WT_SEQ_BEG) + choice + bytes([WT_SEQ_END])
    if msg.get("trailer"):
        out += scalar_u(2, msg["trailer"])
    return bytes(out)


def union_vectors():
    """Value-rich union vectors: each member at boundary values, the default_id
    (empty) case, and tag+member+trailer combos. All valid → all drivers must agree on the
    re-encoded hex (the cross-encode invariant)."""
    out = []
    out.append(("00_default", {}))                        # default union → omitted (§2), 0 bytes
    # as_u16 (u16): 1 / max. NB "u16_zero" and "text_empty" are retired: a member at
    # its own default reduces to the omitted union (§2/§4.2 identity loss), making
    # their wire byte-identical to 00_default; their explicit non-canonical wire
    # forms are swept by sweep_empty_frame.py's union pass instead.
    for tag, v in (("one", 1), ("max", 0xFFFF)):
        out.append((f"u16_{tag}", {"member": ("u16", v)}))
    # as_i32 (i32): min / -1 / 1 / max
    for tag, v in (("min", -2**31), ("neg1", -1), ("one", 1), ("max", 2**31 - 1)):
        out.append((f"i32_{tag}", {"member": ("i32", v)}))
    # as_text (string maxlen16): ascii / unicode / exactly-maxlen16 ("" is retired —
    # see the NB above)
    out.append(("text_ascii", {"member": ("text", "hello")}))
    out.append(("text_unicode", {"member": ("text", "äöü\U0001F600")}))
    out.append(("text_max16", {"member": ("text", "x" * 16)}))
    # as_blob (blob maxlen8): 1-byte / exactly-maxlen8 / binary
    out.append(("blob_one", {"member": ("blob", b"\x5a")}))
    out.append(("blob_max8", {"member": ("blob", bytes(range(8)))}))
    out.append(("blob_bin", {"member": ("blob", b"\x00\xff\x7f\x80")}))
    # tag + member + trailer all set (combos)
    out.append(("combo_tag_i32_trailer", {"tag": 5, "member": ("i32", 42), "trailer": 12}))
    out.append(("combo_tag_text", {"tag": 0xFFFFFFFF, "member": ("text", "Sofab ✓")}))
    out.append(("combo_tag_trailer_default", {"tag": 7, "member": None, "trailer": 200}))
    return out


def _reset_dir(out_dir):
    """Make out_dir and clear any stale *.bin — vector indices shift when the set
    changes, so leftover files from an older set would pollute the corpus (and the
    committed gate CI replays with REGEN=0)."""
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        if f.endswith(".bin"):
            os.remove(os.path.join(out_dir, f))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--union":
        out_dir = sys.argv[2] if len(sys.argv) > 2 else "corpus/structured-union"
        _reset_dir(out_dir)
        n = 0
        for i, (name, msg) in enumerate(union_vectors()):
            with open(os.path.join(out_dir, f"{i:03d}_{name}.bin"), "wb") as fh:
                fh.write(encode_union(msg))
            n += 1
        sys.stderr.write(f"[structured-union] wrote {n} valid union messages to {out_dir}\n")
        return
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "corpus/structured"
    _reset_dir(out_dir)
    n = 0
    for i, (name, msg) in enumerate(vectors()):
        wire = encode(msg)
        with open(os.path.join(out_dir, f"{i:03d}_{name}.bin"), "wb") as fh:
            fh.write(wire)
        n += 1
    sys.stderr.write(f"[structured] wrote {n} valid messages to {out_dir}\n")

if __name__ == "__main__":
    main()
