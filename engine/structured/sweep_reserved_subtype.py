#!/usr/bin/env python3
"""Reserved fixlen-subtype sweep (MESSAGE_SPEC §4.6 / §5.2) — the fourth sweep axis.

A fixlen field's `fixlen_word` packs `(length << 3) | subtype`. Subtypes 0x0-0x3 are
fp32 / fp64 / string / blob; **0x4-0x7 are reserved**, and §4.6 is explicit: *"a
decoder MUST reject a fixlen field carrying a reserved subtype as malformed (the
INVALID decode outcome, §5.2)"* — and §5.2 makes INVALID "malformed regardless of
what follows", so it dominates. This sweep places a reserved-subtype fixlen at
**every** field position and expects **all 13 to reject** (`R`).

The interesting tension this axis probes: at a *non-fixlen* position (a scalar or an
integer-array id) a fixlen header is a wire-type mismatch that §7.3 would **skip**,
and "skipped fields are never validated" (CORELIB_PLAN §5.2) says a skip does not
inspect content. Does a *structurally malformed* fixlen_word (reserved subtype) still
reject there, or does the skip swallow it? §4.6+§5.2 say the reserved subtype is a
structural malformation, not a content check, so INVALID should win — but this is
exactly the kind of §4.6-vs-skip precedence the implementations may read differently,
which is why it is worth sweeping every position rather than asserting from the spec.

Because the expectation is **reject**, the two-oracle runner is essential: a
family-wide *accept/skip* (all 13 uniformly swallow the reserved subtype) is
agreement-green but conformance-red — the exact gap a differential-only oracle
misses.

Positions and wire primitives come from `sweep_positions.py` / `gen.py`.

Usage: python3 engine/structured/sweep_reserved_subtype.py [out_dir]
       (default corpus/reserved-subtype-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import hdr, varint, WT_FIX, FL_STRING  # noqa: E402
from sweep_positions import POSITIONS, place  # noqa: E402

RESERVED = (0x4, 0x5, 0x6, 0x7)


def fixlen_reserved(fid, subtype, payload=b"\x00\x00"):
    """A fixlen field whose fixlen_word carries a reserved subtype."""
    return hdr(fid, WT_FIX) + varint((len(payload) << 3) | subtype) + payload


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for p in POSITIONS:
        for st in RESERVED:
            name = f"{p.tag()}_reserved_st{st}.bin"
            data = place(p.path, fixlen_reserved(p.fid, st))
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
            vectors.append((name, data, "reject"))
    # a control: a *valid* fixlen (string subtype) at a fixlen-declared position
    for p in POSITIONS:
        if p.cat in ("fp32", "fp64", "str", "blob"):
            name = f"{p.tag()}_valid_st_ctl.bin"
            data = place(p.path, hdr(p.fid, WT_FIX) + varint((1 << 3) | FL_STRING) + b"A") \
                if p.cat == "str" else \
                place(p.path, hdr(p.fid, WT_FIX) + varint((1 << 3) | 0x3) + b"A")  # blob: any bytes
            # (fp positions need exact-width payloads; skip them as controls to stay valid)
            if p.cat in ("str", "blob"):
                with open(os.path.join(out_dir, name), "wb") as fh:
                    fh.write(data)
                vectors.append((name, data, "accept"))
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/reserved-subtype-sweep"
    emit(out)
