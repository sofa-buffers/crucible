#!/usr/bin/env python3
"""Build-time generator for the Zig driver's materialized-value walker.

Reads the materialized schema descriptor (oracle/materialized-schema.json, the
same descriptor engine/structured/schema.py emits) and unrolls it into a
straight-line Zig source file implementing

    pub fn materialize(out: anytype, m: *const message.Probe) !void

that walks the decoded `message.Probe` value and prints the element-access
oracle form (oracle/materialized.md) byte-for-byte.

Why generate straight-line source instead of driving it at runtime: Zig 0.16
comptime field access needs field names known at compile time, and a runtime
descriptor can't drive `@field`/comptime reflection the way this form needs
(string vs blob are both []const u8, indistinguishable by type — only the
descriptor's `kind` separates them). So the descriptor is unrolled here, at
build time, into explicit `m.nested.f32` / `m.arrays.u8[0..]` / slice-loop code.

Descriptor shape (JSON): { "message": "probe", "fields": [node, ...] }
  node: id, name, kind
  kind: leaf u|s|fp32|fp64|string|blob
        struct  (+ fields[])
        array   (+ elem u|s|fp32|fp64, + count)   -> native [count]T
        wrapper (+ elem string|blob,  + count)    -> []const []const u8 slice

Zig field names are the schema `name`s verbatim (verified against the generated
message.zig: m.nested.f32, m.arrays.u8, m.string_array, bytes_field, ...), so a
field's access path is just its ancestor names joined with '.'.

Usage: materialize_gen.py [OUT.zig]
       SOFAB_MATERIALIZE_SCHEMA overrides the descriptor path.
"""
import json
import os
import sys


def _load_descriptor():
    """Resolve and load the descriptor: SOFAB_MATERIALIZE_SCHEMA env if set,
    else oracle/materialized-schema.json at the repo root (../.. from here)."""
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
    """Accumulates Zig statements, coalescing runs of literal output into one
    writeAll so the generated source stays readable and cheap."""

    def __init__(self):
        self.lines = []
        self._lit = []
        self._loop = 0  # unique loop-variable suffix, incremented per array/wrapper

    def lit(self, s):
        """Buffer a literal string to be written to `out` verbatim."""
        self._lit.append(s)

    def _flush(self):
        if self._lit:
            joined = "".join(self._lit)
            self._lit = []
            self.stmt(f'try out.writeAll("{_zig_str(joined)}");')

    def stmt(self, s):
        """Emit a raw Zig statement (flushing any pending literal first)."""
        self._flush()
        self.lines.append("    " + s)

    def raw(self, s):
        """Emit a raw Zig line at an explicit indent (flushes pending literal)."""
        self._flush()
        self.lines.append(s)

    def finish(self):
        self._flush()
        return "\n".join(self.lines)


