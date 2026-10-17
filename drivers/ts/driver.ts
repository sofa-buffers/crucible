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

import { Probe, Probe__Decoder } from "./message";
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
// This backend has TWO of the three encode surfaces: the generated `encode()` (`new`, the
// default) and `serialize(os)` into a caller-built `OStream` (`stream`). The generated
// code has no `encodeTo()`, so `SOFAB_ENCODE=to` must be a hard error rather than a
// fallback — reporting a mode as passing that never ran is the failure the encode gate
// exists to prevent (meta: encode_surfaces=new,stream).
const _num = (name: string): number => {
  const v = process.env[name];
  return v ? parseInt(v, 10) || 0 : 0;
};
const _SPLIT = _num("SOFAB_SPLIT");
const _CHUNK = _num("SOFAB_CHUNK");
const _FLUSH = _num("SOFAB_FLUSH");
// SOFAB_ENCODE_FAIL=n: the destination handed to the encoder takes n bytes.
const _FAIL = _num("SOFAB_ENCODE_FAIL");
const _SCRUB = !!process.env.SOFAB_CHUNK_SCRUB && process.env.SOFAB_CHUNK_SCRUB !== "0";
const _ENCODE = process.env.SOFAB_ENCODE ?? "";
// SOFAB_FLUSH sizes the stream surface's buffer, so on its own it selects that surface.
const _SURFACE = _ENCODE || (_FLUSH > 0 ? "stream" : "new");
if (_SURFACE !== "new" && _SURFACE !== "stream") {
  process.stderr.write(
    `crucible-ts: SOFAB_ENCODE=${_SURFACE} — this backend has only 'new' and 'stream' ` +
      `(the generated code has no encodeTo())\n`,
  );
  process.exit(2);
}
if (_FLUSH > 0 && _SURFACE !== "stream") {
  process.stderr.write(
    `crucible-ts: SOFAB_FLUSH=${_FLUSH} sizes the stream surface's buffer, ` +
      `but SOFAB_ENCODE=${_SURFACE}\n`,
  );
  process.exit(2);
}
// Announce the configuration on stderr (never parsed). Without it a driver that
// silently ignored the variables would be indistinguishable from one that honours
// them — identical stdout either way — which is the vacuous pass the gate's opt-in
// roster guards against. This is the same guard at the driver level.
if (_SPLIT || _CHUNK || _SCRUB || _FLUSH || _ENCODE || _FAIL) {
  process.stderr.write(
    `crucible-ts: streaming cfg split=${_SPLIT} chunk=${_CHUNK} ` +
      `scrub=${_SCRUB ? 1 : 0} enc=${_SURFACE} flush=${_FLUSH} ` +
      `fail=${_FAIL}\n`,
  );
}

