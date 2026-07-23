#!/usr/bin/env python3
"""Shared schema-position model for the structured *sweep* family.

A sweep enumerates one normative rule across **every field position** in the
schema and expects all 13 drivers to agree; a divergence is a finding. The wire-type
sweep (`wiretype_sweep.py`, §7.3) proved the method — it found F-0022 and F-0023,
two positions the piecemeal §7.3 guard had missed. The bugs live wherever a rule is
enforced at *some* positions but not all, so **position completeness is the whole
game**: this module is the single, shared enumeration every axis builds on, so a new
axis (a new rule) is one function and no axis can silently omit a position.

**This is the ONE position model** (WP-11): `wiretype_sweep.py` used to carry its own
parallel list (a schema change had to be mirrored twice); it now consumes `POSITIONS`
via `CAT_TO_CONSTRUCT`. The wrapper-**element** positions (`string_array`/`blob_array`
element 0) live here too, so every axis — not just §7.3 — sweeps them.

A `Position` is one field slot in `schema/probe.sofab.yaml`:

  path   enclosing sequence ids to open to reach it (empty = root)
  fid    the field id in that scope
  cat    category — how the field is shaped on the wire:
           'scalar_u' 'scalar_s'                     integer scalars
           'fp32' 'fp64' 'str' 'blob'                fixlen leaves
           'arr_u' 'arr_s' 'arr_fp32' 'arr_fp64'     compact/fixlen arrays
           'seq_struct'                               a struct sequence (opens a scope)
           'seq_wrapper'                              an array-wrapper sequence (a value)
           'welem_str' 'welem_blob'                   a wrapper *element* (a fixlen leaf
                                                      inside a wrapper sequence)
  elem   for a wrapper, the element category ('str' for string_array,
         'blob' for blob_array)

Every axis filters positions by `cat` (e.g. §7.4 repeated-id cares about the
sequence positions; §7.1 over-bound cares about arrays and bounded strings/blobs;
§4.6 reserved-subtype and §7.3 wiretype sweep *every* position, wrapper elements
included).

**Counts and maxlens are derived from the schema** (WP-11): no bare `5`/`64`/`32`/`4`
literals that silently desync — `_BOUNDS` reads them from `schema/probe.sofab.yaml`,
the single source, so a schema `count`/`maxlen` change flows through automatically.

Wire primitives come from `gen.py` (the one reference encoder) so a wire change
cannot desync any sweep.
"""
import os
import struct
import sys
from dataclasses import dataclass, field as dc_field

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    WT_SEQ_BEG, WT_SEQ_END, FL_FP32, FL_FP64, FL_STRING, FL_BLOB,
    hdr, scalar_u, scalar_s, fixlen, arr_u, arr_s, arr_fp,
)

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "schema", "probe.sofab.yaml")


def _load_bounds(path=SCHEMA):
    """(enclosing-id-path, field-id) -> {'count', 'maxlen'} from the schema YAML — the
    single source for every bound the sweeps enforce (WP-11: no literal 5/64/32/4)."""
    with open(path) as fh:
        y = yaml.safe_load(fh)
    (_, mspec), = y["messages"].items()          # the schema carries a single message
    out = {}

    def walk(fields, scope):
        for _, spec in fields.items():
            fid = spec["id"]
            t = spec["type"]
            b = {}
            if t == "array":
                it = spec["items"]
                b["count"] = it.get("count", 0)
                if "maxlen" in it:
                    b["maxlen"] = it["maxlen"]
            elif t in ("string", "blob") and "maxlen" in spec:
                b["maxlen"] = spec["maxlen"]
            out[(tuple(scope), fid)] = b
            if t == "struct":
                walk(spec["fields"], scope + [fid])

    walk(mspec["payload"], [])
    return out


_BOUNDS = _load_bounds()


def _count(path, fid):
    return _BOUNDS.get((path, fid), {}).get("count", 0)


