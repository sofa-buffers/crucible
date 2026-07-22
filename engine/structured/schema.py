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
  struct  { fields: [...] }        a nested struct/message scope
  array   { elem: u|s|fp32|fp64, count }   an inline fixed-count numeric/fp array
  wrapper { elem: string|blob, count }     a dynamic index-keyed element sequence

Usage: python3 engine/structured/schema.py [--json [out]]
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
}


def _field(name, spec):
    t = spec["type"]
    node = {"id": spec["id"], "name": name}
    if t in _SCALAR:
        node["kind"] = _SCALAR[t]
    elif t == "struct":
        node["kind"] = "struct"
        node["fields"] = _fields(spec["fields"])
    elif t == "array":
        it = spec["items"]
        et = it["type"]
        count = it.get("count", 0)
        if et in ("string", "blob"):        # a dynamic wrapper array
            node.update(kind="wrapper", elem=et, count=count)
        else:                                # an inline fixed-count numeric/fp array
            node.update(kind="array", elem=_SCALAR[et], count=count)
    else:
        raise ValueError(f"unhandled schema type {t!r} for field {name!r}")
    return node


def _fields(d):
    # ascending field id (the materialized form emits fields in id order)
    return [_field(n, s) for n, s in sorted(d.items(), key=lambda kv: kv[1]["id"])]


def descriptor(path=SCHEMA):
    with open(path) as fh:
        y = yaml.safe_load(fh)
    (mname, mspec), = y["messages"].items()   # the schema carries a single message
    return {"message": mname, "fields": _fields(mspec["payload"])}


def main():
    out = None
    if len(sys.argv) >= 2 and sys.argv[1] == "--json":
        out = sys.argv[2] if len(sys.argv) >= 3 else \
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "oracle", "materialized-schema.json")
    s = json.dumps(descriptor(), indent=2)
    if out:
        with open(out, "w") as fh:
            fh.write(s + "\n")
        sys.stderr.write(f"[schema] wrote {os.path.relpath(out)}\n")
    else:
        print(s)


if __name__ == "__main__":
    main()
