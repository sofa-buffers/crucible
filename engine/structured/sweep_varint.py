#!/usr/bin/env python3
"""Non-minimal varint sweep (MESSAGE_SPEC §2 canonicality / CORELIB_PLAN §4.1) — a
sweep axis for a divergence class no other suite reaches.

A varint encodes 7 bits per byte, LSB first, high bit = continuation (CORELIB_PLAN
§4.1). A value has a **minimal** encoding (no redundant trailing continuation) but the
wire also admits **non-minimal** forms: extra `0x80` continuation bytes that add only
zero high bits, e.g. value 5 = `05` (minimal) = `85 00` (one redundant byte) = `85 80
00` (two) — all decode to 5. `gen.varint` only ever emits minimal encodings, so no
existing corpus contains a non-minimal-but-in-range varint. F-0016 covered only the
**>64-bit overflow** case (`corpus/regression/F0016_*`); whether all 13 decoders agree
on a non-minimal varint that still fits 64 bits — accept-and-normalize, or reject — is
untested, and it is exactly the class where streaming decoders silently differ.

**Spec status: SPECIFIED** (was SILENT; the hole filed as documentation#24 was closed
by documentation#25, commit `c77f72a`, "varint minimality on encode,
accept-and-normalize on decode"). CORELIB_PLAN §4.1 now states it normatively:

  * an encoder **MUST** emit the minimal form — the byte-level face of the single
    canonical encoding (MESSAGE_SPEC §2);
  * a decoder **MUST accept** a non-minimal varint that stays within the 64-bit
    bound, decode it to the value it denotes, and re-emit the minimal form. A
    non-minimal encoding is explicitly **not** `INVALID` — it is normalized away,
    exactly as a non-canonical trailing-default array run is (MESSAGE_SPEC §3);
  * the rule applies **wherever a varint appears**: field headers, `fixlen_word`s,
    array counts, element values, and inside skipped fields — which is precisely the
    role sweep below.

So the vectors that used to be agreement-only (`expect="agree"`, ground rule 6) now
carry `expect="accept"` and the runner asserts accept-vs-reject conformance on them:
all 13 agreeing on *reject* would have been green before and is a finding now.

The round-trip oracle pins the *normalization* on top of that for free: an accepted
non-minimal input must re-encode to the single canonical form (MESSAGE_SPEC §2), so a
driver that accepts but normalizes differently shows up as an accept-value payload
split without needing its own assertion.

**The 64-bit bound is also sharper than "more than 10 bytes".** §4.1 defines it on the
*encoding*, not the decoded value: an encoding is `INVALID` iff it is **longer than 10
bytes**, *or* any payload bit would land at position **≥ 64** (a tenth byte with
payload above `0x01`). Both halves are swept as reject contrasts below, including the
case the old axis missed — an 11-byte encoding whose surplus bytes are all **zero**,
which denotes a perfectly representable value and is `INVALID` anyway.

A non-minimal varint is placed at each distinct **varint role** on the wire — a
codegen/corelib may guard one role and not another:
  * field-id header varint             `(id << 3) | wtype`
  * fixlen length word                 `(len << 3) | subtype`
  * array element-count word
  * array element value
  * a varint inside a SKIPPED (unknown-id) field  (the skip's own varint reader)

Each role also carries a **minimal control** (must accept, all agree) and a
**max-padding boundary** (the most padding that still decodes ≤64 bits — 10 bytes),
sitting next to **three out-of-range contrasts** (the F-0016 class, must reject): an
11-byte overflow, an 11-byte encoding of a representable value, and a 10-byte encoding
whose tenth byte pushes payload bits to position ≥ 64.

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
    """[(name, bytes, expect)]. Non-minimal-but-in-range vectors are `expect="accept"`
    (CORELIB_PLAN §4.1 mandates accept-and-normalize); minimal controls are `accept`;
    the out-of-range contrasts are `reject` (both halves of §4.1's 64-bit bound)."""
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
        add(f"role_header_nonmin_{w}b", nonminimal_varint(hdr_val, w) + varint(5), "accept")

    # ---- role 2: fixlen length word ------------------------------------------
    # nested struct (id 10) -> str field (id 2): fixlen word (len<<3)|FL_STRING
    word = (1 << 3) | FL_STRING            # len 1, string "A"
    fix_min = hdr(2, WT_FIX) + varint(word) + b"A"
    add("role_fixword_minimal_ctl", _in_seq((10,), fix_min), "accept")
    for w in pads(word):
        fix_nm = hdr(2, WT_FIX) + nonminimal_varint(word, w) + b"A"
        add(f"role_fixword_nonmin_{w}b", _in_seq((10,), fix_nm), "accept")

    # ---- role 3: array element-count word ------------------------------------
    # arrays struct (id 100) -> au8 (id 0), WT_ARR_U: count=1, one element=5
    arr_min = hdr(0, WT_ARR_U) + varint(1) + varint(5)
    add("role_count_minimal_ctl", _in_seq((100,), arr_min), "accept")
    for w in pads(1):
        arr_nm = hdr(0, WT_ARR_U) + nonminimal_varint(1, w) + varint(5)
        add(f"role_count_nonmin_{w}b", _in_seq((100,), arr_nm), "accept")

    # ---- role 4: array element value -----------------------------------------
    for w in pads(5):
        elem_nm = hdr(0, WT_ARR_U) + varint(1) + nonminimal_varint(5, w)
        add(f"role_elem_nonmin_{w}b", _in_seq((100,), elem_nm), "accept")

    # ---- role 5: a varint inside a SKIPPED (unknown-id) field ----------------
    # unknown root id 50, WT_U -> the whole field is skipped (§7.3); its value varint
    # is non-minimal. Does the skip's varint reader tolerate the redundant bytes?
    unk_hdr = (50 << 3) | WT_U
    add("role_skip_minimal_ctl", varint(unk_hdr) + varint(5), "accept")
    for w in pads(5):
        add(f"role_skip_nonmin_{w}b", varint(unk_hdr) + nonminimal_varint(5, w), "accept")
    # the skipped-field HEADER itself non-minimal
    for w in pads(unk_hdr):
        add(f"role_skiphdr_nonmin_{w}b", nonminimal_varint(unk_hdr, w) + varint(5), "accept")

    # ---- boundary / out-of-range contrasts (F-0016 class) --------------------
    # CORELIB_PLAN §4.1 defines the bound on the ENCODING, in two independent halves,
    # and each gets its own contrast. Max-padding within range (10 bytes, ≤64 bit) is
    # already covered per role via MAX64_BYTES and must ACCEPT.
    scalar_hdr = varint((2 << 3) | WT_U)

    # (a) "longer than 10 bytes" — an 11-byte continuation whose value overflows.
    add("contrast_overflow_11byte_value",
        scalar_hdr + (bytes([0x80]) * 10 + bytes([0x01])), "reject")

    # (b) "longer than 10 bytes" with a REPRESENTABLE value: 5 padded to 11 bytes, so
    #     every surplus bit is zero. §4.1 is explicit that this is INVALID anyway —
    #     the test is on the encoding, not the value it denotes. The old axis capped
    #     padding at MAX64_BYTES and so never built this case; a decoder that bounds
    #     by accumulated value rather than by byte count accepts it and diverges.
    add("contrast_overlong_11byte_zero_pad",
        scalar_hdr + nonminimal_varint(5, 11), "reject")

    # (c) the other half — exactly 10 bytes, but the tenth carries payload above 0x01,
    #     so its bits land at position ≥ 64 (here 0x02 -> bit 64). Within the byte-count
    #     limit and still out of range, which is the case a pure length check misses.
    add("contrast_bit64_10byte_high_payload",
        scalar_hdr + (bytes([0x80]) * 9 + bytes([0x02])), "reject")

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