def _maxlen(path, fid):
    return _BOUNDS.get((path, fid), {}).get("maxlen", 0)


@dataclass(frozen=True)
class Position:
    path: tuple
    fid: int
    cat: str
    elem: str = ""       # element category for a wrapper
    count: int = 0       # schema count for arrays / wrappers
    maxlen: int = 0      # schema maxlen for strings / blobs

    def tag(self):
        scope = "root" if not self.path else "_".join(map(str, self.path))
        return f"{scope}_id{self.fid}"


# schema/probe.sofab.yaml, enumerated exhaustively -- the single source of positions.
# Bounds (count/maxlen) come from _BOUNDS (the schema), not literals (WP-11).
POSITIONS = [
    # root scalars
    Position((), 0, "scalar_u"), Position((), 1, "scalar_s"),
    Position((), 2, "scalar_u"), Position((), 3, "scalar_s"),
    Position((), 4, "scalar_u"), Position((), 5, "scalar_s"),
    Position((), 6, "scalar_u"), Position((), 7, "scalar_s"),
    # root sequences
    Position((), 10, "seq_struct"),
    Position((), 100, "seq_struct"),
    Position((), 200, "seq_wrapper", elem="str", count=_count((), 200), maxlen=_maxlen((), 200)),
    Position((), 201, "seq_wrapper", elem="blob", count=_count((), 201), maxlen=_maxlen((), 201)),
    # nested struct (id 10): fixlen leaves
    Position((10,), 0, "fp32"), Position((10,), 1, "fp64"),
    Position((10,), 2, "str", maxlen=_maxlen((10,), 2)),
    Position((10,), 3, "blob", maxlen=_maxlen((10,), 3)),
    # arrays struct (id 100): eight numeric arrays + the nested fp-array struct
    Position((100,), 0, "arr_u", count=_count((100,), 0)), Position((100,), 1, "arr_s", count=_count((100,), 1)),
    Position((100,), 2, "arr_u", count=_count((100,), 2)), Position((100,), 3, "arr_s", count=_count((100,), 3)),
    Position((100,), 4, "arr_u", count=_count((100,), 4)), Position((100,), 5, "arr_s", count=_count((100,), 5)),
    Position((100,), 6, "arr_u", count=_count((100,), 6)), Position((100,), 7, "arr_s", count=_count((100,), 7)),
    Position((100,), 10, "seq_struct"),
    # arrays.nested (id 100 -> 10): fp arrays
    Position((100, 10), 0, "arr_fp32", count=_count((100, 10), 0)),
    Position((100, 10), 1, "arr_fp64", count=_count((100, 10), 1)),
    # wrapper *elements* (WP-11: moved here from wiretype_sweep's private list so every
    # axis sweeps them — §4.6 reserved-subtype now covers them too, not only §7.3). The
    # element (id 0) is a fixlen leaf inside the wrapper sequence; its maxlen is the
    # wrapper's element maxlen.
    Position((200,), 0, "welem_str", maxlen=_maxlen((), 200)),
    Position((201,), 0, "welem_blob", maxlen=_maxlen((), 201)),
]

SEQ_POSITIONS = [p for p in POSITIONS if p.cat in ("seq_struct", "seq_wrapper")]
SCALAR_POSITIONS = [p for p in POSITIONS if p.cat in ("scalar_u", "scalar_s")]
ARRAY_POSITIONS = [p for p in POSITIONS if p.cat.startswith("arr_")]

# cat -> the ONE wire construct that is a §7.3 *control* at a position of that cat
# (all other constructs are mismatches). Lets wiretype_sweep.py consume this shared
# model instead of carrying its own parallel position list (WP-11).
CAT_TO_CONSTRUCT = {
    "scalar_u": "U", "scalar_s": "S",
    "fp32": "FIX_fp32", "fp64": "FIX_fp64", "str": "FIX_str", "blob": "FIX_blob",
    "arr_u": "ARR_U", "arr_s": "ARR_S", "arr_fp32": "ARR_fp32", "arr_fp64": "ARR_fp64",
    "seq_struct": "SEQ", "seq_wrapper": "SEQ",
    "welem_str": "FIX_str", "welem_blob": "FIX_blob",
}


