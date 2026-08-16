#!/usr/bin/env python3
"""Repeated-field-id sweep (MESSAGE_SPEC §7.4) — the second sweep axis.

§7.4: for each field id in a scope the **last** occurrence applies; a re-opened
sequence **continues** its scope (a struct/union *merges*, keeping children of
earlier openings whose ids do not recur), while an **array wrapper is replaced**
whole. F-0019 established this at the *root* struct/union/wrapper positions. This
sweep applies it at **every** sequence position and **every depth** — the same
generalization that turned the §7.3 isolate into F-0022/F-0023.

For each position it emits the repeated-id form and states the expected agreement:

  * scalar position         -> the scalar twice with two values; last wins (uniform).
  * struct sequence         -> reopened with a DIFFERENT child each time; the two
                               children must MERGE (both present on all 13).
  * wrapper sequence        -> reopened with a different element each time; the
                               array is REPLACED (only the second element survives).
  * struct child within one opening -> a child id twice with two values; last wins.
  * §7.3 x §7.4 product     -> a position that owns storage, given a value and then
                               the same id again with a *contradicting* wire type:
                               the mistyped occurrence is §7.3-skipped, so §7.4 never
                               sees it and the established value survives (both
                               orders). This is the case corelib-c-cpp#111 fixed and
                               that upstream's own suite, not this one, caught.

Every vector is a *valid* message (the repetition is the only irregularity, which
§3 declares not-well-formed but §7.4 defines a decode for). All 13 must agree; a
divergence is a finding. Positions and wire primitives come from
`sweep_positions.py` / `gen.py`.

Usage: python3 engine/structured/sweep_repeated_id.py [out_dir]
       (default corpus/repeated-id-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, hdr  # noqa: E402
from sweep_positions import (  # noqa: E402
    POSITIONS, SEQ_POSITIONS, SCALAR_POSITIONS, CAT_TO_CONSTRUCT,
    place, valid_field, struct_children,
)
# The §7.3 construct table, imported rather than restated: WP-11's rule is that a
# position/construct model lives in exactly one place, so the product axis below
# perturbs with the same builders the §7.3 axis sweeps.
from wiretype_sweep import CONSTRUCTS  # noqa: E402

# Positions whose destination is touched *before* the read is bound, and which the
# §7.3 x §7.4 product below therefore covers (see the axis-4 comment in emit()):
# a wrapper sequence resets its slots on open, a sized string/blob writes its
# length. A scalar destination is bound and nothing else, so a contradicting
# occurrence there can be unbound after the fact with no trace.
_PRE_BIND_CATS = ("seq_wrapper", "str", "blob", "welem_str", "welem_blob")


def open_seq(fid, body):
    return hdr(fid, WT_SEQ_BEG) + body + bytes([WT_SEQ_END])


def _valid_occurrence(p):
    """The occurrence that establishes a value at `p` before the mistyped one lands."""
    if p.cat == "seq_wrapper":
        return open_seq(p.fid, valid_field(p.elem, 0, 0))   # wrapper holding element 0
    return valid_field(p.cat, p.fid, 0)


def emit(out_dir):
    vectors = []  # (name, bytes, expected)

    # 1) scalar repeated with two values -> last wins (the F-0019 control, everywhere)
    for p in SCALAR_POSITIONS:
        body = valid_field(p.cat, p.fid, 0) + valid_field(p.cat, p.fid, 1)
        vectors.append((f"{p.tag()}_scalar_twice.bin", place(p.path, body), "lastwins"))

    # 2) sequence reopened with differing children/elements
    for p in SEQ_POSITIONS:
        scope = p.path + (p.fid,)
        if p.cat == "seq_struct":
            # The struct_array ELEMENT position (path (202,)) was carved out for F-0035
            # (G-0020): reopening the element id merged in c/cpp/dart (§7.4 struct-merge)
            # but APPENDED a second element in the 10 id-blind backends. Resolved in
            # sofabgen 0.21.0 (generator#247) — the same fix sweep_empty_frame.py names —
            # so the position rejoined the axis 2026-08-16: 158 -> 159 vectors, all 15
            # drivers agree on the merge case.
            # reopen the struct twice, a different child each time -> MERGE
            occ0 = open_seq(p.fid, struct_children(scope, 0))
            occ1 = open_seq(p.fid, struct_children(scope, 1))
            vectors.append((f"{p.tag()}_struct_reopen_merge.bin",
                            place(p.path, occ0 + occ1), "merge"))
        else:  # seq_wrapper
            # F-0026 (RESOLVED 2026-07-22, corelib-c-cpp#106): the blob_array wrapper
            # reopen-replace was a C-only divergence — sofab_object_init did not reset a
            # sized-blob's companion length on the §7.4 replace-init, so the C object API
            # kept a stale (zeroed) element where the family dropped it. Fixed in
            # corelib-c-cpp `2416a2b`; both the string_array (elem="str") and blob_array
            # (elem="blob") wrapper reopens now agree across all 13 — no carve-out.
            # reopen the wrapper, a different element index each time -> REPLACE
            occ0 = open_seq(p.fid, valid_field(p.elem, 0, 0))   # element id 0
            occ1 = open_seq(p.fid, valid_field(p.elem, 1, 1))   # element id 1
            vectors.append((f"{p.tag()}_wrapper_reopen_replace.bin",
                            place(p.path, occ0 + occ1), "replace"))

    # 3) a struct child repeated within ONE opening -> last wins (per child id)
    for p in SEQ_POSITIONS:
        if p.cat != "seq_struct":
            continue
        scope = p.path + (p.fid,)
        c0 = struct_children(scope, 0)          # child A (id X)
        # same child id, two values: rebuild child A with a variant so the value differs
        # (struct_children variant 0 twice would be identical; force a value change)
        from sweep_positions import STRUCT_CHILDREN
        kids = STRUCT_CHILDREN.get(scope, [("scalar_u", 0)])
        cat, cid = kids[0]
        twice = valid_field(cat, cid, 0) + valid_field(cat, cid, 1)
        vectors.append((f"{p.tag()}_child_twice_lastwins.bin",
                        place(p.path, open_seq(p.fid, twice)), "lastwins"))

    # 4) §7.3 x §7.4 — a field that already holds a value, then the SAME id again
    #    carrying a contradicting wire type. Both rules are swept on their own (this
    #    axis repeats *validly typed* fields; wiretype_sweep mistypes a *lone* field),
    #    and neither reaches the case where they meet: §7.3 says the mistyped
    #    occurrence is skipped like an unknown id, so §7.4 must never see it and the
    #    established value has to survive untouched.
    #
    #    That product is where corelib-c-cpp#111's last commit found a real bug: a
    #    wrapper sequence resets its slots when it opens (§7.4 replace-whole), so a
    #    contradicting occurrence "emptied an array it was never entitled to touch"
    #    — ["A"] became []. A sized blob had the same shape via used_len. Upstream's
    #    own C conformance run caught it and this suite did not, which is what these
    #    vectors close. Only the pre-bind destinations are swept (_PRE_BIND_CATS): a
    #    scalar is bound and nothing more, so it has no state to clobber.
    #
    #    Both orders, because they fail differently: valid-then-mistyped is the
    #    clobber, mistyped-then-valid checks the skip left no residue that the valid
    #    occurrence then merges into. The union pass already pins this for a scalar
    #    member (u_skip_then_valid / u_valid_then_skip); these are its probe-side
    #    counterparts at the positions that own storage.
    for p in POSITIONS:
        if p.cat not in _PRE_BIND_CATS:
            continue
        good = _valid_occurrence(p)
        declared = CAT_TO_CONSTRUCT[p.cat]
        for cname, build in CONSTRUCTS.items():
            if cname == declared:
                continue                      # not a contradiction — that is axis 2's control
            bad = build(p.fid)
            vectors.append((f"{p.tag()}_{cname}_valid_then_skip.bin",
                            place(p.path, good + bad), "skip"))
            vectors.append((f"{p.tag()}_{cname}_skip_then_valid.bin",
                            place(p.path, bad + good), "skip"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, exp in vectors:
        by[exp] = by.get(exp, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


# --- union pass (schema/probe-union.sofab.yaml) ------------------------------
# WP-01: §7.4 over the union schema. A union is a sequence, so it MERGES on re-open
# and its members follow per-id last-wins (§7.4, "covers structs and unions"). Four
# families, all a *valid* decode (never INVALID), all-agree:
#   * member repeated twice, two values  -> last wins;
#   * two DIFFERENT members in one opening -> merge, re-encoded in id order (the
#     behaviour corpus/union/10_two_members pins: id1 then id0 -> reordered to 0,1);
#   * the union sequence re-opened with a different member each time -> continues the
#     scope (merge);
#   * §7.4's "a §7.3-skipped occurrence does not count" — a mistyped member and a
#     correctly-typed same-id member: the valid one wins, in BOTH orders (:557-558).
def emit_union(out_dir):
    from sweep_positions import (  # noqa: E402
        UNION_MEMBER_POSITIONS, UNION_SEQ_POSITION, valid_field, place,
    )
    from gen import scalar_u  # noqa: E402
    vectors = []
    uid = UNION_SEQ_POSITION.fid

    # 1) each member repeated twice with two values -> last wins
    for p in UNION_MEMBER_POSITIONS:
        body = valid_field(p.cat, p.fid, 0) + valid_field(p.cat, p.fid, 1)
        vectors.append((f"u_{p.tag()}_member_twice.bin", place(p.path, body), "lastwins"))

    m0, m1 = UNION_MEMBER_POSITIONS[0], UNION_MEMBER_POSITIONS[1]  # as_u16(id0), as_i32(id1)

    # 2) two different members in ONE opening (id1 first, out of order) -> merge
    both = valid_field(m1.cat, m1.fid, 0) + valid_field(m0.cat, m0.fid, 0)
    vectors.append(("u_two_members_merge.bin", place((uid,), both), "merge"))

    # 3) the union sequence re-opened, a different member each time -> merge
    occ0 = open_seq(uid, valid_field(m0.cat, m0.fid, 0))
    occ1 = open_seq(uid, valid_field(m1.cat, m1.fid, 0))
    vectors.append(("u_seq_reopen_merge.bin", occ0 + occ1, "merge"))

    # 4) a §7.3-skipped occurrence does not count (both orders). Mistype as_text (id2,
    #    fixlen) as an unsigned scalar at the same id: it is wire-type-mismatched ->
    #    skipped, so the correctly-typed as_text occurrence is the only one that counts.
    mt = next(p for p in UNION_MEMBER_POSITIONS if p.cat == "str")  # as_text
    mistyped = scalar_u(mt.fid, 5)                 # wrong wire type at as_text's id
    good = valid_field(mt.cat, mt.fid, 0)          # correctly-typed as_text
    vectors.append(("u_skip_then_valid.bin", place((uid,), mistyped + good), "accept"))
    vectors.append(("u_valid_then_skip.bin", place((uid,), good + mistyped), "accept"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/repeated-id-sweep"
    emit(out)