// How the record is cut on its way into the decoder. k<=0, k>=len and n>=len all mean
// one chunk holding the whole record. A zero-length record is ONE empty chunk, fed once
// (CONTRACT.md rule 4): the decoder, not the driver, answers the empty message. No
// other empty chunk is ever produced.
function chunksOf(data: Uint8Array): Uint8Array[] {
  const len = data.length;
  if (len === 0) return [data];
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
  kind: "u" | "bool" | "s" | "fp32" | "fp64" | "string" | "blob" | "struct" | "array" | "wrapper" | "struct_wrapper" | "union"
    | "enum" | "bitfield" | "node_wrapper";
  fields?: SchemaNode[];
  options?: SchemaNode[];
  default_id?: number;
  elem?: "u" | "bool" | "s" | "enum" | "bitfield" | "fp32" | "fp64" | "string" | "blob";
  count?: number;
  item?: SchemaNode;   // node_wrapper: the (nameless) element node
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
// recovered from it. The generated code therefore keeps a bit-exact channel beside
// the widened value, and since the typed-array codegen there are TWO of them:
//
//   * a SCALAR fp32 parks the four wire bytes in a sibling field `<name>Fp32Raw`,
//     populated on decode only when the value is a NaN (unchanged);
//   * an fp32 ARRAY no longer has that sibling — it materializes as a
//     `Float32Array`, whose buffer the decoder fills with the 32-bit wire words
//     directly, so the array IS its own raw channel and a byte view over it is
//     bit-exact for every element, NaN or not.
//
// The round-trip path re-encodes from the same storage, which is why the round-trip
// oracle sees nothing either way. The materialized walk is a bit-exact consumer too
// (§6.5 "Testing"), so it must read the raw channel rather than repack the double.
// `off` selects the element inside an fp32 *array*'s flat payload.
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
    case "bitfield":
    case "u": return "u" + (v as number | bigint).toString();
    // §4.4 boolean: the unsigned value it is on the wire — u1/u0. `Number(v)` rather
    // than a ternary on purpose: a generated `boolean` yields 1/0, and a port that
    // handed back a non-normalized raw number renders that number, which is the
    // divergence the materialized form exists to surface.
    case "bool": return "u" + Number(v as boolean | number).toString();
    // enum / bitfield: a generated numeric TS enum — the runtime value is already the
    // integer (outside the named members too), so they print exactly like s / u.
    case "enum":
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
      // type parks it next to the value as `<name>Fp32Raw` for a SCALAR fp32. An
      // fp32 array carries its bits in its own Float32Array instead (see below), so
      // for that child the lookup simply finds nothing and the array case supplies it.
      return "{" + node.fields!.map((c) =>
        c.id + ":" + walk(c, v[c.name], v[c.name + "Fp32Raw"])).join(";") + "}";
    }
    case "union": {
      // A union holds exactly one option (§4.2): read the held id through the public
      // `which` accessor and walk only that option's getter. Testing every option for
      // a non-default value would lose a held option sitting at its own default.
      const v = value as Record<string, unknown>;
      const id = v.which as number;
      const o = node.options!.find((c) => c.id === id);
      if (!o) throw new Error("union holds unknown option id " + id);
      return "{" + o.id + ":" + walk(o, v[o.name], v[o.name + "Fp32Raw"]) + "}";
    }
    case "array":
    case "wrapper": {
      // `array` (a compact scalar/float array, §3) materializes as a TYPED array —
      // Uint8Array … BigInt64Array, Float32Array, Float64Array — while `wrapper`
      // (string/blob elements, §5.1) stays a plain array. Both are ArrayLike, which
      // is all this needs. Never `.map()`: a typed array's flavour of it coerces the
      // callback's string back to a number (Uint8Array) or throws (BigInt64Array),
      // and neither failure is visible in the output — it just silently materializes
      // the wrong value.
      const arr = value as ArrayLike<unknown>;
      // fp32 elements: the Float32Array's buffer holds the wire words verbatim, so a
      // byte view over it is the bit-exact channel (§6.5) that `<name>Fp32Raw` is for
      // a scalar. `raw` stays the fallback for a shape that still passes one down.
      const bits = node.elem === "fp32" && value instanceof Float32Array
        ? new Uint8Array(value.buffer, value.byteOffset, value.length * 4)
        : raw;
      const out: string[] = [];
      for (let i = 0; i < arr.length; i++) out.push(formatLeaf(node.elem!, arr[i], bits, i * 4));
      return "[" + out.join(",") + "]";
    }
    case "node_wrapper": {
      // A dynamic wrapper array whose elements are themselves nodes (a union, or a
      // further node_wrapper): walk each ACTUAL element through `item`; nothing is
      // padded to `count`.
      const a = value as unknown[];
      const out: string[] = [];
      for (let i = 0; i < a.length; i++) out.push(walk(node.item!, a[i]));
      return "[" + out.join(",") + "]";
    }
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

// The canonical class of a decode reject or a refused re-encode, read off the
// corelib's SofabErrorCode (oracle/canonical.md). Incomplete and LimitExceeded never
// reach this: they are verdicts of their own (`I`, `L`), classified by the callers.
// Anything that is not a SofabError is surfaced as "other" rather than hidden.
function errorClass(e: unknown): string {
  // A stack overflow is a crash, not a verdict: rethrow it so the harness sees the
  // driver die. (V8 has no catchable out-of-memory; it aborts the process.)
  if (e instanceof RangeError && /call stack/i.test(e.message)) throw e;
  if (e instanceof SofabError) {
    switch (e.code) {
      case SofabErrorCode.InvalidMsg: return "invalid_msg";
      case SofabErrorCode.Argument: return "argument";
      case SofabErrorCode.BufferFull: return "buffer_full";
    }
  }
  return "other";
}

