#!/usr/bin/env python3
"""Materialized-value reference — the ground truth for the element-access oracle
(oracle/materialized.md).

Given a `gen.py` message dict (the same value model the cross-encode corpus is built
from), produce the exact materialized-form dump a *correct* driver must emit under
`SOFAB_MATERIALIZE=1` after decoding that message's wire. Every driver's dump is
validated byte-for-byte against this reference.

It models the decoded value, not the source dict — i.e. `decode(encode(msg))`:
  * an array's length is **what the wire carried** — `count` is a capacity, not a
    length (MESSAGE_SPEC §3, documentation#31): a compact array materializes exactly
    its `M` wire elements with **no fill-to-N**, and a wrapper array materializes
    *highest present id + 1* elements, interior gaps restored as element defaults;
  * a scalar / fp / string / blob is its value or the type default.

Usage: python3 engine/structured/materialize.py            # dump every gen.py vector
       python3 engine/structured/materialize.py --check DIR # compare a driver's
                                                            # SOFAB_MATERIALIZE output in DIR
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import vectors  # noqa: E402
from schema import descriptor  # noqa: E402  (the generated schema-type table)

_DESC = descriptor()


def _array_counts(fields):
    cs = set()
    for f in fields:
        if f["kind"] in ("array", "wrapper"):
            cs.add(f["count"])
        elif f["kind"] == "struct":
            cs |= _array_counts(f["fields"])
    return cs


# The schema `count`s, kept for reference only: since documentation#31 `count` is a
# CAPACITY, so nothing here pads to it — an array materializes exactly what the wire
# carried (§3). Retained so a reader sees the bound this reference deliberately ignores.
ARRAY_CAPACITIES = _array_counts(_DESC["fields"])

# gen.py's message-dict key per schema field PATH — its value-vector naming
# convention, the one thing NOT derivable from the schema (gen.py names arrays.u8
# "au8", nested.f32 "f32", string_array "strarr", …). Everything structural — field
# ids, types, counts, nesting — comes from _DESC, so a schema *type/shape* change
# needs no edit here; only a genuinely new field that gen.py populates does.
_MSG_KEY = {
    ("u8",): "u8", ("i8",): "i8", ("u16",): "u16", ("i16",): "i16",
    ("u32",): "u32", ("i32",): "i32", ("u64",): "u64", ("i64",): "i64",
    ("nested", "f32"): "f32", ("nested", "f64"): "f64",
    ("nested", "str"): "str", ("nested", "bytes_field"): "blob",
    ("arrays", "u8"): "au8", ("arrays", "i8"): "ai8",
    ("arrays", "u16"): "au16", ("arrays", "i16"): "ai16",
    ("arrays", "u32"): "au32", ("arrays", "i32"): "ai32",
    ("arrays", "u64"): "au64", ("arrays", "i64"): "ai64",
    ("arrays", "nested", "fp32"): "afp32", ("arrays", "nested", "fp64"): "afp64",
    ("string_array",): "strarr", ("blob_array",): "blobarr",
    ("struct_array",): "structarr",
}


# --- value encoders (one per materialized-form leaf) -------------------------
def _u(v):    return f"u{v}"
def _s(v):    return f"s{v}"
def _f32(x):  # x is a Python float OR raw 4 bytes (an exact bit pattern, WP-06)
    bits = struct.unpack("<I", x)[0] if isinstance(x, bytes) else struct.unpack("<I", struct.pack("<f", x))[0]
    return "f%08x" % bits
def _f64(x):  # x is a Python float OR raw 8 bytes
    bits = struct.unpack("<Q", x)[0] if isinstance(x, bytes) else struct.unpack("<Q", struct.pack("<d", x))[0]
    return "F%016x" % bits
def _text(s): b = s.encode("utf-8"); return f"t{len(b)}:{b.hex()}"
def _blob(b): return f"b{len(b)}:{b.hex()}"
def _obj(fields): return "{" + ";".join(f"{i}:{v}" for i, v in fields) + "}"
def _arr(vals):   return "[" + ",".join(vals) + "]"


def _num_array(vals, signed):
    """A compact numeric array: exactly the elements the wire carried. `count` is a
    capacity, so there is no fill-to-N (§3) — `[1,2,3]` in a `count: 5` array is a
    three-element array, distinct from `[1,2,3,0,0]`."""
    enc = _s if signed else _u
    return _arr([enc(v) for v in vals])


def _fp_array(vals, enc):
    """As _num_array: the wire count is the length, no padding to the capacity."""
    return _arr([enc(v) for v in vals])


def _scalar_fp(v):
    """A scalar fp *field* (not an array element) is omitted on the wire when it
    equals its default — and -0.0 is falsy, so it is omitted too and decodes to +0.0
    (mirrors gen.py's emit condition; the round-trip can't distinguish ±0.0 either,
    canonical.md §Tradeoff). A nonzero value, ±inf, or NaN is emitted and preserved.
    Array *elements* are always emitted explicitly, so they are NOT normalized here."""
    if v or (v != v) or v in (float("inf"), float("-inf")):
        return v
    return 0.0


def _wrapper(items, leaf, empty):
    """A wrapper array (string_array/blob_array). The wire omits *interior* default
    elements and always writes the **last** one (§2), so the decoded length is the
    value's own length — interior gaps come back as the element default."""
    return _arr([leaf(v if v else empty) for v in items])


