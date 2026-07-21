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
// (fp32 vs fp64, unsigned vs signed), so this walker holds a small schema-type
// table (mirrors the Python/C drivers). fp32 is a JS double at rest and MUST be
// repacked through Float32 to recover its 32-bit pattern (canonical.md NaN-payload
// caveat applies); string byte length uses UTF-8 bytes via Buffer.
const _MATERIALIZE = process.env.SOFAB_MATERIALIZE === "1";
const _SCALARS: Array<[number, string, boolean]> = [
  [0, "u8", false], [1, "i8", true], [2, "u16", false], [3, "i16", true],
  [4, "u32", false], [5, "i32", true], [6, "u64", false], [7, "i64", true],
];

function _u(v: number | bigint): string { return "u" + v.toString(); }
function _s(v: number | bigint): string { return "s" + v.toString(); }
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
function _arr(vals: string[]): string { return "[" + vals.join(",") + "]"; }

function materialize(m: Probe): string {
  const f: string[] = [];
  for (const [fid, name, signed] of _SCALARS) {
    const v = (m as unknown as Record<string, number | bigint>)[name];
    f.push(`${fid}:${(signed ? _s : _u)(v)}`);
  }
  const n = m.nested;
  f.push("10:{" + [`0:${_f32(n.f32)}`, `1:${_f64(n.f64)}`,
    `2:${_t(n.str)}`, `3:${_b(n.bytes_field)}`].join(";") + "}");
  const a = m.arrays;
  const af: string[] = [];
  for (const [fid, name, signed] of _SCALARS) {
    const arr = (a as unknown as Record<string, Array<number | bigint>>)[name];
    af.push(`${fid}:` + _arr(arr.map((x) => (signed ? _s : _u)(x))));
  }
  af.push("10:{" + ["0:" + _arr(a.nested.fp32.map((x) => _f32(x))),
    "1:" + _arr(a.nested.fp64.map((x) => _f64(x)))].join(";") + "}");
  f.push("100:{" + af.join(";") + "}");
  f.push("200:" + _arr(m.string_array.map((s) => _t(s))));
  f.push("201:" + _arr(m.blob_array.map((bb) => _b(bb))));
  return "{" + f.join(";") + "}";
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
