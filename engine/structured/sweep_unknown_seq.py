#!/usr/bin/env python3
"""Unknown-sequence sweep (MESSAGE_SPEC §5.2 / CORELIB_PLAN §4.9) — the coverage gap
F-0044 walked through.

A field id the schema does not declare is **skipped whole**. When that id carries a
SEQUENCE wire type, "whole" means the entire subtree: every child inside it, at every
depth, is jumped over and never bound. Nothing inside an unknown sequence may reach the
enclosing scope, and the message must decode exactly as if the sequence were absent.

**Why this axis exists.** `sweep_framing.py` already places unknown ids (50/51) at
scalar, fixlen and array wire types — but never opened one as a SEQUENCE with a payload
inside. So the whole "skip a subtree" half of the rule was unswept, and it took the
fuzzer to find F-0044: `sequenceBegin`'s dispatch has no default arm in the flat-visitor
backends, so a child of a skipped unknown sequence binds into the enclosing scope. A
6-byte defect that six axes walked past.

Per sequence scope it emits, at an unknown id inside that scope:

  * empty            -> the degenerate case sweep_framing effectively had; must be a no-op.
  * one scalar child -> the child must not bind anywhere.
  * nested sequence  -> a subtree two deep; skipping must not be one level only.
  * COLLIDING child  -> the child carries the id of a REAL field of the *enclosing*
                        scope. This is F-0044's exact shape and the sharp vector: a
                        decoder that leaks the child writes it over a live field, so
                        the leak is visible as a value, not merely as a stray.
  * collide + anchor -> the same, with the real field ALSO set before the unknown
                        sequence. The established value must survive; a leaking decoder
                        overwrites it. Distinguishes "leaked into an empty slot" from
                        "clobbered a value", which is what F-0044's two symptoms are.

Every vector is a *valid* message — the unknown id is legal (§5.2 requires forward
compatibility), so all 13 must ACCEPT and agree. A divergence is a finding.

Usage: python3 engine/structured/sweep_unknown_seq.py [out_dir]
       (default corpus/unknown-seq-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, hdr  # noqa: E402
from sweep_positions import (  # noqa: E402
    POSITIONS, SEQ_POSITIONS, STRUCT_CHILDREN, place, valid_field,
)

# Ids absent from schema/probe.sofab.yaml, shared with sweep_framing.py's convention
# (the max real id is 202). A second one is needed for the nested case so the inner
# and outer unknown sequences are distinguishable in a dump.
UNKNOWN_ID_A = 50
UNKNOWN_ID_B = 51


def open_seq(fid, body):
    return hdr(fid, WT_SEQ_BEG) + body + bytes([WT_SEQ_END])


def _scopes():
    """Every scope an unknown sequence can sit in: the root, plus each struct scope.

    A *wrapper* scope is deliberately excluded — inside a wrapper an id is an array
    INDEX (§5.1), not a field id, so an "unknown id" there is an over-index question
    (§7.1, swept by sweep_overbound) rather than a forward-compatibility one.
    """
    yield ()
    for p in SEQ_POSITIONS:
        if p.cat == "seq_struct":
            yield p.path + (p.fid,)


def _real_child(scope):
    """A (cat, id) genuinely declared in `scope` — the collision target."""
    if scope == ():
        return ("scalar_u", 0)          # root u8
    kids = STRUCT_CHILDREN.get(scope)
    return kids[0] if kids else None


def emit(out_dir):
    vectors = []  # (name, bytes, expected)

    for scope in _scopes():
        path = scope
        tag = "root" if not path else "_".join(map(str, path))

        # 1) empty unknown sequence -> a pure no-op
        vectors.append((f"{tag}_unkseq_empty.bin",
                        place(path, open_seq(UNKNOWN_ID_A, b"")), "accept"))

        # 2) one scalar child inside -> must not bind
        child = valid_field("scalar_u", 0, 0)
        vectors.append((f"{tag}_unkseq_scalar_child.bin",
                        place(path, open_seq(UNKNOWN_ID_A, child)), "accept"))

        # 3) a nested sequence inside -> skipping is not one level deep
        inner = open_seq(UNKNOWN_ID_B, valid_field("scalar_u", 0, 1))
        vectors.append((f"{tag}_unkseq_nested_seq.bin",
                        place(path, open_seq(UNKNOWN_ID_A, inner)), "accept"))

        real = _real_child(scope)
        if real is None:
            continue
        cat, cid = real

        # 4) the child COLLIDES with a real field id of the enclosing scope (F-0044)
        collide = valid_field(cat, cid, 1)
        vectors.append((f"{tag}_unkseq_colliding_child.bin",
                        place(path, open_seq(UNKNOWN_ID_A, collide)), "accept"))

        # 5) the same, but the real field is established FIRST. A leaking decoder
        #    overwrites a live value instead of filling an empty slot.
        anchored = valid_field(cat, cid, 0) + open_seq(UNKNOWN_ID_A, collide)
        vectors.append((f"{tag}_unkseq_collide_over_value.bin",
                        place(path, anchored), "accept"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    print(f"{len(vectors)} vectors: "
          f"{sum(1 for _, _, e in vectors if e == 'accept')} accept "
          f"(unknown ids are legal — §5.2 forward compatibility)")
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/unknown-seq-sweep"
    emit(out)
