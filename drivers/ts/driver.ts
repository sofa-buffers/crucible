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

import { Probe, ProbeDecoder } from "./message";
import { DecodeStatus, OStream, SofabError, SofabErrorCode } from "@sofa-buffers/corelib";

// --- the streaming axes (drivers/common/CONTRACT.md, "The streaming axes") --------
//
// The replay protocol hands each record over whole and re-encodes it with one call, so
// neither streaming surface of the generated API is reachable through it. Five
// environment variables open them; unset, each is today's behaviour byte for byte.
//
// TypeScript is where crucible#132 found three bugs while building the chunked decoder
// — a visitor callback that was simply not implemented (an unimplemented optional
// callback is a NO-OP in TS, so the field silently vanished), and two more — none of
// which crashed, failed to compile, or turned the conformance suite red. That is the
// class of defect this axis exists for.
//
// This backend has ONE encode surface: `serialize(os)`. There is no `encode()` and no
// `encodeTo()`, so `SOFAB_ENCODE=new|to` must be a hard error rather than a fallback —
// reporting a mode as passing that never ran is the failure the encode gate exists to
// prevent (meta: encode_surfaces=stream).
const _num = (name: string): number => {
  const v = process.env[name];
  return v ? parseInt(v, 10) || 0 : 0;
};
const _SPLIT = _num("SOFAB_SPLIT");
const _CHUNK = _num("SOFAB_CHUNK");
const _FLUSH = _num("SOFAB_FLUSH");
const _SCRUB = !!process.env.SOFAB_CHUNK_SCRUB && process.env.SOFAB_CHUNK_SCRUB !== "0";
const _ENCODE = process.env.SOFAB_ENCODE ?? "";
if (_ENCODE && _ENCODE !== "stream") {
  process.stderr.write(
    `crucible-ts: SOFAB_ENCODE=${_ENCODE} — this backend has only 'stream' ` +
      `(no encode(), no encodeTo())\n`,
  );
  process.exit(2);
}
// Announce the configuration on stderr (never parsed). Without it a driver that
// silently ignored the variables would be indistinguishable from one that honours
// them — identical stdout either way — which is the vacuous pass the gate's opt-in
// roster guards against. This is the same guard at the driver level.
if (_SPLIT || _CHUNK || _SCRUB || _FLUSH || _ENCODE) {
  process.stderr.write(
    `crucible-ts: streaming cfg split=${_SPLIT} chunk=${_CHUNK} ` +
      `scrub=${_SCRUB ? 1 : 0} enc=${_ENCODE || "stream"} flush=${_FLUSH}\n`,
  );
}