def _walk(node, msg, path):
    """One descriptor node → its materialized value string, pulling the source value
    from the gen.py msg via _MSG_KEY (structs recurse; the type/count come from node)."""
    kind = node["kind"]
    if kind == "struct":
        return _obj([(c["id"], _walk(c, msg, path + (c["name"],))) for c in node["fields"]])
    key = _MSG_KEY[path]
    if kind == "u":      return _u(msg.get(key, 0))
    if kind == "s":      return _s(msg.get(key, 0))
    if kind == "fp32":
        v = msg.get(key, 0.0)                       # raw bytes are explicit (no omit-normalize)
        return _f32(v if isinstance(v, bytes) else _scalar_fp(v))
    if kind == "fp64":
        v = msg.get(key, 0.0)
        return _f64(v if isinstance(v, bytes) else _scalar_fp(v))
    if kind == "string": return _text(msg.get(key, ""))
    if kind == "blob":   return _blob(msg.get(key, b""))
    if kind == "array":
        vals = msg.get(key, [])
        if node["elem"] in ("u", "s"):
            return _num_array(vals, node["elem"] == "s")
        return _fp_array(vals, _f32 if node["elem"] == "fp32" else _f64)
    if kind == "wrapper":
        items = msg.get(key, [])
        leaf, empty = (_text, "") if node["elem"] == "string" else (_blob, b"")
        return _wrapper(items, leaf, empty)
    if kind == "struct_wrapper":
        # struct_array (WP-05): elements are sequences; the same length rule as
        # _wrapper applies (§2/§5.1) — nothing trailing is elided.
        items = msg.get(key, [])
        # element leaf kinds, driven by the descriptor (schema-shape-agnostic); the
        # element dict keys are the schema field names (gen.py's convention). Same
        # length rule as _wrapper: interior all-default elements are gaps on the wire
        # and come back as all-default elements, the last one is always written.
        fmts = {"u": (_u, 0), "s": (_s, 0), "string": (_text, ""), "blob": (_blob, b"")}
        return _arr([
            _obj([(c["id"], fmts[c["kind"]][0](e.get(c["name"], fmts[c["kind"]][1])))
                  for c in node["fields"]])
            for e in items])
    raise ValueError(f"unhandled kind {kind!r}")


def materialize(msg):
    """The materialized-form value string (no 'A ' prefix) for a gen.py msg, driven by
    the generated schema descriptor (engine/structured/schema.py) — no hardcoded shape."""
    return _obj([(f["id"], _walk(f, msg, (f["name"],))) for f in _DESC["fields"]])


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        _check(sys.argv[2])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--driver":
        _check_driver(sys.argv[2])
        return
    for i, (name, msg) in enumerate(vectors()):
        print(f"{i:03d}_{name}\tA {materialize(msg)}")


def _check_driver(driver_bin):
    """Run a driver binary with SOFAB_MATERIALIZE=1 over corpus/structured and diff
    every line against the reference. This is the per-driver acceptance gate for the
    materialized rollout: 0 mismatches == the driver reproduces the form exactly."""
    import struct
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cdir = os.path.join(root, "corpus", "structured")
    files = sorted(f for f in os.listdir(cdir) if f.endswith(".bin"))
    stream = b""
    for f in files:
        d = open(os.path.join(cdir, f), "rb").read()
        stream += struct.pack("<I", len(d)) + d
    schema_json = os.path.join(root, "oracle", "materialized-schema.json")
    env = {**os.environ, "SOFAB_MATERIALIZE": "1", "SOFAB_MATERIALIZE_SCHEMA": schema_json}
    out = subprocess.run([driver_bin], input=stream, capture_output=True, env=env)
    lines = out.stdout.decode("utf-8", "replace").splitlines()
    vecs = vectors()
    if len(lines) != len(vecs):
        print(f"FAIL: driver emitted {len(lines)} lines for {len(vecs)} inputs")
        if out.stderr:
            print("  stderr:", out.stderr.decode("utf-8", "replace")[-400:])
        sys.exit(1)
    bad = 0
    for i, (name, msg) in enumerate(vecs):
        exp = "A " + materialize(msg)
        if lines[i] != exp:
            bad += 1
            if bad <= 6:
                print(f"MISMATCH {i:03d}_{name}\n  ref: {exp}\n  got: {lines[i]}")
    print(f"\n{'OK' if not bad else 'FAIL'}: {bad}/{len(vecs)} mismatch(es) — {driver_bin}")
    sys.exit(1 if bad else 0)


def _check(driver_out_dir):
    """Compare a driver's SOFAB_MATERIALIZE dump (one file `NNN_name` per vector,
    holding its `A <dump>` line) against the reference. Reports mismatches."""
    bad = 0
    for i, (name, msg) in enumerate(vectors()):
        expected = "A " + materialize(msg)
        path = os.path.join(driver_out_dir, f"{i:03d}_{name}")
        if not os.path.exists(path):
            print(f"MISSING {i:03d}_{name}"); bad += 1; continue
        got = open(path).read().strip()
        if got != expected:
            print(f"MISMATCH {i:03d}_{name}\n  ref: {expected}\n  got: {got}"); bad += 1
    print(f"\n{'OK' if not bad else 'FAIL'}: {bad} mismatch(es) of {len(vectors())} vectors")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
