#!/usr/bin/env python3
"""Tolerance sweep (CORELIB_PLAN §7.2 test class **5b**) — the class a differential
oracle is structurally blind to.

Every other axis here asks whether the family *agrees*, and asserts a verdict on top.
That catches a decoder which is too **lenient**: it accepts what the others reject and
the partition shows it. It cannot catch a decoder which is too **strict** *if they are
all too strict together* — 13 rejects is unanimous, and unanimity is what green looks
like. §7.2 added class 5b for exactly this:

  > input that is non-canonical but well-formed **MUST** decode to the value it denotes
  > and re-encode canonically, never `INVALID` […] These are the cases where a decoder
  > is *stricter* than the format allows — the mirror of the malformed-input tests
  > above, and the ones a majority-vote conformance check cannot catch, since an
  > implementation may be uniformly too strict.

The axis is testable because a sweep vector carries an **absolute** expectation
(`expect="accept"`), not merely "the drivers agree" — so a family-wide over-rejection
is conformance-red here while being agreement-green everywhere else.

**Scope: the sequence-end half and the boolean half.** Class 5b names two tolerance
families of its own, and CORELIB_PLAN §4.4 adds a third that belongs here for exactly the
same reason — it is a rule about a value a decoder must ACCEPT and NORMALIZE, which no
agreement oracle can see:

  > **Canonical on encode, tolerant on decode.** An encoder **MUST** write `true` as `1`.
  > A decoder **MUST** read **every value other than `0`** as `true`: such a value is
  > **not** `INVALID` (§5.2), it is normalized away, and a re-encode emits `1` — the same
  > bargain §4.1.2 strikes for a non-minimal varint.

The boolean is also the one integer-backed leaf type with **no width bound** (MESSAGE_SPEC
§1): `u8 = 256` is `INVALID` under §7.1, `boolean = 256` is a legal spelling of `true`. A
port that binds a boolean to its storage width — the single most likely way to get this
wrong — rejects there, or truncates 256 to 0 and decodes `false`. Both are caught here,
the first as a verdict split, the second by the `same:` twin.

Until 2026-09-18 `schema/probe.sofab.yaml` declared no boolean at all, so neither half was
reachable by any vector in any corpus. AUDIT_v3 carries an open "no dedicated boolean read
function" finding for ten of the twelve ports, which is precisely a rule with no
implementation — and every gate here was green.

The other family: the
non-minimal varint family — at a field header, a `fixlen_word` and an element count —
is already swept exhaustively by `sweep_varint` (WP-03), which carries `expect="accept"`
and the same reasoning; duplicating it here would only give a second place for the two
to disagree. This axis owns the other one: **a sequence-end header whose id is non-zero
but within `ID_MAX`** (CORELIB_PLAN §4.9).

  * an encoder MUST emit a sequence end as exactly `0x07`;
  * a decoder MUST **accept any id it can represent**, **discard** it, and re-encode the
    marker as `0x07`. A non-zero id is *not* `INVALID` — the id sub-field exists only to
    keep the header format uniform and carries no information;
  * but *discarded is not unvalidated*: the id is bounded by `ID_MAX` like every other
    header's (§6.2), so an id **above** the ceiling is `INVALID`. The bound is on the
    id's **value**, not on its spelling, which is why a non-minimal encoding of an
    in-range id stays valid (§4.1).

That last pair is the whole point of the axis and is swept as a contrast: tolerance and
strictness meet at one boundary, and a decoder that gets either side wrong is caught.

**Why the vectors carry a value.** The F-0054 isolate closes a *skipped* subtree, so its
whole message re-encodes to the empty byte string and the discarded id is unobservable —
it proves the verdict and nothing else. Every vector here closes a **declared** sequence
holding a real field, so the round-trip oracle sees the normalization: the re-encode must
carry the field and a bare `07`. A driver that accepted the id and then echoed it back
must equal the canonical twin's byte-for-byte. The tolerance vectors therefore carry
`expect="same:<ctl>"`, an expectation added to the runner for this axis: **accept AND
normalize**. Accept-vs-reject alone cannot see this half — a family that accepted the
input and echoed the non-canonical form straight back would agree with itself and pass
every other check in the suite.

History: this axis exists because F-0054 split the family 4-vs-9 by accident. Had every driver
applied `ID_MAX` to wire type 7 — which nine of them did — no divergence would have
appeared, and the spec's own tolerance rule would have been violated family-wide and
silently. Two of the three positions taken on that clause in one day would have been
invisible here.

Usage: python3 engine/structured/sweep_tolerance.py [out_dir]  (default corpus/tolerance-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    varint, WT_SEQ_BEG, WT_SEQ_END, WT_U, WT_ARR_U, hdr, scalar_u, arr_u,
)
from sweep_positions import (  # noqa: E402
    POSITIONS, STRUCT_CHILDREN, UNION_SEQ_POSITION, UNION_MEMBER_POSITIONS,
    place, valid_field,
)

ID_MAX = (1 << 31) - 1          # CORELIB_PLAN §6.2, fixed format-wide
END = bytes([WT_SEQ_END])       # the canonical marker: id 0, minimal

# Same marker convention as the other axes: u8 (root id 0) = 1, which sorts before
# every sequence id, so the message stays non-empty and a driver that mis-reads the
# end marker has to disagree visibly rather than collapsing to the empty message.
MARKER = scalar_u(0, 1)

ALL_SEQ_POSITIONS = [p for p in POSITIONS
                     if p.cat in ("seq_struct", "seq_wrapper", "seq_swrapper")]

# every §4.4 boolean the schema declares — scalar and array, at all four positions
BOOL_POSITIONS = [p for p in POSITIONS if p.cat in ("scalar_bool", "arr_bool")]


def seq_end(id_):
    """A sequence-end header carrying `id_`, minimally encoded."""
    return varint((id_ << 3) | WT_SEQ_END)


def seq_end_nonminimal(pad):
    """Id 0 on a sequence end, spelled with `pad` redundant continuation bytes.

    §4.1 binds minimality on the **encoder**; a decoder must accept the non-minimal
    spelling of an in-range id and re-emit `0x07`. `07` -> `87 00` -> `87 80 00`.
    """
    return bytes([WT_SEQ_END | 0x80]) + b"\x80" * (pad - 1) + b"\x00"


def _content(p):
    """A real field to put inside the sequence, so the re-encode is observable.

    An empty frame would be normalized away by §2 and the marker with it, which is
    precisely the blind spot the F-0054 isolate had. Every vector must carry a value.
    """
    scope = p.path + (p.fid,)
    kids = STRUCT_CHILDREN.get(scope)
    if kids:
        cat, cid = kids[0]
        return valid_field(cat, cid)
    if p.cat == "seq_wrapper":
        # a wrapper array: element 0 is a leaf of the declared element type
        return valid_field(p.elem, 0)
    if p.cat == "seq_swrapper":
        # struct_array: element 0 is itself a sequence, so give it its own first child
        inner_kids = STRUCT_CHILDREN.get((p.fid, 0), [])
        inner = valid_field(*inner_kids[0]) if inner_kids else b""
        return hdr(0, WT_SEQ_BEG) + inner + END
    return b""


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []

    def add(name, data, expect):
        vectors.append((f"{name}.bin", data, expect))

    for p in ALL_SEQ_POSITIONS:
        body = _content(p)
        if not body:
            continue
        tag = p.tag()

        def frame(end_bytes):
            return MARKER + place(p.path, hdr(p.fid, WT_SEQ_BEG) + body + end_bytes)

        # --- the control: the canonical marker, so every vector below has a twin ---
        add(f"{tag}_end_canonical_ctl", frame(END), "accept")

        # --- TOLERANCE: an id the decoder must accept and discard (§4.9) ----------
        # A small id, and the largest id that exists at all. Both must decode as an
        # ordinary sequence end and re-encode as `07`, identical to the control.
        ctl = f"{tag}_end_canonical_ctl.bin"
        add(f"{tag}_end_id_small", frame(seq_end(3)), f"same:{ctl}")
        add(f"{tag}_end_id_at_ID_MAX", frame(seq_end(ID_MAX)), f"same:{ctl}")

        # --- TOLERANCE: id 0, spelled non-minimally (§4.1 x §4.9) -----------------
        # The distinction that decides the clause: the bound is on the id's VALUE, so
        # its SPELLING is free. `87 00` and `87 80 00` both denote id 0.
        add(f"{tag}_end_id0_nonminimal", frame(seq_end_nonminimal(1)), f"same:{ctl}")
        add(f"{tag}_end_id0_nonminimal2", frame(seq_end_nonminimal(2)), f"same:{ctl}")

        # --- STRICTNESS: the other side of the same boundary ----------------------
        # Discarded is not unvalidated. One past the ceiling is INVALID (§6.2, §5.2) —
        # this is F-0054, and it is the contrast that keeps the axis from being a
        # one-way "accept everything" test.
        add(f"{tag}_end_id_over_ID_MAX", frame(seq_end(ID_MAX + 1)), "reject")
        # A header varint over §4.1's 64-bit bound is INVALID on a sequence end as
        # anywhere else — the one constraint the §6.2 carve-out does NOT lift.
        add(f"{tag}_end_varint_over_64bit",
            frame(b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02"), "reject")

    # ---- the §4.4 boolean pass, at every boolean position the schema declares ----
    for p in BOOL_POSITIONS:
        tag = p.tag()
        is_arr = p.cat == "arr_bool"

        def put(v):
            """The boolean field carrying the raw wire value `v` at this position.

            For the array position the value goes into element 0 and the remaining
            elements stay canonical, so the count (the array's length) is identical to
            the control and the ONLY difference is the spelling of one element."""
            if is_arr:
                return place(p.path, arr_u(p.fid, [v, 1, 0, 1, 1]))
            return place(p.path, scalar_u(p.fid, v))

        def put_raw(raw):
            """The same field with the value varint spelled by hand (non-minimally)."""
            if is_arr:
                body = hdr(p.fid, WT_ARR_U) + varint(5) + raw + b"\x01\x00\x01\x01"
            else:
                body = hdr(p.fid, WT_U) + raw
            return place(p.path, body)

        # the control: `true` spelled canonically (1) — every vector below must
        # re-encode to exactly these bytes
        ctl = f"{tag}_bool_true_ctl.bin"
        add(f"{tag}_bool_true_ctl", MARKER + put(1), "accept")

        # --- TOLERANCE: every non-zero value IS `true` and normalizes to 1 --------
        # The values are chosen so that each defeats one WAY of getting §4.4 wrong, and
        # no two defeat the same way:
        #   2          bit 0 clear   -> catches `v & 1` (which is what a raw value stored
        #                               into a C++ `bool` degenerates to; found F-0064)
        #   0xff       all 8 bits    -> passes `& 1` and every truncation: the control
        #                               that proves a failure above is not "rejects big"
        #   256        1 << 8        -> catches a u8-width destination (truncates to 0,
        #                               i.e. `true` silently becomes `false`; found G-0042)
        #   2^32       1 << 32       -> the same for a 32-bit accumulator
        #   2^63       1 << 63       -> the same for a 64-bit one, and the sign bit: a port
        #                               testing `v > 0` on a SIGNED accumulator reads false
        #   2^64-1     every bit     -> the largest value a varint can denote at all
        # None of them is INVALID (§4.4 lifts the width bound), and every one must
        # re-encode to the control's bytes.
        for name, v in (("two", 2), ("0xff", 0xFF), ("256_over_u8", 256),
                        ("2p32_over_u32", 1 << 32), ("2p63_sign_bit", 1 << 63),
                        ("u64_max", (1 << 64) - 1)):
            add(f"{tag}_bool_{name}", MARKER + put(v), f"same:{ctl}")

        # --- TOLERANCE: `1`, spelled non-minimally (§4.1.2 x §4.4) ----------------
        # The two tolerance rules meet: a padded varint denoting 1 is still `true`, and
        # the re-encode is minimal. `01` -> `81 00` -> `81 80 00`.
        add(f"{tag}_bool_true_nonminimal", MARKER + put_raw(b"\x81\x00"), f"same:{ctl}")
        add(f"{tag}_bool_true_nonminimal2", MARKER + put_raw(b"\x81\x80\x00"), f"same:{ctl}")

        # --- TOLERANCE: `false`, written explicitly, is the omitted field ----------
        # The §2 half of the same question: `false` is the declared default, so writing
        # it is writing nothing. The twin is the SAME position with the field absent —
        # `place(p.path, b"")`, not a bare MARKER, because what the enclosing scopes
        # re-encode to is their own business: an all-default `nested` is omitted (§2)
        # while a struct_array's last element stays framed even when empty (§5.1). Both
        # vectors go through the identical scopes, so the twin holds at every position
        # without this axis having to model either rule.
        #
        # An ARRAY element is the exception: a compact array's count IS its length
        # (documentation#31), so element 0 = 0 is a real `false` that stays on the wire.
        if is_arr:
            fctl = f"{tag}_bool_false_elem_ctl.bin"
            add(f"{tag}_bool_false_elem_ctl", MARKER + put(0), "accept")
            add(f"{tag}_bool_false_elem_nonminimal", MARKER + put_raw(b"\x80\x00"),
                f"same:{fctl}")
        else:
            fctl = f"{tag}_bool_false_absent_ctl.bin"
            add(f"{tag}_bool_false_absent_ctl", MARKER + place(p.path, b""), "accept")
            add(f"{tag}_bool_false_explicit", MARKER + put(0), f"same:{fctl}")
            add(f"{tag}_bool_false_nonminimal", MARKER + put_raw(b"\x80\x00"), f"same:{fctl}")

        # --- STRICTNESS: the one bound a boolean still carries ---------------------
        # §4.1.3: a value varint wider than 64 bits is INVALID wherever it appears. The
        # boolean lifts the WIDTH bound, not the format's own varint ceiling — without
        # this the axis would only ever say "accept", and a decoder that accepted an
        # 11-byte varint here would look conformant.
        add(f"{tag}_bool_varint_over_64bit",
            MARKER + put_raw(b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02"),
            "reject")

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


def emit_union(out_dir):
    """The same rule over schema/probe-union.sofab.yaml (roster rebuilt by sweep.sh).

    A union is an ordinary sequence on the wire, so §4.9 binds its closing marker exactly
    as it binds a struct's — but the union lives in its own schema, so the probe pass
    above cannot reach it. This is the product cell F-0044, F-0048, F-0053 and F-0054 all
    came out of: two axes each correct, the place they meet untested.
    """
    os.makedirs(out_dir, exist_ok=True)
    u = UNION_SEQ_POSITION
    tag = scalar_u(0, 5)                       # tag (id 0) = 5 — keeps the message non-empty
    member = valid_field(UNION_MEMBER_POSITIONS[0].cat, UNION_MEMBER_POSITIONS[0].fid)
    vectors = []

    def add(name, end_bytes, expect):
        vectors.append((f"{name}.bin", tag + hdr(u.fid, WT_SEQ_BEG) + member + end_bytes, expect))

    ctl = "u_end_canonical_ctl.bin"
    add("u_end_canonical_ctl", END, "accept")
    add("u_end_id_small", seq_end(3), f"same:{ctl}")
    add("u_end_id_at_ID_MAX", seq_end(ID_MAX), f"same:{ctl}")
    add("u_end_id0_nonminimal", seq_end_nonminimal(1), f"same:{ctl}")
    add("u_end_id0_nonminimal2", seq_end_nonminimal(2), f"same:{ctl}")
    add("u_end_id_over_ID_MAX", seq_end(ID_MAX + 1), "reject")
    add("u_end_varint_over_64bit",
        b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02", "reject")

    # ---- §4.4 x §4.2: the boolean MEMBER (the fifth boolean position) -------------
    # The one place the two rules meet. A member at its own default reduces to the
    # OMITTED union (§4.2's identity loss: the option id cannot survive a round-trip),
    # so here `false` in any spelling must re-encode to *nothing* — while `true` in any
    # spelling must re-encode to this option id carrying 1. A port that normalizes the
    # value but not the identity, or vice versa, fails exactly one of the two twins.
    bm = next((p for p in UNION_MEMBER_POSITIONS if p.cat == "scalar_bool"), None)
    if bm is not None:
        def umember(body, name, expect):
            vectors.append((f"{name}.bin",
                            tag + hdr(u.fid, WT_SEQ_BEG) + body + END, expect))

        tctl = "u_member_bool_true_ctl.bin"
        umember(scalar_u(bm.fid, 1), "u_member_bool_true_ctl", "accept")
        for nm, v in (("two", 2), ("0xff", 0xFF), ("256_over_u8", 256),
                      ("2p63_sign_bit", 1 << 63), ("u64_max", (1 << 64) - 1)):
            umember(scalar_u(bm.fid, v), f"u_member_bool_{nm}", f"same:{tctl}")
        umember(hdr(bm.fid, WT_U) + b"\x81\x00", "u_member_bool_true_nonminimal",
                f"same:{tctl}")
        # the `false` half: the member's default, so the whole union is omitted. Its
        # twin is the tag alone — which re-encodes to a NON-empty message, so the
        # comparison still observes normalization (the axis rejects an empty twin).
        fctl = "u_member_bool_false_ctl.bin"
        vectors.append((fctl, tag, "accept"))
        umember(scalar_u(bm.fid, 0), "u_member_bool_false_explicit", f"same:{fctl}")
        umember(hdr(bm.fid, WT_U) + b"\x80\x00", "u_member_bool_false_nonminimal",
                f"same:{fctl}")

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} union vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/tolerance-sweep"
    emit(out)
