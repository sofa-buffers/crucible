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

**Scope: the sequence-end half.** Class 5b names two tolerance families. The
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

History: this axis exists because F-0054 split the family 4-vs-9 by accident. Had all 13
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
    varint, WT_SEQ_BEG, WT_SEQ_END, hdr, scalar_u,
)
from sweep_positions import (  # noqa: E402
    POSITIONS, STRUCT_CHILDREN, place, valid_field,
)

ID_MAX = (1 << 31) - 1          # CORELIB_PLAN §6.2, fixed format-wide
END = bytes([WT_SEQ_END])       # the canonical marker: id 0, minimal

# Same marker convention as the other axes: u8 (root id 0) = 1, which sorts before
# every sequence id, so the message stays non-empty and a driver that mis-reads the
# end marker has to disagree visibly rather than collapsing to the empty message.
MARKER = scalar_u(0, 1)

ALL_SEQ_POSITIONS = [p for p in POSITIONS
                     if p.cat in ("seq_struct", "seq_wrapper", "seq_swrapper")]


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

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/tolerance-sweep"
    emit(out)
