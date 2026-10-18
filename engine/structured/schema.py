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
                                   An `enum` / `bitfield` scalar node carries `default: <int>` when
                                   its declared default is non-zero. That key is REFERENCE-ONLY
                                   (engine/structured/materialize.py, the generators of vectors):
                                   a walker never reads it — it prints the value the generated code
                                   decoded, and an absent field decodes to its default by itself
  array   { elem: u|s|bool|enum|bitfield|fp32|fp64, count }
                                   an inline fixed-count compact array; `enum` and `bitfield`
                                   elements are a compact signed / unsigned array (MESSAGE_SPEC §3)
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


# --- the declared width of an enum / bitfield (MESSAGE_SPEC §1, §7.1) ----------------------
# The ONE place in Crucible that derives it. An `enum` is bounded by the smallest SIGNED type
# holding every declared constant ("signed whatever the constants are", §1); a `bitfield` by the
# smallest UNSIGNED type holding its highest declared `pos` — never by the set of constants or
# the mask the flags form.

def _deref(o, root):
    """`{ $ref: "#/$defs/<cat>/<Name>" }` resolved against the loaded YAML `root`; else `o`."""
    if isinstance(o, dict) and set(o) == {"$ref"}:
        node = root
        for part in o["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return node
    return o


def enum_values(spec, root):
    """The declared constants of an enum field / array `items` spec (`KEY: int` or
    `KEY: {value: int}`, generator schema README)."""
    consts = _deref(spec["enum"], root)
    return [c["value"] if isinstance(c, dict) else c for c in consts.values()]


def bitfield_flags(spec, root):
    """The declared flags of a bitfield field / array `items` spec: {name: {pos, default?}}."""
    return _deref(spec["bits"], root)


def declared_width(spec, root):
    """`i8`..`i64` for an enum, `u8`..`u64` for a bitfield (field spec or array `items` spec)."""
    t = spec["type"]
    for w in (8, 16, 32, 64):
        if t == "enum":
            vals = enum_values(spec, root)
            if -(1 << (w - 1)) <= min(vals) and max(vals) <= (1 << (w - 1)) - 1:
                return f"i{w}"
        elif t == "bitfield":
            if max(f["pos"] for f in bitfield_flags(spec, root).values()) < w:
                return f"u{w}"
        else:
            raise ValueError(f"declared_width: {t!r} is neither an enum nor a bitfield")
    raise ValueError(f"declared_width: no width holds {spec!r}")


def declared_default(spec, root):
    """The decoded value of an absent enum / bitfield field (§2): an enum field's `default`, a
    bitfield's flags with `default: true` folded into the mask; 0 when none is declared."""
    if spec["type"] == "enum":
        return int(spec.get("default", 0))
    if spec["type"] == "bitfield":
        return sum(1 << f["pos"] for f in bitfield_flags(spec, root).values()
                   if isinstance(f, dict) and f.get("default"))
    raise ValueError(f"declared_default: {spec['type']!r} is neither an enum nor a bitfield")


def _field(name, spec):
    t = spec["type"]
    node = {"id": spec["id"], "name": name}
    if t in _SCALAR:
        node["kind"] = _SCALAR[t]
        if t in ("enum", "bitfield"):
            d = declared_default(spec, _ROOT)
            if d:
                node["default"] = d   # reference-only (see the module docstring)
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


def _dereference(node, path, depth=0):
    """Every `{$ref}` below `node` replaced by what it points at — a `$defs` body, a whole
    field, a whole payload, or a definition in another file (`file.yaml#/...`, relative to the
    file the `$ref` is written in). A `$ref` names nothing the wire carries, so the descriptor
    of a schema is the descriptor of its dereferenced form (schema/probe-ref.sofab.yaml and its
    inline twin give one and the same table)."""
    if depth > 64:
        raise ValueError(f"{path}: $ref cycle")
    if isinstance(node, dict) and set(node) == {"$ref"}:
        f, _, ptr = node["$ref"].partition("#")
        src = os.path.join(os.path.dirname(path), f) if f else path
        with open(src) as fh:
            target = yaml.safe_load(fh)
        for part in ptr.strip("/").split("/"):
            target = target[part]
        return _dereference(target, src, depth + 1)
    if isinstance(node, dict):
        return {k: _dereference(v, path, depth) for k, v in node.items()}
    if isinstance(node, list):
        return [_dereference(v, path, depth) for v in node]
    return node


def descriptor(path=SCHEMA):
    with open(path) as fh:
        y = yaml.safe_load(fh)
    _ROOT.clear()
    _ROOT.update({"$defs": y.get("$defs", {})})
    (mname, mspec), = _dereference(y["messages"], path).items()   # the schema carries a single message
    return {"message": mname, "fields": _fields(mspec["payload"])}


def annotate_types(desc, path, sofabgen=None):
    """Mark every union node of `desc` with the generated type it decodes into, as sofabgen's
    IR states it: `"ir_type": {"path": [...], "variant": <default option> or null}`.

    A union's generated type name is not derivable from its position once `$ref` is involved: a
    `$defs` union is named after the def, split into one type per effective default_id, and an
    alias def is a type of its own (schema/probe-ref.sofab.yaml has all three). The generated
    walkers (cpp, dart, kotlin, rust, zig) spell a union's type name; they take it from here when
    it is present. The descriptor is walked in step with `sofabgen --dump-ir`, matched by id."""
    import subprocess
    tool = sofabgen or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "sofabgen")
    ir = json.loads(subprocess.run([tool, "--dump-ir", "--in", path], check=True,
                                   capture_output=True, text=True).stdout)
    named = {n["key"]: n for n in ir.get("named") or []}

    def walk(node, irf):
        kind = node.get("kind")
        if kind in ("struct", "union"):
            nt = named.get(irf.get("ref"))
            if nt is None:
                return
            if kind == "union":
                node["ir_type"] = {"path": nt["path"], "variant": nt.get("variant")}
            by_id = {f["id"]: f for f in nt.get("fields") or []}
            for child in node.get("fields") or node.get("options") or []:
                if child["id"] in by_id:
                    walk(child, by_id[child["id"]])
        elif kind == "struct_wrapper":
            walk({"kind": "struct", "fields": node["fields"]}, {"ref": irf.get("elem_ref")})
        elif kind == "node_wrapper":
            if "elem_items" in irf:
                walk(node["item"], dict(irf["elem_items"], kind="array"))
            else:
                walk(node["item"], {"ref": irf.get("elem_ref")})

    (msg,) = ir["messages"]
    by_id = {f["id"]: f for f in msg["fields"]}
    for f in desc["fields"]:
        if f["id"] in by_id:
            walk(f, by_id[f["id"]])
    return desc


def main():
    """schema.py [--json [OUT]] [--schema PATH] [--types]   (default schema: schema/probe.sofab.yaml)

    `--json` with no OUT writes oracle/materialized-schema.json; `--schema` picks the schema
    the descriptor is derived from; `--types` adds each union's generated type
    (`annotate_types`, needs tools/sofabgen). Without `--json` the descriptor goes to stdout."""
    args = sys.argv[1:]
    schema = SCHEMA
    if "--schema" in args:
        i = args.index("--schema")
        schema = args[i + 1]
        del args[i:i + 2]
    types = "--types" in args
    if types:
        args.remove("--types")
    out = None
    if args and args[0] == "--json":
        out = args[1] if len(args) >= 2 else \
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "oracle", "materialized-schema.json")
    desc = descriptor(schema)
    if types:
        annotate_types(desc, schema)
    s = json.dumps(desc, indent=2)
    if out:
        with open(out, "w") as fh:
            fh.write(s + "\n")
        sys.stderr.write(f"[schema] wrote {os.path.relpath(out)}\n")
    else:
        print(s)


if __name__ == "__main__":
    main()
