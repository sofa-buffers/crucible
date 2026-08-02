#!/usr/bin/env python3
"""Repeated wrapper-ELEMENT-id sweep (MESSAGE_SPEC §7.4 x §5.1) — the coverage gap
F-0048 walked through.

§5.1 makes a wrapper sequence *"an **ordinary sequence**, so **every element is a normal
field with its own `(id, type)` header**"*, with *"element id = the 0-based array index"*,
and states outright that this *"keeps the ids unique within the wrapper scope (the
'unique ids per scope' rule holds, no exception)"*. §7.4 then governs what a decoder must
do when that uniqueness is violated: process it deterministically, never report
`INVALID`, and let the **last** occurrence apply.

**Why this axis exists — and why `sweep_repeated_id` does not already cover it.** That
axis sweeps §7.4 at every *field* position, including re-opening an array **wrapper**
(`_wrapper_reopen_replace`). What it never does is repeat an **element id inside one
wrapper opening**. F-0019 established the §7.4 axis and has the same blind spot. So the
cell stayed unswept until F-0048: the no-std backend's element sink appends instead of
replacing, and the capacity guard riding on that line then misfires into `buffer_full`
for *any* duplicate element id at *any* size.

Per wrapper position it emits:

  * differing values -> the sharp one: last occurrence wins, earlier is discarded.
  * same value twice -> idempotence; an appending decoder doubles the payload here even
                        though nothing about the value changed.
  * empty then value -> the one order an append gets right by accident (empty prefix +
                        value == value). A decoder that passes only this is not correct.
  * value then empty -> the reverse; the final value must be EMPTY, not the first value.
  * repeat to overflow -> enough repeats that a concatenation would exceed the element
                        `maxlen`, separating "wrong value" from "capacity error". A
                        conformant decoder is unaffected; F-0048's shape rejects.
  * two distinct ids -> CONTROL. Two elements written once each: no repetition, so it
                        must be unanimous. Anything that fails here fails the wrapper,
                        not the repeat, and the axis result would be meaningless.

Every vector is a *valid* message — §7.4 says an id repeat is not well-formed for a
*producer* but binds a *decoder*, explicitly forbidding `INVALID`. All 13 must ACCEPT and
agree on the value.

Usage: python3 engine/structured/sweep_repeated_elem.py [out_dir]
       (default corpus/repeated-elem-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, hdr, fixlen, FL_STRING, FL_BLOB  # noqa: E402
from sweep_positions import (  # noqa: E402
    POSITIONS, place, valid_field, struct_children,
)

# Wrapper positions: the leaf-element wrappers (string_array/blob_array) and the
# struct-element one (struct_array, WP-05 — its own category, since its elements are
# sequences and have no `p.elem` leaf builder).
WRAPPERS = [p for p in POSITIONS if p.cat in ("seq_wrapper", "seq_swrapper")]


def open_seq(fid, body):
    return hdr(fid, WT_SEQ_BEG) + body + bytes([WT_SEQ_END])


def _elem(p, idx, variant):
    """One element of wrapper `p` at index `idx`."""
    if p.cat == "seq_swrapper":
        # struct element: a sequence carrying the {k, v} children
        return open_seq(idx, struct_children(p.path + (p.fid,) + (0,), variant))
    return valid_field(p.elem, idx, variant)


def _empty_elem(p, idx):
    """The same element position carrying an EMPTY value (zero-length / no children)."""
    if p.cat == "seq_swrapper":
        return open_seq(idx, b"")
    return fixlen(idx, FL_STRING if p.elem == "str" else FL_BLOB, b"")


def emit(out_dir):
    vectors = []  # (name, bytes, expected)

    for p in WRAPPERS:
        t = p.tag()
        scope = p.path + (p.fid,)

        # 1) element 0 twice, DIFFERENT values -> last wins
        body = _elem(p, 0, 0) + _elem(p, 0, 1)
        vectors.append((f"{t}_elem_twice_differing.bin",
                        place(p.path, open_seq(p.fid, body)), "lastwins"))

        # 2) element 0 twice, the SAME value -> still last wins (idempotent)
        body = _elem(p, 0, 0) + _elem(p, 0, 0)
        vectors.append((f"{t}_elem_twice_same.bin",
                        place(p.path, open_seq(p.fid, body)), "lastwins"))

        # 3) empty then value — the order an appending decoder gets right by accident
        body = _empty_elem(p, 0) + _elem(p, 0, 1)
        vectors.append((f"{t}_elem_empty_then_value.bin",
                        place(p.path, open_seq(p.fid, body)), "lastwins"))

        # 4) value then empty — the final value must be EMPTY
        body = _elem(p, 0, 1) + _empty_elem(p, 0)
        vectors.append((f"{t}_elem_value_then_empty.bin",
                        place(p.path, open_seq(p.fid, body)), "lastwins"))

        # 5) repeated until a CONCATENATION would exceed the element maxlen, while each
        #    individual occurrence stays well inside it. Separates the value question
        #    from the capacity question: a decoder that replaces never approaches the
        #    bound, one that appends blows past it.
        if p.cat != "seq_swrapper" and p.maxlen:
            one = _elem(p, 0, 0)
            reps = (p.maxlen // 2) + 2          # each occurrence carries 1-2 payload bytes
            vectors.append((f"{t}_elem_repeat_past_maxlen.bin",
                            place(p.path, open_seq(p.fid, one * reps)), "lastwins"))

        # 6) CONTROL: two DISTINCT element ids, once each -> no repetition at all
        body = _elem(p, 0, 0) + _elem(p, 1, 1)
        vectors.append((f"{t}_ctl_two_distinct_elems.bin",
                        place(p.path, open_seq(p.fid, body)), "accept"))

    os.makedirs(out_dir, exist_ok=True)
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    lw = sum(1 for _, _, e in vectors if e == "lastwins")
    print(f"{len(vectors)} vectors: lastwins={lw}, control={len(vectors) - lw} "
          f"(§7.4 forbids INVALID on a repeated id — every vector must accept)")
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/repeated-elem-sweep"
    emit(out)
