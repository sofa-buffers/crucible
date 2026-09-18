#!/usr/bin/env python3
"""Wire-type sweep — a *structured* corpus that systematically enumerates, for every
field position in the schema and every wire construct, a message that places one
field there with that construct's header.

Motivation. Byte-mutation fuzzing practically never produces a *well-formed* field
that carries the wrong wire type at a valid id — it is a needle in the space. Yet
that is exactly the shape of the whole §7.3 axis: F-0017 (one isolate), F-0020 (the
axis: every mismatch diverged), F-0021 (a scalar receiving an array of the same
signedness, the corner five backends missed). Each was found by *enumeration*, not
mutation. This generator turns that enumeration into a standing suite.

The rule under test (MESSAGE_SPEC §7.3): a field whose header wire type — for a
`fixlen` field, including the subtype — is not the one its declared type maps to
(§1) MUST be **skipped**, exactly as an unknown id is skipped; a matching one
decodes. So for every (position, construct):

  * construct == the position's declared type  -> a **control**: the field decodes,
    the message round-trips, all drivers agree;
  * otherwise                                   -> a **mismatch**: the field is
    skipped, the message decodes as all-default, all drivers agree.

Either way the oracle requires **all drivers to agree**.

Positions come from the shared `sweep_positions.POSITIONS` (WP-11: this axis used to
carry its own parallel list; it now consumes the one model via `CAT_TO_CONSTRUCT`, so
a schema change is mirrored once and the wrapper-**element** positions are shared with
every other axis). Wire primitives are imported from `gen.py` (the one reference
encoder) so an encoding change cannot silently desync this suite.

Usage: python3 engine/structured/wiretype_sweep.py [out_dir]
       (default corpus/wiretype-sweep)
"""
import dataclasses
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (
    WT_SEQ_BEG, WT_SEQ_END, WT_ARR_U, WT_ARR_S, FL_FP32, FL_FP64, FL_STRING, FL_BLOB,
    hdr, varint, scalar_u, scalar_s, fixlen, arr_u, arr_s, arr_fp,
)
from sweep_positions import POSITIONS, CAT_TO_CONSTRUCT  # noqa: E402  (the ONE model)

# --- the wire constructs we place, one representative body each ---------------
# Each builder takes a field id and returns the full field bytes (header + body).
def _seq(fid):  # an empty sequence: open + immediately close
    return hdr(fid, WT_SEQ_BEG) + bytes([WT_SEQ_END])

CONSTRUCTS = {
    "U":         lambda fid: scalar_u(fid, 5),
    "S":         lambda fid: scalar_s(fid, 3),
    "FIX_fp32":  lambda fid: fixlen(fid, FL_FP32, struct.pack("<f", 1.5)),
    "FIX_fp64":  lambda fid: fixlen(fid, FL_FP64, struct.pack("<d", 1.5)),
    "FIX_str":   lambda fid: fixlen(fid, FL_STRING, b"A"),
    "FIX_blob":  lambda fid: fixlen(fid, FL_BLOB, b"\xde\xad"),
    "ARR_U":     lambda fid: arr_u(fid, [5]),
    "ARR_S":     lambda fid: arr_s(fid, [3]),
    "ARR_fp32":  lambda fid: arr_fp(fid, [1.5], "<f", FL_FP32),
    "ARR_fp64":  lambda fid: arr_fp(fid, [1.5], "<d", FL_FP64),
    "SEQ":       _seq,
}


def place(path, fid, body):
    """One field carrying `body` at (path, fid); enclosing sequences opened/closed.
    The rest of the probe message stays default (omitted) — a valid sparse message."""
    out = bytearray()
    for p in path:
        out += hdr(p, WT_SEQ_BEG)
    out += body
    out += bytes([WT_SEQ_END]) * len(path)
    return bytes(out)


def emit(out_dir):
    """Write vectors and return [(name, bytes, expect)]. A control (matching wire
    type) and a mismatch (skipped → decodes as all-default) both yield verdict `A`,
    so `expect="accept"` for every vector — a driver that instead rejects or
    mis-decodes a mismatch shows up as a divergence in the runner. The `declared`
    control construct for each position is derived from its `cat` (CAT_TO_CONSTRUCT)."""
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for p in POSITIONS:
        declared = CAT_TO_CONSTRUCT[p.cat]
        for cname, build in CONSTRUCTS.items():
            kind = "ctl" if cname == declared else "mism"
            # The fp-array-meets-other-fp-width cells were the F-0042 carve-out: both are
            # ArrayKind.FIXLEN, so the corelib's array-header hook had to widen to carry
            # the element subtype before the §7.3 skip could precede the schema `count`
            # bound. Shipped in the seven corelibs (go/java/cs/dart/rs/rs-no-std/zig) and
            # consumed by the backends in generator#259; the cells are green on their own
            # now, so the axis covers the full construct product again.
            name = f"{p.tag()}_{cname}_{kind}.bin"
            # One axis, one rule. At a boolean position the unsigned constructs carry
            # the generic value 5 (or [5]), which is a perfectly legal `true` — but it
            # is a NON-CANONICAL one, so this §7.3 cell would also assert §4.4's
            # normalization and go red on F-0064 / G-0042. Use the canonical spelling
            # here; the §4.4 rule is swept in full, at all five boolean positions and
            # over six values, by sweep_tolerance, which is where a failure belongs.
            b = build
            if p.cat == "scalar_bool" and cname == "U":
                b = lambda fid: scalar_u(fid, 1)
            elif p.cat == "arr_bool" and cname == "ARR_U":
                b = lambda fid: arr_u(fid, [1])
            data = place(list(p.path), p.fid, b(p.fid))
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
            vectors.append((name, data, "accept"))
    for name, data, expect in _sized_mismatches():
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
        vectors.append((name, data, expect))
    return vectors