// The `A <hex>` line, or `E <class>` when the re-encode of an ACCEPTED value was
// refused — its own verdict, never a reject class, and never an escaping throw:
// before this, a refusal propagated out of canonical() and killed the process, which
// the comparator reports as a crashed driver and which costs every line after it
// (oracle/canonical.md "The fifth verdict `E`").
function acceptLine(m: Probe): string {
  let bytes: Uint8Array;
  try {
    bytes = encodeBytes(m);
  } catch (e) {
    return "E " + errorClass(e);
  }
  return "A " + _hex(bytes);
}

// SOFAB_FLUSH=n: the stream surface's OStream gets an n-byte buffer draining to a
// sink, so the message arrives in n-byte pieces and the encoder crosses a buffer
// boundary at every offset — the encode-side mirror of SOFAB_CHUNK=1.
//
// The sink is handed the INSTALLED BUFFER plus coordinates — `buffer[start..end)` —
// never a subarray, because a view would be an allocation per flush and the encoder
// allocates nothing after construction (§6.6); and never foreign memory, because
// §5.1.6 forbids pass-through. Copying the region out is what lets the encoder keep
// writing into the same buffer. Taking `buffer` whole here instead would append the
// untouched tail of the window to every piece.
let _parts: Uint8Array[] = [];
function flushStream(): OStream {
  return new OStream(new Uint8Array(_FLUSH), 0, (buffer, start, end) =>
    _parts.push(buffer.slice(start, end)),
  );
}

// CORELIB_PLAN §5.1 (CONTRACT.md "Which flush sizes must work"): a size at or above
// meta's min_output_buffer MUST work, one below it MUST be refused where the buffer is
// handed over — and that refusal is the corelib's to make, at the OStream constructor,
// so the driver asks it once before any record rather than comparing against a number
// of its own. A refusal exits 3. Whether that is the required answer or a conformance
// failure is the gate's call, from the same meta value.
if (_FLUSH > 0) {
  try {
    flushStream();
  } catch (e) {
    process.stderr.write(
      `crucible-ts: SOFAB_FLUSH=${_FLUSH} refused at the handover ` +
        `(CORELIB_PLAN §5.1): ${e instanceof Error ? e.message : String(e)}\n`,
    );
    process.exit(3);
  }
}

// Re-encode through the selected surface. Each is the generated entry point an
// application would call; a throw from any of them is the `E` line above.
//   new     -> the generated `encode()`: one exact MAX_SIZE buffer it allocates itself
//   stream  -> `serialize(os)` into an OStream this driver builds — a MAX_SIZE buffer
//              with no sink, or the SOFAB_FLUSH window draining to one
function encodeBytes(m: Probe): Uint8Array {
  // SOFAB_ENCODE_FAIL=n (CONTRACT.md): a destination of n bytes with NO sink, so a
  // message that does not fit is REFUSED (SofabErrorCode.BufferFull) rather than
  // truncated, and the `E` mapping runs for real — from the wire that branch is
  // unreachable, because every value re-encoded here came out of this driver's own
  // decoder and is in-bounds by construction.
  if (_FAIL > 0) {
    const small = new Uint8Array(_FAIL);
    const sos = new OStream(small, 0);
    m.serialize(sos);
    sos.flush();
    return small.subarray(0, sos.bytesUsed);
  }
  if (_SURFACE === "new") return m.encode();
  if (_FLUSH > 0) {
    _parts = [];
    const os = flushStream();
    m.serialize(os);
    os.flush();
    const total = _parts.reduce((n, p) => n + p.length, 0);
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of _parts) { out.set(p, o); o += p.length; }
    return out;
  }
  // The buffer is the CALLER's (CORELIB_PLAN §6.6): OStream holds none of its own, so
  // the stream surface needs one supplied — MAX_SIZE, the schema's worst case, so every
  // value the schema permits fits.
  const os = new OStream(new Uint8Array(Probe.MAX_SIZE));
  m.serialize(os);
  return os.bytes();
}

