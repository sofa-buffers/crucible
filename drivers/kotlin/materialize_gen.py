#!/usr/bin/env python3
"""Build-time generator for the Kotlin driver's materialized-value walker.

Reads the materialized schema descriptor (oracle/materialized-schema.json, the
same descriptor engine/structured/schema.py emits) and unrolls it into a
straight-line Kotlin source file implementing

    fun materialize(m: Probe): String

that walks the decoded `Probe` value and prints the element-access oracle form
(oracle/materialized.md) byte-for-byte vs engine/structured/materialize.py.

Why generate straight-line source (the rust/cpp/zig/dart camp, not go/ts/java/cs/py's
runtime reflection): the driver is compiled once per KMP target, and only the JVM
target has reflection at all — `kotlin-reflect` is JVM-only and Kotlin/Native has no
property reflection. A runtime walk would therefore need one implementation per
target, which is precisely what having one shared driver.kt is meant to avoid. The
descriptor is unrolled here instead, at build time, into explicit `m.nested.f32` /
`m.arrays.u8[i]` / list-loop code that compiles on every target.

Kotlin field names are the schema `name`s verbatim (verified against the generated
message classes: m.nested.f32, m.arrays.u8, m.string_array, m.nested.bytes_field, …),
so a field's access path is its ancestor names joined with '.'.

Kotlin type notes the leaf emitters rely on (see oracle/materialized.md):
  * u    — the generated field is a Kotlin UNSIGNED type (UByte/UShort/UInt/ULong,
           and UByteArray/… for array elements), whose toString() is already the
           unsigned decimal. No masking or BigInteger detour is needed, unlike the
           signed-storage ports.
  * fp32 — a real Kotlin Float, so Float.toRawBits() is the exact wire pattern:
           nothing widened it through a double, so a signalling NaN survives and no
           `<field>Fp32Bits` companion channel (generator#275, the Dart case) is
           involved.
  * fp64 — Double.toRawBits(), printed as 16 hex digits via toULong() so the sign
           bit never renders as a leading '-'.
  * text — the String's UTF-8 bytes, i.e. encodeToByteArray().

Descriptor shape (JSON): { "message": "probe", "fields": [node, ...] }
  node.kind: leaf u|s|fp32|fp64|string|blob
             struct         (+ fields[])
             array          (+ elem u|s|fp32|fp64, + count)  -> UByteArray/IntArray/…
             wrapper        (+ elem string|blob,  + count)   -> MutableList<String|ByteArray>
             struct_wrapper (+ fields[])                     -> MutableList<generated>

Usage: materialize_gen.py OUT.kt [SCHEMA_PATH]
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
        self.lines.append("    " + s)

    def fresh(self):
        n = self._loop
        self._loop += 1
        return f"_i{n}"


class _Indent:
    """Wraps an emitter so nested leaf statements get extra indentation (cosmetic;
    the generated Kotlin is correct regardless of leading whitespace)."""

    def __init__(self, em, depth):
        self._em = em
        self._pad = "    " * depth

    def stmt(self, s):
        self._em.lines.append("    " + self._pad + s)

    def fresh(self):
        return self._em.fresh()


def _emit_leaf(em, kind, expr):
    if kind == "u":
        # The generated type is unsigned, so toString() is the unsigned decimal.
        em.stmt(f'b.append("u").append({expr}.toString())')
    elif kind == "s":
        em.stmt(f'b.append("s").append({expr}.toString())')
    elif kind == "fp32":
        em.stmt(f"_f32(b, {expr})")
    elif kind == "fp64":
        em.stmt(f"_f64(b, {expr})")
    elif kind == "string":
        em.stmt(f"_bytes(b, 't', {expr}.encodeToByteArray())")
    elif kind == "blob":
        em.stmt(f"_bytes(b, 'b', {expr})")
    else:
        raise ValueError(f"not a leaf kind: {kind!r}")


def _emit_array(em, elem, expr):
    # `count: N` numeric/fp array: emit exactly the elements the container holds.
    # `count` is a CAPACITY, not a length (MESSAGE_SPEC §3) — "a decoder materializes
    # exactly the M elements the wire carries … There is no fill-to-N" — so the
    # container's own length is the answer and padding to N would invent trailing
    # default elements the wire never carried. Same rule as the wrapper form below.
    i = em.fresh()
    em.stmt('b.append("[")')
    em.stmt(f"for ({i} in 0 until {expr}.size) {{")
    em.stmt(f'    if ({i} != 0) b.append(",")')
    _emit_leaf(_Indent(em, 1), elem, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt('b.append("]")')


def _emit_wrapper(em, elem, expr):
    # Wrapper array (string_array/blob_array): emit the container's actual elements
    # in index order — the length is itself the signal, no fill-to-N.
    i = em.fresh()
    em.stmt('b.append("[")')
    em.stmt(f"for ({i} in 0 until {expr}.size) {{")
    em.stmt(f'    if ({i} != 0) b.append(",")')
    _emit_leaf(_Indent(em, 1), elem, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt('b.append("]")')


def _emit_struct(em, fields, expr):
    em.stmt('b.append("{")')
    for idx, child in enumerate(fields):
        sep = "" if idx == 0 else ";"
        em.stmt(f'b.append("{sep}{child["id"]}:")')
        _emit_node(em, child, expr)
    em.stmt('b.append("}")')


def _emit_element_struct(em, fields, elem_expr):
    """_emit_struct, but rooted at an element expression instead of a field of a
    parent object (children access elem_expr.<name> via _emit_node)."""
    em.stmt('b.append("{")')
    for idx, child in enumerate(fields):
        sep = "" if idx == 0 else ";"
        em.stmt(f'b.append("{sep}{child["id"]}:")')
        _emit_node(em, child, elem_expr)
    em.stmt('b.append("}")')


def _emit_struct_wrapper(em, fields, expr):
    # struct_array (WP-05): elements are generated objects — an obj walk per element
    # via a struct scope rooted at the element expression; container length as-is.
    i = em.fresh()
    em.stmt('b.append("[")')
    em.stmt(f"for ({i} in 0 until {expr}.size) {{")
    em.stmt(f'    if ({i} != 0) b.append(",")')
    _emit_element_struct(_Indent(em, 1), fields, f"{expr}[{i}]")
    em.stmt("}")
    em.stmt('b.append("]")')


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


_PREAMBLE = '''// Code generated by materialize_gen.py from oracle/materialized-schema.json;
// DO NOT EDIT. Regenerated on every build.sh run — a schema change reshapes this
// walker with zero hand-editing. Implements the materialized-value oracle
// (oracle/materialized.md): a full walk of the decoded Probe, every field and
// every array element made explicit, byte-for-byte vs engine/structured/materialize.py.
//
// Target-agnostic Kotlin: it compiles unchanged for every KMP target the driver is
// built for, which is why it is generated rather than reflected (Kotlin has no
// property reflection outside the JVM).
@file:OptIn(ExperimentalUnsignedTypes::class)
@file:Suppress("RedundantVisibilityModifier", "unused")

package crucible

import message.Probe

private const val _HEX = "0123456789abcdef"

// fp32: the raw IEEE-754 pattern. A Kotlin Float is a true 32-bit float, so nothing
// widened it through a double and a signalling NaN payload reaches here intact.
private fun _f32(b: StringBuilder, v: Float) {
    b.append('f')
    b.append(v.toRawBits().toUInt().toString(16).padStart(8, '0'))
}

// fp64: as above, 16 hex digits. Via toULong() so the sign bit never renders as '-'.
private fun _f64(b: StringBuilder, v: Double) {
    b.append('F')
    b.append(v.toRawBits().toULong().toString(16).padStart(16, '0'))
}

private fun _bytes(b: StringBuilder, tag: Char, s: ByteArray) {
    b.append(tag).append(s.size.toString()).append(':')
    for (x in s) {
        val v = x.toInt() and 0xff
        b.append(_HEX[v ushr 4]).append(_HEX[v and 0xf])
    }
}

'''

_STUB = (
    "// Code generated by materialize_gen.py — compile-only stub (non-probe schema).\n"
    "package crucible\n\n"
    "import message.Probe\n\n"
    'internal fun materialize(m: Probe): String = ""\n'
)


def generate(desc):
    em = _Emitter()
    _emit_struct(em, desc["fields"], "m")  # top level is the Probe struct off `m`
    body = "\n".join(em.lines)
    return (
        _PREAMBLE
        + "internal fun materialize(m: Probe): String {\n"
        + "    val b = StringBuilder()\n"
        + body
        + "\n    return b.toString()\n"
        + "}\n"
    )


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
    sys.stderr.write(f"==> [kotlin] materialize walker generated from {path} -> {out_path}\n")


if __name__ == "__main__":
    main()