# --- framing helpers ---------------------------------------------------------
def open_path(path):
    return b"".join(hdr(p, WT_SEQ_BEG) for p in path)

def close_path(path):
    return bytes([WT_SEQ_END]) * len(path)

def place(path, body):
    """Frame `body` (already a full field, or several) inside `path`'s scopes."""
    return open_path(path) + body + close_path(path)


# --- a canonical *valid* field at a position (the base every axis perturbs) ---
# Each builder takes a field id and a small "variant" int so an axis can make two
# occurrences differ (e.g. for repeated-id last-wins).
def valid_field(cat, fid, variant=0):
    v = 5 + variant
    if cat == "scalar_u": return scalar_u(fid, v)
    if cat == "scalar_s": return scalar_s(fid, v)
    if cat == "fp32":     return fixlen(fid, FL_FP32, struct.pack("<f", 1.0 + variant))
    if cat == "fp64":     return fixlen(fid, FL_FP64, struct.pack("<d", 1.0 + variant))
    if cat in ("str", "welem_str"):   return fixlen(fid, FL_STRING, (b"A", b"B", b"C")[variant % 3])
    if cat in ("blob", "welem_blob"): return fixlen(fid, FL_BLOB, (b"\xde\xad", b"\xbe\xef", b"\x11\x22")[variant % 3])
    if cat == "arr_u":    return arr_u(fid, [v])
    if cat == "arr_s":    return arr_s(fid, [v])
    if cat == "arr_fp32": return arr_fp(fid, [1.0 + variant], "<f", FL_FP32)
    if cat == "arr_fp64": return arr_fp(fid, [1.0 + variant], "<d", FL_FP64)
    raise ValueError(f"no valid_field builder for cat {cat!r}")


# The children of each struct scope, as (child_cat, child_id) — the exact schema.
# Keyed by the struct's OWN scope tuple (its enclosing path + its own id). WP-11:
# (100,) now lists all eight numeric arrays (was two). §7.4's merge-vs-replace test
# (sweep_repeated_id) samples the first two — two *distinct* child ids are enough to
# distinguish merge (both kept) from replace (first lost); the rest are available for
# any axis that wants a wider reopen and keep the model complete.
STRUCT_CHILDREN = {
    (10,):     [("fp32", 0), ("fp64", 1), ("str", 2), ("blob", 3)],
    (100,):    [("arr_u", 0), ("arr_s", 1), ("arr_u", 2), ("arr_s", 3),
                ("arr_u", 4), ("arr_s", 5), ("arr_u", 6), ("arr_s", 7)],
    (100, 10): [("arr_fp32", 0), ("arr_fp64", 1)],
}

def struct_children(scope, variant):
    """One valid child field for the struct whose OWN scope tuple is `scope`, in
    `variant` (0 or 1) — variant 0 and 1 are DIFFERENT child ids, so a §7.4
    repeated-open makes merge (both kept) vs replace (first lost) observable."""
    kids = STRUCT_CHILDREN.get(scope, [("scalar_u", 0), ("scalar_s", 1)])
    cat, cid = kids[variant % len(kids)]
    return valid_field(cat, cid)


if __name__ == "__main__":
    print(f"{len(POSITIONS)} positions: "
          f"{len(SCALAR_POSITIONS)} scalar, {len(ARRAY_POSITIONS)} array, "
          f"{len(SEQ_POSITIONS)} sequence, "
          f"{sum(1 for p in POSITIONS if p.cat.startswith('welem_'))} wrapper-element")
    for p in POSITIONS:
        b = f"  count={p.count}" if p.count else (f"  maxlen={p.maxlen}" if p.maxlen else "")
        print(f"  {p.tag():14} {p.cat}{b}")