// How the record is cut on its way into the decoder. Never an empty chunk: k<=0,
// k>=len and n>=len all mean one chunk holding the whole record. A zero-length record
// yields no chunks and is not fed at all.
function chunksOf(data: Uint8Array): Uint8Array[] {
  const len = data.length;
  if (len === 0) return [];
  if (_CHUNK > 0) {
    const out: Uint8Array[] = [];
    for (let o = 0; o < len; o += _CHUNK) out.push(data.subarray(o, Math.min(o + _CHUNK, len)));
    return out;
  }
  if (_SPLIT > 0 && _SPLIT < len) return [data.subarray(0, _SPLIT), data.subarray(_SPLIT)];
  return [data];
}

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
  kind: "u" | "s" | "fp32" | "fp64" | "string" | "blob" | "struct" | "array" | "wrapper" | "struct_wrapper";
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
// CORELIB_PLAN §6.5: TS has no fp32 value type, so `x` above is already a widened
// double and the widening SETS the quiet bit — an fp32 signaling NaN can never be
// recovered from it. The generated Probe therefore captures the wire bytes
// alongside the value (`<field>Fp32Raw`, populated on decode when the value is a
// NaN); the round-trip path already re-encodes from them, which is why the
// round-trip oracle sees nothing. The materialized walk is a bit-exact consumer too
// (§6.5 "Testing"), so it must read the same raw channel rather than repack the
// double. `off` selects the element inside an fp32 *array*'s flat payload.
function _f32FromRaw(raw: Uint8Array, off: number): string {
  const bits = (raw[off] | (raw[off + 1] << 8) | (raw[off + 2] << 16) |
                (raw[off + 3] << 24)) >>> 0;   // little-endian wire order
  return "f" + bits.toString(16).padStart(8, "0");
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
function formatLeaf(kind: string, v: unknown, raw?: unknown, off = 0): string {
  switch (kind) {
    case "u": return "u" + (v as number | bigint).toString();
    case "s": return "s" + (v as number | bigint).toString();
    case "fp32":
      // Prefer the raw wire bytes when the generated type captured them (NaN only);
      // otherwise the widened double is lossless and repacking is exact.
      return raw instanceof Uint8Array && off + 4 <= raw.length
        ? _f32FromRaw(raw, off)
        : _f32(v as number);
    case "fp64": return _f64(v as number);
    case "string": return _t(v as string);
    case "blob": return _b(v as Uint8Array);
    default: throw new Error("unhandled leaf kind " + kind);
  }
}

// Generic recursive walk: descriptor node + the corresponding in-memory value → the
// materialized-form string. No schema shape is baked in here — structs, arrays, and
// wrappers are all discovered from the node.
function walk(node: SchemaNode, value: unknown, raw?: unknown): string {
  switch (node.kind) {
    case "struct": {
      const v = value as Record<string, unknown>;
      // Thread the sibling raw-bits field (§6.5) down with each child: the generated
      // type parks it next to the value as `<name>Fp32Raw`, for a scalar fp32 and for
      // an fp32 array alike (there it is the flat count*4 payload).
      return "{" + node.fields!.map((c) =>
        c.id + ":" + walk(c, v[c.name], v[c.name + "Fp32Raw"])).join(";") + "}";
    }
    case "array":
    case "wrapper":
      // array: numeric/fp materialized to N in memory; wrapper: index order,
      // container length is the signal. Both just map over the in-memory elements.
      return "[" + (value as unknown[]).map((el, i) =>
        formatLeaf(node.elem!, el, raw, i * 4)).join(",") + "]";
    case "struct_wrapper":
      // struct_array (WP-05): elements are generated objects — an obj walk per
      // element, container length as-is (like `wrapper`).
      return "[" + (value as Record<string, unknown>[]).map((e) =>
        "{" + node.fields!.map((c) => c.id + ":" + walk(c, e[c.name])).join(";") + "}"
      ).join(",") + "]";
    default:
      return formatLeaf(node.kind, value, raw);
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

// Re-encode through the streaming surface, which is the only one this backend has.
// SOFAB_FLUSH=n gives the OStream an n-byte buffer draining to a sink, so the message
// arrives in n-byte pieces and the encoder crosses a buffer boundary at every offset —
// the encode-side mirror of SOFAB_CHUNK=1. The bytes must not change either way.
function encodeBytes(m: Probe): Uint8Array {
  if (_FLUSH > 0) {
    const parts: Uint8Array[] = [];
    const os = new OStream(new Uint8Array(_FLUSH), 0, (c) => parts.push(Uint8Array.from(c)));
    try {
      m.serialize(os);
    } catch (e) {
      // corelib-ts's OStream.ensure(n) needs n CONTIGUOUS bytes and only flushes
      // before checking, so a caller buffer smaller than the largest single write
      // (e.g. 4 for an fp32, count*10 for a varint array) cannot encode at all. That
      // is a property of this backend, not of the message: corelib-cpp streams the
      // same value through a 1-byte buffer. Exit 3 — distinct from 2, "the backend
      // has no such surface" — so the gate can report the size as inapplicable
      // instead of either failing or, worse, silently skipping it.
      if (e instanceof SofabError && e.code === SofabErrorCode.BufferFull) {
        process.stderr.write(
          `crucible-ts: SOFAB_FLUSH=${_FLUSH} is below this backend's contiguous-write ` +
            `requirement (OStream.ensure needs n contiguous bytes): ${e.message}\n`,
        );
        process.exit(3);
      }
      throw e;
    }
    os.flush();
    const total = parts.reduce((n, p) => n + p.length, 0);
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }
  const os = new OStream();
  m.serialize(os);
  return os.bytes();
}

// Chunked decode via the generated ProbeDecoder (crucible#132; new in sofabgen
// cfe5250b). Used ONLY when a chunking variable is set, so the default path stays the
// one-shot Probe.decode byte for byte — which is also what makes the comparison
// meaningful: the gate then checks `decode(whole) == feed(a); feed(b); …`, two
// genuinely different code paths, rather than one path against itself.
//
// The verdict comes from `status`, never from `finish()`: finish() throws mid-field
// here and returns null in Dart, so routing the verdict through it would bake a
// backend difference into the canonical line (CONTRACT.md).
function canonicalChunked(data: Uint8Array): string {
  const d = new ProbeDecoder();
  try {
    for (const c of chunksOf(data)) {
      // Scrub mode needs a buffer the driver owns: feed it, then overwrite. A decoder
      // that borrowed from the chunk instead of copying out of it reads back 0xA5.
      const buf = _SCRUB ? Uint8Array.from(c) : c;
      d.feed(buf);
      if (_SCRUB) buf.fill(0xa5);
    }
  } catch (e) {
    if (e instanceof SofabError && e.code === SofabErrorCode.Incomplete) return "I";
    if (e instanceof SofabError && e.code === SofabErrorCode.LimitExceeded) return "L";
    return "R " + rejectClass(e);
  }
  const st = d.status;
  if (st === DecodeStatus.Invalid) return "R invalid_msg";
  if (st !== DecodeStatus.Complete) return "I";
  const m = d.message;
  if (_MATERIALIZE) return "A " + materialize(m);
  return "A " + _hex(encodeBytes(m));
}

function canonical(data: Uint8Array): string {
  // decode -> re-encode -> hex (oracle/canonical.md). The generated TS message
  // has no encode(), so serialize into an in-memory OStream and read its bytes.
  if (_SPLIT || _CHUNK || _SCRUB) return canonicalChunked(data);
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
  return "A " + _hex(encodeBytes(m));
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