def _zig_str(s):
    """Escape a Python string for a Zig string literal (only " and \\ occur here)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# --- leaf emitters: `expr` is the Zig value-access expression ------------------
def _emit_leaf(em, kind, expr):
    if kind == "u":
        em.stmt(f'try out.print("u{{d}}", .{{{expr}}});')
    elif kind == "s":
        em.stmt(f'try out.print("s{{d}}", .{{{expr}}});')
    elif kind == "fp32":
        em.stmt(f"try matFp32(out, {expr});")
    elif kind == "fp64":
        em.stmt(f"try matFp64(out, {expr});")
    elif kind == "string":
        em.stmt(f"try matBytes(out, 't', {expr});")
    elif kind == "blob":
        em.stmt(f"try matBytes(out, 'b', {expr});")
    else:
        raise ValueError(f"not a leaf kind: {kind!r}")


def _emit_array(em, elem, expr):
    """A fixed-count native array [count]T: iterate the slice, comma-separated."""
    n = em._loop
    em._loop += 1
    e, i = f"_e{n}", f"_i{n}"
    em.lit("[")
    em.raw(f"    for ({expr}[0..], 0..) |{e}, {i}| {{")
    em.raw(f'        if ({i} != 0) try out.writeAll(",");')
    # element emit at deeper indent
    saved = em.lines
    em.lines = []
    _emit_leaf(em, elem, e)
    body = ["    " + ln for ln in em.finish_body()]
    em.lines = saved
    for ln in body:
        em.raw(ln)
    em.raw("    }")
    em.lit("]")


def _emit_wrapper(em, elem, expr):
    """A wrapper array ([]const []const u8 slice): iterate directly."""
    n = em._loop
    em._loop += 1
    e, i = f"_e{n}", f"_i{n}"
    tag = "'t'" if elem == "string" else "'b'"
    em.lit("[")
    em.raw(f"    for ({expr}, 0..) |{e}, {i}| {{")
    em.raw(f'        if ({i} != 0) try out.writeAll(",");')
    em.raw(f"        try matBytes(out, {tag}, {e});")
    em.raw("    }")
    em.lit("]")


def _emit_struct(em, fields, expr):
    """A struct/message obj: {id:val;id:val;...} in the fields' listed order."""
    em.lit("{")
    for idx, child in enumerate(fields):
        sep = "" if idx == 0 else ";"
        em.lit(f'{sep}{child["id"]}:')
        _emit_node(em, child, expr)
    em.lit("}")


def _emit_node(em, node, parent_expr):
    """Walk one descriptor node, appending its access expression to parent_expr."""
    kind = node["kind"]
    expr = f'{parent_expr}.{node["name"]}'
    if kind == "struct":
        _emit_struct(em, node["fields"], expr)
    elif kind == "array":
        _emit_array(em, node["elem"], expr)
    elif kind == "wrapper":
        _emit_wrapper(em, node["elem"], expr)
    else:
        _emit_leaf(em, kind, expr)


# _Emitter helper used by _emit_array to grab its own buffered body
def _finish_body(self):
    self._flush()
    return self.lines


_Emitter.finish_body = _finish_body


def generate(desc):
    """Descriptor dict -> full Zig source string."""
    em = _Emitter()
    # Top level is a struct whose fields are desc["fields"], accessed off `m`.
    _emit_struct(em, desc["fields"], "m")
    body = em.finish()

    return f'''// Code generated by materialize_gen.py from oracle/materialized-schema.json;
// DO NOT EDIT. Regenerated on every build.sh run — a schema change reshapes this
// walker with zero hand-editing. Implements the materialized-value oracle
// (oracle/materialized.md): a full walk of the decoded Probe, every field and
// every array element made explicit, byte-for-byte vs engine/structured/materialize.py.
const std = @import("std");
const message = @import("message.zig");

fn matFp32(out: anytype, v: f32) !void {{
    const bits: u32 = @bitCast(v);
    try out.print("f{{x:0>8}}", .{{bits}});
}}
fn matFp64(out: anytype, v: f64) !void {{
    const bits: u64 = @bitCast(v);
    try out.print("F{{x:0>16}}", .{{bits}});
}}
fn matBytes(out: anytype, tag: u8, s: []const u8) !void {{
    try out.print("{{c}}{{d}}:", .{{ tag, s.len }});
    for (s) |b| try out.print("{{x:0>2}}", .{{b}});
}}

/// Walk the decoded `m` and emit its materialized-value form to `out`. String and
/// blob bytes borrow the input buffer (zero-copy decode), so this must run before
/// the per-record arena reset — the driver's accept path already guarantees that.
pub fn materialize(out: anytype, m: *const message.Probe) !void {{
{body}
}}
'''


def main():
    desc, path = _load_descriptor()
    src = generate(desc)
    if len(sys.argv) >= 2:
        out_path = sys.argv[1]
    else:
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "materialize_gen.zig")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(src)
    sys.stderr.write(f"==> [zig] materialize walker generated from {path} -> {out_path}\n")


if __name__ == "__main__":
    main()
