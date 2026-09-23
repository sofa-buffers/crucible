#!/usr/bin/env python3
"""Fixlen-ARRAY string/blob-subtype sweep (CORELIB_PLAN §4.8.1 step 3 / MESSAGE_SPEC
§7.3) — crucible#173.

A scalar `fixlen` field's `fixlen_word` may legally carry subtype `string` (0x2) or
`blob` (0x3) — `fstr`/`fblob` in `gen.py`. A fixlen **array**'s shared `fixlen_word`
may not: CORELIB_PLAN §4.8 admits only `fp32`/`fp64` there, so `string`/`blob` (and the
reserved range `sweep_reserved_subtype.py` already covers) make the field malformed
regardless of the schema, at the word — §4.8.1 step 3, ahead of any schema check
(step 4's §7.3 mistyped-field skip, and the array's own `count` bound). §5.2.2 lists
it explicitly: *"a fixlen array whose fixlen_word subtype is not fp32/fp64"*.

The failure this axis exists to catch is specific: a decoder that lets `string`/`blob`
fall through to the §7.3 mistyped-field skip (rather than rejecting at the word)
*accepts a construct the format does not have* and still reports `COMPLETE`. Every
port agreeing on that wrong answer is agreement-green — invisible to a differential-
only oracle, exactly the shape MESSAGE_SPEC §7.3's own mirror paragraph warns about:
*"A format violation is never routed to the skip; only a well-formed field of the
wrong declared type is."*

Two vectors per position per subtype:

  * `<pos>_arrfix_<str|blob>subtype.bin`            — a well-formed, skippable-looking
    fixlen array (header, count, the bad fixlen_word, `count*width` payload bytes) →
    expect **reject**. Swept at *every* position — including the `arr_fp32`/`arr_fp64`
    positions, where step 3 must fire ahead of the schema's own fp expectation, and
    every other position, where step 3 must fire ahead of the §7.3 skip a wire-type
    mismatch would otherwise take.
  * `<pos>_arrfix_<str|blob>subtype_trunc_word.bin` — the same field cut immediately
    after the COUNT word and before the fixlen_word begins → expect **not_reject**
    (`A` or `I`, never `R`). This is §4.8.1's own stated boundary: a message truncated
    *between the two words* is `INCOMPLETE`, because the malformation is not yet
    provable — only the fixlen_word (not read yet) carries the bad subtype.

Positions and wire primitives come from `sweep_positions.py` / `gen.py`, exactly as
`sweep_reserved_subtype.py` uses them.

Usage: python3 engine/structured/sweep_fixlen_array_subtype.py [out_dir]
       (default corpus/fixlen-array-subtype-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import hdr, varint, WT_ARR_FIX, FL_STRING, FL_BLOB  # noqa: E402
from sweep_positions import POSITIONS, place, open_path  # noqa: E402

SUBTYPES = ((FL_STRING, "str"), (FL_BLOB, "blob"))


def array_fixlen_bad_subtype(fid, subtype, count=1, width=1, fill=b"A"):
    """A fixlen ARRAY whose shared fixlen_word carries subtype 0x2 (string) or 0x3
    (blob) — otherwise well-formed: a real count, a real length, and exactly
    count*width payload bytes, so a decoder that merely skips a "mistyped" field
    would swallow it silently instead of rejecting.

    Returns (field_bytes, boundary) where `boundary` is the offset right after the
    COUNT word — before the fixlen_word begins — the "truncated between the two
    words" split."""
    h = hdr(fid, WT_ARR_FIX)
    count_w = varint(count)
    boundary = len(h) + len(count_w)
    word = varint((width << 3) | subtype)
    payload = fill * (width * count)
    return h + count_w + word + payload, boundary


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for p in POSITIONS:
        for subtype, label in SUBTYPES:
            field, boundary = array_fixlen_bad_subtype(p.fid, subtype)
            full = place(p.path, field)
            open_len = len(open_path(p.path))

            name = f"{p.tag()}_arrfix_{label}subtype.bin"
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(full)
            vectors.append((name, full, "reject"))

            trunc_name = f"{p.tag()}_arrfix_{label}subtype_trunc_word.bin"
            trunc_data = full[:open_len + boundary]
            with open(os.path.join(out_dir, trunc_name), "wb") as fh:
                fh.write(trunc_data)
            vectors.append((trunc_name, trunc_data, "not_reject"))
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


# --- union pass (schema/probe-union.sofab.yaml) ------------------------------
# WP-01: the same format-before-schema question, over the union schema. A union
# member slot never declares an array (see `_UNION_CAT` in sweep_positions.py), so
# every vector here is necessarily the "declared type is something else entirely"
# case — step 3 must still fire ahead of the §7.3 skip a wire-type mismatch would
# otherwise take, complete vectors only (no truncation half, matching
# sweep_reserved_subtype.py's union pass).
def emit_union(out_dir):
    from sweep_positions import UNION_POSITIONS, place  # noqa: E402
    os.makedirs(out_dir, exist_ok=True)
    vectors = []
    for p in UNION_POSITIONS:
        for subtype, label in SUBTYPES:
            field, _ = array_fixlen_bad_subtype(p.fid, subtype)
            name = f"u_{p.tag()}_arrfix_{label}subtype.bin"
            data = place(p.path, field)
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
            vectors.append((name, data, "reject"))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/fixlen-array-subtype-sweep"
    emit(out)
