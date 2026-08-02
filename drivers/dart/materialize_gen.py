#!/usr/bin/env python3
"""Build-time generator for the Dart driver's materialized-value walker.

Reads the materialized schema descriptor (oracle/materialized-schema.json, the
same descriptor engine/structured/schema.py emits) and unrolls it into a
straight-line Dart source file implementing

    String materialize(Probe m)

that walks the decoded `Probe` value and prints the element-access oracle form
(oracle/materialized.md) byte-for-byte vs engine/structured/materialize.py.

Why generate straight-line source (the rust/cpp/zig camp, not go/ts/java/cs/py's
runtime reflection): the driver is AOT-compiled (`dart compile exe`), so
`dart:mirrors` is unavailable. The descriptor is unrolled here, at build time,
into explicit `m.nested.f32` / `m.arrays.u8[i]` / list-loop code. Dart field
names are the schema `name`s verbatim (verified against the generated
message.dart: m.nested.f32, m.arrays.u8, m.string_array, m.nested.bytes_field, …),
so a field's access path is just its ancestor names joined with '.'.

Dart type gotchas the leaf emitters handle (see oracle/materialized.md):
  * u64  — Dart `int` is signed 64-bit, so a value with the high bit set prints
           negative. `_u` reinterprets it as unsigned via BigInt (the issue's
           "u64 as JSON strings" concern, here in decimal).
  * fp32 — stored as a Dart `double`; repacked to the 32-bit IEEE pattern.
  * fp64 — emitted as two uint32 halves so `toRadixString(16)` never sees a
           negative int (which would prepend '-').

Descriptor shape (JSON): { "message": "probe", "fields": [node, ...] }
  node.kind: leaf u|s|fp32|fp64|string|blob
             struct  (+ fields[])
             array   (+ elem u|s|fp32|fp64, + count)   -> List<int>/List<double>, actual length
             wrapper (+ elem string|blob,  + count)    -> List<String>/List<Uint8List>, actual length

Usage: materialize_gen.py OUT.dart [SCHEMA_PATH]
       SOFAB_MATERIALIZE_SCHEMA overrides the descriptor path.
       A non-probe SCHEMA_PATH (union/limit suites) emits a compile-only stub —
       those suites do not use the materialized oracle.
"""
import json
import os
import sys

