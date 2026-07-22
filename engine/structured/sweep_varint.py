#!/usr/bin/env python3
"""Non-minimal varint sweep (MESSAGE_SPEC §2 canonicality / CORELIB_PLAN §4.1) — a
report-only sweep axis for a divergence class no other suite reaches.

A varint encodes 7 bits per byte, LSB first, high bit = continuation (CORELIB_PLAN
§4.1). A value has a **minimal** encoding (no redundant trailing continuation) but the
wire also admits **non-minimal** forms: extra `0x80` continuation bytes that add only
zero high bits, e.g. value 5 = `05` (minimal) = `85 00` (one redundant byte) = `85 80
00` (two) — all decode to 5. `gen.varint` only ever emits minimal encodings, so no
existing corpus contains a non-minimal-but-in-range varint. F-0016 covered only the
**>64-bit overflow** case (`corpus/regression/F0016_*`); whether all 13 decoders agree
on a non-minimal varint that still fits 64 bits — accept-and-normalize, or reject — is
untested, and it is exactly the class where streaming decoders silently differ.

**Spec status: SILENT.** CORELIB_PLAN §4.1 guards only "overlong / overflowing …
more bytes than a 64-bit value can hold" (the overflow case); MESSAGE_SPEC §2 makes
the *encoder* canonical but states no *decoder* rule for a non-minimal-but-≤64-bit
varint. §3 (:193) shows the family's pattern — a decoder *accepts* a non-canonical
form and re-encodes it canonically — which suggests non-minimal varints should be
accepted-and-normalized, but no clause says so. Per Crucible ground rule 6 this axis
is therefore **agreement-only** (the vectors carry `expect="agree"`: the runner checks
only that all 13 agree, not accept-vs-reject conformance) and the hole is filed
upstream against `documentation` (`docs/spec-proposals.md`) — the F-0015 arc. If all 13
accept, the round-trip oracle *also* pins the normalization: an accepted non-minimal
input must re-encode to the single canonical form (§2:73-76) on all 13, so a driver
that normalizes differently shows up as an accept-value payload split for free.

A non-minimal varint is placed at each distinct **varint role** on the wire — a
codegen/corelib may guard one role and not another:
  * field-id header varint             `(id << 3) | wtype`
  * fixlen length word                 `(len << 3) | subtype`
  * array element-count word
  * array element value
  * a varint inside a SKIPPED (unknown-id) field  (the skip's own varint reader)

Each role also carries a **minimal control** (must accept, all agree) and a
**max-padding boundary** (the most padding that still decodes ≤64 bits — 10 bytes),
sitting next to a single **>64-bit overflow** contrast (the F-0016 class, must reject).

Wire primitives come from `gen.py` (the one reference encoder); the non-minimal forms
are hand-built here and `gen.varint` is deliberately left untouched (it is the
canonical reference encoder).

Usage: python3 engine/structured/sweep_varint.py [out_dir]   (default corpus/varint-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    varint, WT_U, WT_FIX, WT_ARR_U, WT_SEQ_BEG, WT_SEQ_END, FL_STRING,
    hdr, scalar_u,
)


def nonminimal_varint(value: int, total_bytes: int) -> bytes:
    """`value` encoded in exactly `total_bytes` bytes (>= its minimal length): the
    first total_bytes-1 carry a group with the continuation bit set, the last carries
    the remaining (possibly all-zero) high group with the bit clear. Decodes to
    `value`; non-minimal iff total_bytes exceeds the minimal length."""
    out = bytearray()
    v = value
    for i in range(total_bytes):
        byte = v & 0x7F
        v >>= 7
        if i < total_bytes - 1:
            byte |= 0x80
        out.append(byte)
    if v != 0:
        raise ValueError(f"{value} does not fit in {total_bytes} varint bytes")
    return bytes(out)


def _minimal_len(value: int) -> int:
    n = 1
    v = value >> 7
    while v:
        n += 1
        v >>= 7
    return n


# --- framing helpers (a bare field at root, or one inside a sequence path) -----
def _at_root(field: bytes) -> bytes:
    return field

def _in_seq(path, field: bytes) -> bytes:
    return b"".join(hdr(p, WT_SEQ_BEG) for p in path) + field + bytes([WT_SEQ_END]) * len(path)


# A non-minimal varint that still fits 64 bits maxes out at 10 bytes (⌈64/7⌉);
# an 11-byte continuation is unambiguously >64-bit — the F-0016 overflow class.
MAX64_BYTES = 10


def emit(out_dir):
    """[(name, bytes, expect)]. Non-minimal vectors are `expect="agree"` (agreement
    only — spec is silent); minimal controls are `accept`; the overflow contrast is
    `reject` (>64-bit is spec-defined malformed, CORELIB_PLAN §4.1 / F-0016)."""
    os.makedirs(out_dir, exist_ok=True)
    vectors = []

    def add(name, data, expect):
        vectors.append((f"{name}.bin", data, expect))

    # padding widths to sweep per role: +1, +3 bytes, and max-that-fits-64-bit
    def pads(value):
        m = _minimal_len(value)
        widths = [m + 1, m + 3, MAX64_BYTES]
        # dedup / keep only strictly non-minimal and representable
        return [w for w in sorted(set(widths)) if w > m and w <= MAX64_BYTES]

    # ---- role 1: field-id header varint --------------------------------------
    # root u16 field id2, wtype WT_U -> header value (2<<3)|0 = 16; value = 5 (minimal)
    hdr_val = (2 << 3) | WT_U
    add("role_header_minimal_ctl", varint(hdr_val) + varint(5), "accept")
    for w in pads(hdr_val):
        add(f"role_header_nonmin_{w}b", nonminimal_varint(hdr_val, w) + varint(5), "agree")

    # ---- role 2: fixlen length word ------------------------------------------
    # nested struct (id 10) -> str field (id 2): fixlen word (len<<3)|FL_STRING
    word = (1 << 3) | FL_STRING            # len 1, string "A"
    fix_min = hdr(2, WT_FIX) + varint(word) + b"A"
    add("role_fixword_minimal_ctl", _in_seq((10,), fix_min), "accept")
    for w in pads(word):
        fix_nm = hdr(2, WT_FIX) + nonminimal_varint(word, w) + b"A"
        add(f"role_fixword_nonmin_{w}b", _in_seq((10,), fix_nm), "agree")

    # ---- role 3: array element-count word ------------------------------------
    # arrays struct (id 100) -> au8 (id 0), WT_ARR_U: count=1, one element=5
    arr_min = hdr(0, WT_ARR_U) + varint(1) + varint(5)
    add("role_count_minimal_ctl", _in_seq((100,), arr_min), "accept")
    for w in pads(1):
        arr_nm = hdr(0, WT_ARR_U) + nonminimal_varint(1, w) + varint(5)
        add(f"role_count_nonmin_{w}b", _in_seq((100,), arr_nm), "agree")

    # ---- role 4: array element value -----------------------------------------
    for w in pads(5):
        elem_nm = hdr(0, WT_ARR_U) + varint(1) + nonminimal_varint(5, w)
        add(f"role_elem_nonmin_{w}b", _in_seq((100,), elem_nm), "agree")

    # ---- role 5: a varint inside a SKIPPED (unknown-id) field ----------------
    # unknown root id 50, WT_U -> the whole field is skipped (§7.3); its value varint
    # is non-minimal. Does the skip's varint reader tolerate the redundant bytes?
    unk_hdr = (50 << 3) | WT_U
    add("role_skip_minimal_ctl", varint(unk_hdr) + varint(5), "accept")
    for w in pads(5):
        add(f"role_skip_nonmin_{w}b", varint(unk_hdr) + nonminimal_varint(5, w), "agree")
    # the skipped-field HEADER itself non-minimal
    for w in pads(unk_hdr):
        add(f"role_skiphdr_nonmin_{w}b", nonminimal_varint(unk_hdr, w) + varint(5), "agree")

    # ---- boundary / overflow contrast (F-0016 class) -------------------------
    # max-padding value 1 (10 bytes, still ≤64 bit) already covered per role via
    # MAX64_BYTES; the >64-bit overflow is the reject contrast: an 11-byte continuation
    # at a scalar value (value would be 1<<70 — beyond 64 bits).
    overflow = varint((2 << 3) | WT_U) + (bytes([0x80]) * 10 + bytes([0x01]))
    add("contrast_overflow_11byte_value", overflow, "reject")

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/varint-sweep"
    emit(out)