// Chunked decode via the generated ProbeDecoder (crucible#132; new in sofabgen
// cfe5250b). Used ONLY when a chunking variable is set, so the default path stays the
// one-shot Probe.decode byte for byte — which is also what makes the comparison
// meaningful: the gate then checks `decode(whole) == feed(a); feed(b); …`, two
// genuinely different code paths, rather than one path against itself.
//
// The verdict is what the LAST `feed` returned, never what `finish()` says: finish()
// throws mid-field here and returns null in Dart, so routing the verdict through it
// would bake a backend difference into the canonical line (CONTRACT.md).
//
// It used to be read from a `status` accessor beside `feed`. CORELIB_PLAN §5.2.1
// closed that door — the outcome "MUST reach the caller from the `feed` that produced
// it", with "no second place to ask", because two surfaces holding one answer can
// disagree — so the generated decoder has no such accessor any more. Every record
// feeds at least once (a zero-length one feeds one empty chunk), so `st` below is
// always a status the corelib returned, never one this driver assumed.
function canonicalChunked(data: Uint8Array): string {
  const d = new Probe__Decoder();
  let st: DecodeStatus | undefined;
  try {
    for (const c of chunksOf(data)) {
      // Scrub mode needs a buffer the driver owns: feed it, then overwrite. A decoder
      // that borrowed from the chunk instead of copying out of it reads back 0xA5.
      const buf = _SCRUB ? Uint8Array.from(c) : c;
      st = d.feed(buf);
      if (_SCRUB) buf.fill(0xa5);
    }
  } catch (e) {
    if (e instanceof SofabError && e.code === SofabErrorCode.Incomplete) return "I";
    if (e instanceof SofabError && e.code === SofabErrorCode.LimitExceeded) return "L";
    return "R " + errorClass(e);
  }
  // No `Invalid` arm: `feed` returns only Complete or Incomplete (corelib-ts types
  // that as `FeedStatus`), and a malformed message arrives as the throw the catch
  // above already classifies — CORELIB_PLAN §6.3's error-channel option for the one
  // outcome that is terminal.
  if (st !== DecodeStatus.Complete) return "I";
  const m = d.message;
  if (_MATERIALIZE) return "A " + materialize(m);
  return acceptLine(m);
}

// SOFAB_REUSE=1 (CONTRACT.md, "Reused destination"): every record decodes into ONE
// destination held for the whole run, through Probe.tryDecode(bytes, out), which resets
// it first and writes over its storage. Each line must equal the fresh-destination one.
const _REUSED: Probe | null = (() => {
  const s = process.env.SOFAB_REUSE;
  if (!s || s === "0") return null;
  process.stderr.write("crucible-ts: reuse=1\n");
  return new Probe();
})();

function canonical(data: Uint8Array): string {
  // decode -> re-encode -> hex (oracle/canonical.md). A zero-length record goes
  // through Probe.decode like any other: the decoder answers the empty message.
  if (_SPLIT || _CHUNK || _SCRUB) return canonicalChunked(data);
  let m: Probe;
  try {
    if (_REUSED) {
      // tryDecode answers INCOMPLETE as a status where decode() throws it.
      if (Probe.tryDecode(data, _REUSED) !== DecodeStatus.Complete) return "I";
      m = _REUSED;
    } else {
      m = Probe.decode(data);
    }
  } catch (e) {
    // INCOMPLETE (truncation) is a distinct hard verdict, not a reject: the
    // stream ended inside a field. Detect it first (canonical.md: never collapse
    // it into A or R). The line is a bare `I` — it carries no payload.
    if (e instanceof SofabError && e.code === SofabErrorCode.Incomplete) {
      return "I";
    }
    if (e instanceof SofabError && e.code === SofabErrorCode.LimitExceeded) {
      // LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
      // cap on a schema-unbounded field. A policy rejection distinct from INVALID —
      // its own verdict `L`, not `R`.
      return "L";
    }
    return "R " + errorClass(e);
  }
  // COMPLETE decode. In materialize mode, dump the decoded value (oracle/
  // materialized.md) instead of the re-encoded wire hex; the default path is
  // unchanged.
  if (_MATERIALIZE) {
    return "A " + materialize(m);
  }
  return acceptLine(m);
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