def _load_descriptor():
    env = os.environ.get("SOFAB_MATERIALIZE_SCHEMA")
    if env:
        path = env
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(here, "..", ".."))
        path = os.path.join(root, "oracle", "materialized-schema.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


class _Emitter:
    def __init__(self):
        self.lines = []
        self._loop = 0

    def stmt(self, s):
        self.lines.append("  " + s)

    def fresh(self):
        n = self._loop
        self._loop += 1
        return f"_i{n}"


def _emit_leaf(em, kind, expr):
    if kind == "u":
        em.stmt(f"b.write('u'); b.write(_u({expr}));")
    elif kind == "s":
        em.stmt(f"b.write('s'); b.write({expr}.toString());")
    elif kind == "fp32":
        # CORELIB_PLAN §6.5: Dart has no fp32 value type, so `expr` is already a widened
        # double and the widening SET the quiet bit — a signaling NaN cannot be recovered
        # from it. Since generator#275 the generated type parks the wire bits next to the
        # value as `<field>Fp32Bits` (public), which is the raw channel §6.5 requires a
        # double-only target to offer its bit-exact consumers. A materialized walk is one
        # of those, so read the bits and fall back to the double only when they are absent
        # (they are captured for NaN payloads only — every other value is lossless).
        em.stmt(f"_f32Scalar(b, {expr}, {expr}Fp32Bits);")
    elif kind == "fp64":
        em.stmt(f"_f64(b, {expr});")
    elif kind == "string":
        em.stmt(f"_bytes(b, 't', utf8.encode({expr}));")
    elif kind == "blob":
        em.stmt(f"_bytes(b, 'b', {expr});")
    else:
        raise ValueError(f"not a leaf kind: {kind!r}")


def _emit_array(em, elem, expr):
    # `count: N` numeric/fp array: emit exactly the elements the container holds.
    # `count` is a CAPACITY, not a length (MESSAGE_SPEC §3) — "a decoder materializes
    # exactly the M elements the wire carries … There is no fill-to-N" — so the
    # container's own length is the answer and padding to N would invent trailing
    # default elements the wire never carried. Same rule as the wrapper form below;
    # `count` now only bounds (M > N is INVALID, §7), it never restores a length.
    i = em.fresh()
    em.stmt("b.write('[');")
    em.stmt(f"for (var {i} = 0; {i} < {expr}.length; {i}++) {{")
    em.stmt(f"  if ({i} != 0) b.write(',');")
    if elem == "fp32":
        # CORELIB_PLAN §6.5: Dart has no fp32 value type, so reading an element out
        # of the list widens it to a double and the widening SETS the quiet bit,
        # destroying a signaling NaN. The container is a Float32List at runtime, so
        # its byte buffer still holds the exact wire bits — read those instead.
        _Indent(em, 1).stmt(f"_f32Elem(b, {expr}, {i});")
    else:
        _emit_leaf(_Indent(em, 1), elem, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt("b.write(']');")


def _emit_wrapper(em, elem, expr):
    # Wrapper array (string_array/blob_array): emit the container's actual
    # elements in index order — the length is itself the signal, no fill-to-N.
    i = em.fresh()
    em.stmt("b.write('[');")
    em.stmt(f"for (var {i} = 0; {i} < {expr}.length; {i}++) {{")
    em.stmt(f"  if ({i} != 0) b.write(',');")
    _emit_leaf(_Indent(em, 1), elem, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt("b.write(']');")


def _emit_struct(em, fields, expr):
    em.stmt("b.write('{');")
    for idx, child in enumerate(fields):
        sep = "" if idx == 0 else ";"
        em.stmt(f"b.write('{sep}{child['id']}:');")
        _emit_node(em, child, expr)
    em.stmt("b.write('}');")


def _emit_struct_wrapper(em, fields, expr):
    # struct_array (WP-05): elements are generated objects — an obj walk per
    # element via a struct scope rooted at the element expression; container
    # length as-is (like _emit_wrapper).
    i = em.fresh()
    em.stmt("b.write('[');")
    em.stmt(f"for (var {i} = 0; {i} < {expr}.length; {i}++) {{")
    em.stmt(f"  if ({i} != 0) b.write(',');")
    _emit_element_struct(em, fields, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt("b.write(']');")


def _emit_element_struct(em, fields, elem_expr):
    """_emit_struct, but rooted at an element expression instead of a field of a
    parent object (children access elem_expr.<name> via _emit_node)."""
    em.stmt("b.write('{');")
    for idx, child in enumerate(fields):
        sep = "" if idx == 0 else ";"
        em.stmt(f"b.write('{sep}{child['id']}:');")
        _emit_node(em, child, elem_expr)
    em.stmt("b.write('}');")


def _emit_node(em, node, parent_expr):
    kind = node["kind"]
    expr = f'{parent_expr}.{node["name"]}'
    if kind == "struct":
        _emit_struct(em, node["fields"], expr)
    elif kind == "array":
        _emit_array(em, node["elem"], expr)
    elif kind == "wrapper":
        _emit_wrapper(em, node["elem"], expr)
    elif kind == "struct_wrapper":
        _emit_struct_wrapper(em, node["fields"], expr)
    else:
        _emit_leaf(em, kind, expr)


class _Indent:
    """Wraps an emitter so nested leaf statements get extra indentation (cosmetic;
    the generated Dart is correct regardless of leading whitespace)."""

    def __init__(self, em, depth):
        self._em = em
        self._pad = "  " * depth

    def stmt(self, s):
        self._em.lines.append("  " + self._pad + s)

    def fresh(self):
        return self._em.fresh()


_PREAMBLE = '''// Code generated by materialize_gen.py from oracle/materialized-schema.json;
// DO NOT EDIT. Regenerated on every build.sh run — a schema change reshapes this
// walker with zero hand-editing. Implements the materialized-value oracle
// (oracle/materialized.md): a full walk of the decoded Probe, every field and
// every array element made explicit, byte-for-byte vs engine/structured/materialize.py.
import 'dart:convert';
import 'dart:typed_data';
import 'message.dart';

const _hex = '0123456789abcdef';

// Unsigned decimal of a possibly-negative Dart int (u64 with the high bit set is
// stored as a negative signed 64-bit int).
String _u(int v) =>
    v >= 0 ? v.toString() : (BigInt.from(v) + (BigInt.one << 64)).toString();

void _f32(StringBuffer b, double v) {
  final bd = ByteData(4);
  bd.setFloat32(0, v, Endian.big); // rounds the double to float32 (repack, §floats)
  b.write('f');
  b.write(bd.getUint32(0, Endian.big).toRadixString(16).padLeft(8, '0'));
}

// A scalar fp32 field, bit-exact (CORELIB_PLAN §6.5). `v` has already been widened to a
// double by the time it is a Dart value, so a signaling NaN is gone from it; `bits` is the
// generated type's raw-wire companion (`<field>Fp32Bits`, generator#275), captured on decode
// for a NaN payload. Absent bits mean the value is not a NaN and the repack is exact.
void _f32Scalar(StringBuffer b, double v, int? bits) {
  if (bits != null) {
    b.write('f');
    b.write((bits & 0xFFFFFFFF).toRadixString(16).padLeft(8, '0'));
    return;
  }
  _f32(b, v);
}

// One element of an fp32 array, bit-exact (CORELIB_PLAN §6.5). `_f32` above cannot
// be used here: its argument is already a widened double, and fp32 -> fp64 widening
// sets the quiet bit, so a signaling NaN is gone before the function is entered.
// A decoded fp32 array is a Float32List, whose byte buffer still holds the untouched
// little-endian wire bits; fall back to the repack only for a plain List<double>.
void _f32Elem(StringBuffer b, List<double> l, int i) {
  if (l is Float32List) {
    final u = l.buffer.asUint8List(l.offsetInBytes + i * 4, 4);
    final bits = u[0] | (u[1] << 8) | (u[2] << 16) | (u[3] << 24);
    b.write('f');
    b.write(bits.toRadixString(16).padLeft(8, '0'));
    return;
  }
  _f32(b, l[i]);
}

void _f64(StringBuffer b, double v) {
  final bd = ByteData(8);
  bd.setFloat64(0, v, Endian.big);
  b.write('F');
  // Two uint32 halves so toRadixString never sees a negative int.
  b.write(bd.getUint32(0, Endian.big).toRadixString(16).padLeft(8, '0'));
  b.write(bd.getUint32(4, Endian.big).toRadixString(16).padLeft(8, '0'));
}

void _bytes(StringBuffer b, String tag, List<int> s) {
  b.write(tag);
  b.write(s.length.toString());
  b.write(':');
  for (final x in s) {
    b.write(_hex[(x >> 4) & 0xf]);
    b.write(_hex[x & 0xf]);
  }
}

'''

_STUB = ('// Code generated by materialize_gen.py — compile-only stub (non-probe schema).\n'
         "import 'message.dart';\n\n"
         "String materialize(Probe m) => '';\n")


def generate(desc):
    em = _Emitter()
    _emit_struct(em, desc["fields"], "m")  # top level is the Probe struct off `m`
    body = "\n".join(em.lines)
    return (_PREAMBLE
            + "String materialize(Probe m) {\n"
            + "  final b = StringBuffer();\n"
            + body + "\n"
            + "  return b.toString();\n"
            + "}\n")


def main():
    out_path = sys.argv[1]
    schema = sys.argv[2] if len(sys.argv) >= 3 else "probe.sofab.yaml"
    if os.path.basename(schema) != "probe.sofab.yaml":
        src, path = _STUB, "stub (non-probe schema)"
    else:
        desc, path = _load_descriptor()
        src = generate(desc)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(src)
    sys.stderr.write(f"==> [dart] materialize walker generated from {path} -> {out_path}\n")


if __name__ == "__main__":
    main()
