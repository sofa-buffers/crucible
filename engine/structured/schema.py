#!/usr/bin/env python3
"""Generated schema-type descriptor — the "schema-type table" for the materialized
oracle (oracle/materialized.md).

A value walk (unlike the round-trip re-encode) needs schema-type info the wire does
not carry: which field id is unsigned/signed/fp32/fp64/string/blob, the struct
nesting, the array counts. The C driver gets this generically from sofabgen's object
descriptor; the other drivers hardcode it, so a schema change breaks every walker.
This derives one language-neutral descriptor from `schema/probe.sofab.yaml` — the
single schema source — so a schema change regenerates the table instead.

`descriptor()` returns the typed field tree; `--json [path]` writes it (the artifact
drivers/reference consume). Kinds:

  u s fp32 fp64 string blob        leaves
  bool                             a CORELIB_PLAN §4.4 boolean. Its own kind, not `u`:
                                   the wire carries an unsigned integer but the VALUE is
                                   two-valued, so a walker must render `u0`/`u1` out of a
                                   native `bool` (Go/Dart/Kotlin/…) — and a port that kept
                                   a non-normalized `2` renders `u2`, which is the
                                   divergence this kind exists to make visible
  struct  { fields: [...] }        a nested struct/message scope
  union   { default_id, options: [...] }   a sequence carrying at most one child;
                                           the active option's id selects it (§4.2)
  enum                             an `enum`: an integer on the wire (signed, zigzag) but its OWN
                                   kind here, because most languages hold it as a native enum type
                                   and the walker must print the integer (`s<value>`)
  bitfield                         a `bitfield`: an unsigned integer (`u<value>`); its own kind for
                                   the same reason (a native flags type, not a number)
  array   { elem: u|s|fp32|fp64, count }   an inline fixed-count numeric/fp array
  wrapper { elem: string|blob, count }     a dynamic index-keyed element sequence
  struct_wrapper { count, fields: [...] }  a wrapper whose elements are struct
                                           sequences (array-of-struct, §5.2)
  node_wrapper { count, item: <node> }     a wrapper whose elements are any OTHER nameless node:
                                           a union (array of unions) or an array (array of arrays).
                                           A walker emits the container's actual elements in index
                                           order, each through `item`

Usage: python3 engine/structured/schema.py [--json [out]] [--schema path]
"""
import json
import os
import sys

import yaml

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "schema", "probe.sofab.yaml")

# schema leaf type -> materialized-form kind
_SCALAR = {
    "u8": "u", "u16": "u", "u32": "u", "u64": "u",
    "i8": "s", "i16": "s", "i32": "s", "i64": "s",
    "fp32": "fp32", "fp64": "fp64", "string": "string", "blob": "blob",
    # §4.4: a boolean is an unsigned integer on the wire, but it is NOT `u` here —
    # see the kind list above. `array of boolean` reuses the unsigned array wire form
    # (MESSAGE_SPEC §4.7), so `elem` becomes "bool" and the array node is unchanged.
    "boolean": "bool",
    "enum": "enum", "bitfield": "bitfield",
}

# the schema's `$defs`, for resolving `{$ref: "#/$defs/union/Name"}` (set by descriptor())
_ROOT = {}


def _resolve(o):
    """A `{$ref: "#/$defs/..."}` object becomes the definition it names; anything else is itself."""
    if isinstance(o, dict) and set(o) == {"$ref"}:
        node = _ROOT
        for part in o["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return node
    return o


def _field(name, spec):
    t = spec["type"]
    node = {"id": spec["id"], "name": name}
    if t in _SCALAR:
        node["kind"] = _SCALAR[t]
    elif t == "struct":
        node["kind"] = "struct"
        node["fields"] = _fields(spec["fields"])
    elif t == "union":
        # A union is a sequence carrying at most one child (MESSAGE_SPEC §4.2); the
        # present child's id selects the active `oneof` option, `default_id` applies
        # when none is set. An option may be any field type, so each is a normal field
        # node (recursing for a nested struct/union); string/blob options also carry
        # their maxlen, which the over-bound sweep needs and a scalar node never has.
        node.update(_union_node(spec))
    elif t == "array":
        node.update(_array_node(spec["items"]))
    else:
        raise ValueError(f"unhandled schema type {t!r} for field {name!r}")
    return node


def _union_node(spec):
    """The kind-specific part of a union node (a field's, or an array element's). `default_id`
    omitted means the lowest option id (the generator's rule); `oneof` may be a `$ref`."""
    options = _union_options(_resolve(spec["oneof"]))
    default_id = spec.get("default_id", min(o["id"] for o in options))
    return {"kind": "union", "default_id": default_id, "options": options}


def _array_node(it):
    """The kind-specific part of an array whose ELEMENT spec is `it`. `it.count` is this array's
    capacity; when the element is itself an array, ITS element spec is `it.items`."""
    et = it["type"]
    count = it.get("count", 0)
    if et in ("string", "blob"):            # a dynamic wrapper array (leaf elements)
        return {"kind": "wrapper", "elem": et, "count": count}
    if et == "struct":                       # a wrapper of composite (struct) elements
        # array-of-struct (§5.2): each element is itself a struct sequence. Modeled
        # as a `struct_wrapper` node carrying the element struct's field tree, so a
        # value walk can descend into every element's k/v (WP-05).
        return {"kind": "struct_wrapper", "count": count, "fields": _fields(it["fields"])}
    if et == "union":                        # an array of unions: each element holds ONE option
        return {"kind": "node_wrapper", "count": count, "item": _union_node(it)}
    if et == "array":                        # an array of arrays
        return {"kind": "node_wrapper", "count": count, "item": _array_node(it["items"])}
    return {"kind": "array", "elem": _SCALAR[et], "count": count}   # an inline numeric/fp array


def _fields(d):
    # ascending field id (the materialized form emits fields in id order)
    return [_field(n, s) for n, s in sorted(d.items(), key=lambda kv: kv[1]["id"])]


def _union_options(d):
    # the union options, in ascending option id (the id selects the active option)
    opts = []
    for n, s in sorted(d.items(), key=lambda kv: kv[1]["id"]):
        o = _field(n, s)
        if s["type"] in ("string", "blob"):
            o["maxlen"] = s.get("maxlen", 0)
        opts.append(o)
    return opts


def descriptor(path=SCHEMA):
    with open(path) as fh:
        y = yaml.safe_load(fh)
    _ROOT.clear()
    _ROOT.update({"$defs": y.get("$defs", {})})
    (mname, mspec), = y["messages"].items()   # the schema carries a single message
    return {"message": mname, "fields": _fields(mspec["payload"])}


def main():
    """schema.py [--json [OUT]] [--schema PATH]   (default schema: schema/probe.sofab.yaml)

    `--json` with no OUT writes oracle/materialized-schema.json; `--schema` picks the schema
    the descriptor is derived from. Without `--json` the descriptor goes to stdout."""
    args = sys.argv[1:]
    schema = SCHEMA
    if "--schema" in args:
        i = args.index("--schema")
        schema = args[i + 1]
        del args[i:i + 2]
    out = None
    if args and args[0] == "--json":
        out = args[1] if len(args) >= 2 else \
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "oracle", "materialized-schema.json")
    s = json.dumps(descriptor(schema), indent=2)
    if out:
        with open(out, "w") as fh:
            fh.write(s + "\n")
        sys.stderr.write(f"[schema] wrote {os.path.relpath(out)}\n")
    else:
        print(s)


if __name__ == "__main__":
    main()