# --- the skip does not depend on the size of what is skipped ------------------
# Every mismatch above carries a one-element body, and that hid G-0043: generated
# Python ACCEPTED a mistyped element in an array-of-struct wrapper, so the corelib
# READ it -- harmless at one element, and only the size makes a read observable. A
# read is capped (the receiver's max_dyn_array_count) and, when the message ends
# inside it, held in the reassembly buffer, which generated Python sizes to the
# largest value the schema can carry. A skip is neither (MESSAGE_SPEC §7.3,
# CORELIB_PLAN §6.7.2: "neither materializes nor validates ... and is never
# capped"). So the same mismatch is placed again at three sizes, at every position:
#
#   big      COMPLETE, 70000 elements: above both default cap tiers (65536 and
#            16384, generator ARCHITECTURE §9.5) -> accept, as the small one does
#   hdronly  the count word announces 1886575 elements and the message ends there:
#            a skip is still waiting for bytes -> INCOMPLETE, never L
#   partial  1024 of 1100 elements, then the message ends: far above any value the
#            probe schema can carry in one piece -> INCOMPLETE, never a refusal
#
# plus the three again at an index ABOVE each wrapper's schema count (§7.3 wins
# against the index bound too; the nightly isolates sat at ids 9 and 1378). The
# body is a native integer array because only it carries a count ahead of its
# payload; an unsigned one everywhere except where that is the declared type.
BIG_COUNT = 70000
HDRONLY_COUNT = 1886575
PARTIAL = (1100, 1024)
WRAPPERS = {200, 201, 202}
OVER_INDEX = 9  # every probe wrapper declares count 5


def _mismatched_array(p, count, present):
    wt = WT_ARR_S if CAT_TO_CONSTRUCT[p.cat] == "ARR_U" else WT_ARR_U
    return hdr(p.fid, wt) + varint(count) + b"\x01" * present


def _open(path):
    return b"".join(hdr(q, WT_SEQ_BEG) for q in path)


def _sized_mismatches():
    positions = list(POSITIONS)
    for p in POSITIONS:
        if p.path and p.path[-1] in WRAPPERS and p.fid == 0:
            positions.append(dataclasses.replace(p, fid=OVER_INDEX))
    out = []
    for p in positions:
        path = list(p.path)
        tag = p.tag()
        out.append((f"{tag}_ARRbig_mism.bin",
                    place(path, p.fid, _mismatched_array(p, BIG_COUNT, BIG_COUNT)), "accept"))
        out.append((f"{tag}_ARRhdronly_mism.bin",
                    _open(path) + _mismatched_array(p, HDRONLY_COUNT, 0), "not_reject"))
        out.append((f"{tag}_ARRpartial_mism.bin",
                    _open(path) + _mismatched_array(p, *PARTIAL), "not_reject"))
    return out


# --- union pass (schema/probe-union.sofab.yaml) ------------------------------
# WP-01: §7.3 over the union schema. A construct that mismatches a member's declared
# type is skipped (§7.3); a union whose only child is skipped is empty -> `default_id`
# (§4.2), so a mismatch still decodes as the default union — verdict `A`, all agree,
# same as the probe pass. The `seq_union` position (the union field itself) declares
# SEQ; a non-SEQ construct there skips the whole union field -> default_id likewise.
_UNION_DECL = {"scalar_u": "U", "scalar_bool": "U", "scalar_s": "S", "str": "FIX_str",
               "blob": "FIX_blob", "seq_union": "SEQ"}


def emit_union(out_dir):
    """§7.3 over every union position x every wire construct. Control (matching type)
    and mismatch (skipped -> union default_id) both yield `A`, so `expect="accept"`
    throughout; a driver that rejects or mis-decodes a mismatch is a divergence."""
    from sweep_positions import UNION_POSITIONS  # noqa: E402
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for p in UNION_POSITIONS:
        declared = _UNION_DECL[p.cat]
        for cname, build in CONSTRUCTS.items():
            kind = "ctl" if cname == declared else "mism"
            name = f"u_{p.tag()}_{cname}_{kind}.bin"
            data = place(list(p.path), p.fid, build(p.fid))
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
            vectors.append((name, data, "accept"))
    return vectors


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "corpus/wiretype-sweep"
    v = emit(out_dir)
    ctl = sum(1 for n, _, _ in v if n.endswith("_ctl.bin"))
    print(f"{len(v)} vectors ({ctl} controls, {len(v)-ctl} mismatches) over "
          f"{len(POSITIONS)} field positions x {len(CONSTRUCTS)} wire constructs")


if __name__ == "__main__":
    main()
