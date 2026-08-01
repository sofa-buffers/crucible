#!/usr/bin/env python3
"""Empty-frame / all-default-sequence sweep (MESSAGE_SPEC §2, POC
`omit-all-default-sequences`) — what a present-but-childless sequence denotes,
enumerated at every sequence position.

The POC spec inverted §2's sequence rule: a sequence-typed **field** whose value
equals its declared default is **omitted** (it used to be "always framed"), and an
empty frame became a **non-canonical encoding of the omitted field** that a decoder
MUST accept and a re-encode normalizes away. Three §2 denotation rules fall out,
and each is a distinct failure surface:

  1. an empty frame at a `struct`/`union` **field** position → the field's default
     value, exactly as absence; re-encode drops the frame.
  2. an empty frame at an **array-wrapper** position whose declared `default` is
     the empty collection → the empty array, whose canonical form is *also* the
     omitted field. (The explicit-empty-overrides-a-non-empty-default case needs a
     `default:`-carrying schema field — docs/TODO.md WP-08(c).)
  3. `expect` is always **accept**: rejecting an empty frame anywhere is a §2
     violation (the F-0004 shape: one impl rejects what the family accepts).

The sweep also pins the §2 *consequence* vectors:

  - the **frame-only message** (nothing but empty frames) decodes to the
    all-default value and re-encodes to the **empty byte string** — the
    zero-byte-canonical rule, exercised per position (a driver whose canonical
    path can't produce a 0-byte output shows up here, not in a fuzz corner);
  - a **chain** of nested empty frames collapses recursively (the §2 predicate is
    the conjunction of the children's — an outer sequence whose only child is an
    all-default sequence is itself all-default);
  - a **merged** empty frame (§7.4: the same sequence id reopened, both empty)
    is still all-default;
  - a wrapper carrying only **default-valued leaf elements** is NOT the empty
    array: since documentation#31 the last element is always written, so
    `seq[200](0:"")` is the one-element array `[""]` and re-encodes unchanged,
    while an *interior* default element is a gap;
  - a **zero-count compact array** (`arr_u(fid, [])`) at every numeric-array
    position: the compact analogue of the empty wrapper — legal (CORELIB_PLAN
    §4.7), value-identical to the omitted field, normalized on re-encode.

The union pass (WP-01 pattern) adds the §4.2 corners: an empty union frame (→
`default_id`, re-encode omits) and every option carried **explicitly at its own
default** — including the non-`default_id` options, whose §4.2 identity loss
(the option id cannot survive the round-trip) previously had no wire vector.

Agreement is the oracle for the *normalization* half: the runner machine-checks
accept-vs-reject conformance plus the 13-way canonical-hex agreement, so a driver
that keeps a frame the family drops (or drops one the family keeps) is a hard
accept_value divergence. The byte-exact "normalizes to the control form" pairs
live in corpus/conformance/ (a/a_ctl, d) where a human can diff them.

Usage: python3 engine/structured/sweep_empty_frame.py [out_dir]
       (default corpus/empty-frame-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, hdr, arr_u, arr_s, arr_fp, scalar_u, scalar_s, \
    fstr, fblob, FL_FP32, FL_FP64  # noqa: E402
from sweep_positions import (  # noqa: E402
    POSITIONS, ARRAY_POSITIONS, UNION_SEQ_POSITION, UNION_MEMBER_POSITIONS,
    place, valid_field,
)

# Every sequence-shaped position, the struct_array wrapper included (its own
# SEQ_POSITIONS membership is deliberately withheld — see sweep_positions.py).
ALL_SEQ_POSITIONS = [p for p in POSITIONS
                     if p.cat in ("seq_struct", "seq_wrapper", "seq_swrapper")]

END = bytes([WT_SEQ_END])

# A marker the §2 omission cannot touch: u8 (root id 0) = 1. Placed before every
# frame (ids 10/100/200/201 all sort after 0), so the message stays non-empty and
# a driver that mis-decodes the frame as an error still has to disagree visibly.
MARKER = scalar_u(0, 1)


def empty_seq(fid):
    return hdr(fid, WT_SEQ_BEG) + END


def emit(out_dir):
    vectors = []  # (name, bytes, expect)

    for p in ALL_SEQ_POSITIONS:
        # The struct_array ELEMENT position (path (202,)) was carved out for
        # F-0035/F-0036 (G-0020/G-0021): 12 backends kept an explicit empty element
        # frame (missing the §3/§5.1 trailing rule) and the id-blind camp additionally
        # double-appended on the merge case. Both resolved in sofabgen 0.21.0, so the
        # position rejoins the axis — every sequence position now gets all three.
        # 1) marker + the empty frame at this position (enclosing scopes opened).
        #    For a nested position the enclosing frames then hold nothing but an
        #    empty frame — the recursive-collapse chain comes free.
        vectors.append((f"{p.tag()}_empty_frame.bin",
                        MARKER + place(p.path, empty_seq(p.fid)), "accept"))
        # 2) the frame-only message: same wire without the marker. Decodes to the
        #    all-default message; canonical re-encode is the EMPTY byte string (§2).
        vectors.append((f"{p.tag()}_frame_only.bin",
                        place(p.path, empty_seq(p.fid)), "accept"))
        # 3) §7.4 x §2: the empty frame merged with itself (same id reopened, both
        #    empty) — still all-default, still normalized away.
        vectors.append((f"{p.tag()}_empty_merge.bin",
                        MARKER + place(p.path, empty_seq(p.fid) + empty_seq(p.fid)),
                        "accept"))
        # 4) leaf-wrapper length rules (documentation#31): a single default element
        #    is the one-element array [""], NOT the empty array — the last element
        #    is always written; an interior default element is a gap that the
        #    decoder restores. Both must round-trip to themselves.
        if p.cat == "seq_wrapper":
            e0 = fstr(0, "") if p.elem == "str" else fblob(0, b"")
            e1 = fstr(1, "x") if p.elem == "str" else fblob(1, b"\x78")
            vectors.append((f"{p.tag()}_default_elem_only.bin",
                            MARKER + place(p.path, hdr(p.fid, WT_SEQ_BEG) + e0 + END),
                            "accept"))
            # interior gap: element 0 absent (default), element 1 present -> length 2
            vectors.append((f"{p.tag()}_interior_gap_leaf.bin",
                            MARKER + place(p.path, hdr(p.fid, WT_SEQ_BEG) + e1 + END),
                            "accept"))
        # 5) the sequence-ELEMENT rules (struct_array, WP-05) — the §2 position
        #    where an empty frame is NOT interchangeable with absence:
        if p.cat == "seq_swrapper":
            e = lambda i, body=b"": hdr(i, WT_SEQ_BEG) + body + END
            k = lambda i, v: e(i, scalar_u(0, v))
            # an INTERIOR all-default element between two real ones is NON-canonical
            # since documentation#31: the interior is sparse, so it must normalize to
            # an id GAP (the length is fixed by the last element either way).
            vectors.append((f"{p.tag()}_interior_empty_elem.bin",
                            MARKER + place(p.path, e(p.fid, k(0, 1) + e(1) + k(2, 3))),
                            "accept"))
            # the CANONICAL form of the above — element 0 and 2 present, 1 an id GAP.
            # Was the F-0035 carve-out (G-0020): the 10 id-blind backends compacted it
            # to length 2. Resolved in sofabgen 0.21.0, so it is a vector again.
            vectors.append((f"{p.tag()}_interior_gap_elem.bin",
                            MARKER + place(p.path, e(p.fid, k(0, 1) + k(2, 3))),
                            "accept"))
            # a TRAILING all-default element is CANONICAL (it is the last element, so it
            # carries the length) — `c` used to trim it (F-0036, direction inverted with
            # documentation#31); resolved in sofabgen 0.21.0.
            vectors.append((f"{p.tag()}_trailing_default_elem.bin",
                            MARKER + place(p.path, e(p.fid, k(0, 1) + e(1))),
                            "accept"))

    # 5) zero-count compact arrays: the compact-form analogue at every numeric/fp
    #    array position (CORELIB_PLAN §4.7 legal; §2 value-identical to omission).
    #    NB a *non-zero* short count is no longer "under-count" but simply a shorter
    #    array (documentation#31) — that axis lives in the cross-encode value corpus
    #    (`cap_*` vectors), where the exact re-encoded bytes are compared.
    for p in ARRAY_POSITIONS:
        if p.cat == "arr_u":      body = arr_u(p.fid, [])
        elif p.cat == "arr_s":    body = arr_s(p.fid, [])
        elif p.cat == "arr_fp32": body = arr_fp(p.fid, [], "<f", FL_FP32)
        else:                     body = arr_fp(p.fid, [], "<d", FL_FP64)
        vectors.append((f"{p.tag()}_count0.bin",
                        MARKER + place(p.path, body), "accept"))

    # 6) an empty frame BETWEEN two real fields (ids 10 < 100): the omission must
    #    not desync the scope walk around it — the sibling after the frame decodes.
    both = MARKER + empty_seq(10) + place((100,), valid_field("arr_u", 0))
    vectors.append(("root_frame_between_fields.bin", both, "accept"))

    _write(out_dir, vectors)
    return vectors


def emit_union(out_dir):
    """§4.2 corners over schema/probe-union.sofab.yaml (roster rebuilt by sweep.sh)."""
    u = UNION_SEQ_POSITION
    tag = scalar_u(0, 5)                       # tag (id 0) = 5 — the marker
    vectors = []
    # the empty union frame: → default_id, re-encode omits the frame
    vectors.append(("u_empty_frame.bin", tag + empty_seq(u.fid), "accept"))
    # frame-only: decodes to the all-default message → re-encode = 0 bytes
    vectors.append(("u_frame_only.bin", empty_seq(u.fid), "accept"))
    # each option carried explicitly at its own default — for id != default_id this
    # is the §4.2 identity loss on the wire: it MUST decode as default_id's value
    # and the option id MUST NOT survive the re-encode.
    for p in UNION_MEMBER_POSITIONS:
        if p.cat == "scalar_u":  member = scalar_u(p.fid, 0)
        elif p.cat == "scalar_s": member = scalar_s(p.fid, 0)
        elif p.cat == "str":      member = fstr(p.fid, "")
        else:                     member = fblob(p.fid, b"")
        vectors.append((f"u_member_id{p.fid}_default.bin",
                        tag + hdr(u.fid, WT_SEQ_BEG) + member + END, "accept"))
    _write(out_dir, vectors)
    return vectors


def _write(out_dir, vectors):
    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/empty-frame-sweep"
    v = emit(out)
    accept = sum(1 for _, _, e in v if e == "accept")
    sys.stderr.write(f"{len(v)} vectors: accept={accept}\n")


if __name__ == "__main__":
    main()
