// Crucible TypeScript driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-ts code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// build.sh bundles this + the generated message.ts + corelib-ts SOURCE into one
// CJS file via esbuild (aliasing @sofa-buffers/corelib to the corelib's
// src/index.ts), so the run needs no separate corelib build and does not depend
// on the corelib's committed dist.
//
// Like Python/Java (and unlike Rust/C++), the generated TS decode throws on
// non-COMPLETE input (SofabError), so the verdict is a plain try/catch. The
// one-shot Probe.decode path (MESSAGE_SPEC §7) throws a SofabError whose .code
// distinguishes the two non-COMPLETE outcomes: Incomplete (truncation — decode
// ended mid-field, not an error → canonical "I") vs InvalidMsg (malformed →
// "R invalid_msg"). COMPLETE returns normally (→ "A <hex>").
import { readFileSync } from "node:fs";

import { Probe } from "./message";
import { OStream, SofabError, SofabErrorCode } from "@sofa-buffers/corelib";

// --- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 -------
// Instead of "A <hex(re-encode)>", emit "A <dump(decoded value)>": every field and
// array element made explicit. The generated Probe carries no schema type tag
// (fp32 vs fp64, unsigned vs signed) and no struct/array shape, so the walk is
// driven by the GENERATED schema descriptor (engine/structured/schema.py, committed
// as oracle/materialized-schema.json) loaded at runtime — the same generic source
// the C driver uses. Only leaf FORMATTING stays type-specific: fp32 is a JS double
// at rest and MUST be repacked through Float32 to recover its 32-bit pattern
// (canonical.md NaN-payload caveat applies); string byte length uses UTF-8 bytes.
const _MATERIALIZE = process.env.SOFAB_MATERIALIZE === "1";

// Descriptor node shapes (oracle/materialized-schema.json). Leaves carry only a
// kind; struct carries child fields; array/wrapper carry an element type + count.
interface SchemaNode {
  id: number;
  name: string;
  kind: "u" | "s" | "fp32" | "fp64" | "string" | "blob" | "struct" | "array" | "wrapper";
  fields?: SchemaNode[];
  elem?: "u" | "s" | "fp32" | "fp64" | "string" | "blob";
  count?: number;
}
interface SchemaDescriptor { message: string; fields: SchemaNode[]; }

// Loaded once at startup, only in materialize mode (the default/round-trip path
// never touches the schema — it stays schema-agnostic).
const _DESC: SchemaDescriptor | null = _MATERIALIZE
  ? (JSON.parse(readFileSync(
      process.env.SOFAB_MATERIALIZE_SCHEMA ?? "oracle/materialized-schema.json",
      "utf8",
    )) as SchemaDescriptor)
  : null;

function _hex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}
function _f32(x: number): string {
  const buf = new ArrayBuffer(4);
  new DataView(buf).setFloat32(0, x);
  return "f" + new DataView(buf).getUint32(0).toString(16).padStart(8, "0");
}
function _f64(x: number): string {
  const buf = new ArrayBuffer(8);
  new DataView(buf).setFloat64(0, x);
  return "F" + new DataView(buf).getBigUint64(0).toString(16).padStart(16, "0");
}
function _t(s: string): string {
  const b = Buffer.from(s, "utf-8");
  return "t" + b.length + ":" + b.toString("hex");
}
function _b(bytes: Uint8Array): string {
  return "b" + bytes.length + ":" + _hex(bytes);
}

// The one schema-specific piece: format a single leaf value per its kind. Reused for
// both scalar leaves and array/wrapper elements (the descriptor's `elem` is a leaf
// kind). u/s are number|bigint (bigint for 64-bit) → decimal via toString().
function formatLeaf(kind: string, v: unknown): string {
  switch (kind) {
    case "u": return "u" + (v as number | bigint).toString();
    case "s": return "s" + (v as number | bigint).toString();
    case "fp32": return _f32(v as number);
    case "fp64": return _f64(v as number);
    case "string": return _t(v as string);
    case "blob": return _b(v as Uint8Array);
    default: throw new Error("unhandled leaf kind " + kind);
  }
}

// Generic recursive walk: descriptor node + the corresponding in-memory value → the
// materialized-form string. No schema shape is baked in here — structs, arrays, and
// wrappers are all discovered from the node.
function walk(node: SchemaNode, value: unknown): string {
  switch (node.kind) {
    case "struct": {
      const v = value as Record<string, unknown>;
      return "{" + node.fields!.map((c) => c.id + ":" + walk(c, v[c.name])).join(";") + "}";
    }
    case "array":
    case "wrapper":
      // array: numeric/fp materialized to N in memory; wrapper: index order,
      // container length is the signal. Both just map over the in-memory elements.
      return "[" + (value as unknown[]).map((el) => formatLeaf(node.elem!, el)).join(",") + "]";
    default:
      return formatLeaf(node.kind, value);
  }
}

function materialize(m: Probe): string {
  const d = _DESC!;
  const v = m as unknown as Record<string, unknown>;
  return "{" + d.fields.map((c) => c.id + ":" + walk(c, v[c.name])).join(";") + "}";
}

function rejectClass(e: unknown): string {
  // Coarse in Phase 2 (reject-class comparison is soft per policy). A SofabError
  // is a decode-level failure; anything else is surfaced as "other" rather than
  // hidden.
  return e instanceof SofabError ? "invalid_msg" : "other";
}

function canonical(data: Uint8Array): string {
  // decode -> re-encode -> hex (oracle/canonical.md). The generated TS message
  // has no encode(), so marshal into an in-memory OStream and read its bytes.
  let m: Probe;
  try {
    m = Probe.decode(data);
  } catch (e) {
    // INCOMPLETE (truncation) is a distinct hard verdict, not a reject: the
    // stream ended inside a field. Detect it first (canonical.md: never collapse
    // it into A or R). The optional partial-value hex payload is not emitted —
    // the throwing one-shot path yields no partial value, and the payload axis is
    // soft in Phase 2.
    if (e instanceof SofabError && e.code === SofabErrorCode.Incomplete) {
      return "I";
    }
    if (e instanceof SofabError && e.code === SofabErrorCode.LimitExceeded) {
      // LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
      // cap on a schema-unbounded field. A policy rejection distinct from INVALID —
      // its own verdict `L`, not `R`.
      return "L";
    }
    return "R " + rejectClass(e);
  }
  // COMPLETE decode. In materialize mode, dump the decoded value (oracle/
  // materialized.md) instead of the re-encoded wire hex; the default path is
  // unchanged.
  if (_MATERIALIZE) {
    return "A " + materialize(m);
  }
  const os = new OStream();
  m.marshal(os);
  const bytes = os.bytes();
  const hex = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return "A " + hex;
}

function main(): void {
  const input = readFileSync(0); // whole stdin (comparator writes all frames, then EOF)
  const lines: string[] = [];
  let off = 0;
  while (off + 4 <= input.length) {
    const n = input.readUInt32LE(off);
    off += 4;
    if (off + n > input.length) {
      process.stderr.write("crucible-ts: short payload\n");
      process.exit(1);
    }
    lines.push(canonical(input.subarray(off, off + n)));
    off += n;
  }
  process.stdout.write(lines.length ? lines.join("\n") + "\n" : "");
}

main();
