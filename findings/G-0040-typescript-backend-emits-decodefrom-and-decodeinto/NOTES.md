# G-0040 — generated TypeScript exposes `decodeFrom` / `decodeInto` (two names §6.1.1 forbids)

**Status:** 🔴 **open** — filed 2026-08-22 as [generator#384](https://github.com/sofa-buffers/generator/issues/384)
**Issue:** [generator#384](https://github.com/sofa-buffers/generator/issues/384)

Found 2026-08-22 while auditing every corelib README against CORELIB_PLAN §9 (the
README-tightening pass; see `docs/STATUS-LOG.md`). A **static** defect — a naming
contract violation, not a wire bug — so it has no fuzz reproducer and no corpus
guard: no byte sequence can expose it, and the differential oracle cannot see it at
all. It is caught by reading generated source.

The **TypeScript backend** gives every generated message class three public static
decode methods, two of which are spellings CORELIB_PLAN §6.1.1 lists as forbidden:

```ts
static decode(bytes: Uint8Array): ProbeArrays   // in the closed set
static decodeFrom(c: Cursor): ProbeArrays       // = decode_from
static decodeInto(c: Cursor, o: ProbeArrays)    // = decode_into
```

`decode` delegates to `decodeFrom`, which delegates to `decodeInto`. The two extra
names are internal steps of one operation, but `static` makes them part of the
generated type's surface — which is exactly the surface §6.1.1 closes.

**Evidence.** `drivers/ts/build/message.ts`, sofabgen
`0.0.0-20260821224828-89330ac81a61`. All five generated types carry the full trio:
`ProbeArrays` 149/153/159, `ProbeArraysNested` 229/233/239, `ProbeNested`
326/330/336, `ProbeStructArrayElem` 386/390/396, `Probe` 566/570/576.

**The clause** (CORELIB_PLAN.md:1010, verified at documentation `main@dd2866b`):
the generated-object set is closed to `encode` / `decode` / `try_decode` /
`serialize` / `deserialize` / `decoder`, and `decode_from` and `decode_into` are
both named among the spellings a port "must not invent beside them". Only the
**casing/idiom** may be adapted (`try_decode` / `tryDecode` / `TryDecode`), never
the words — so `decodeFrom` is `decode_from` in TypeScript's idiom, not a distinct
name.

**Attribution: codegen.** The corelib is schema-agnostic and emits no message
classes, so it cannot choose these names; the TypeScript backend does. Grepped every
backend's generated output under `drivers/*`: the two names appear in the TypeScript
output only. The Zig backend names its streaming entry point `decoder()`, the §6.1.1
name.

**Fix:** keep `decode(bytes)` public and take the two intermediate steps off the
type's public surface (a module-level function, or `static #decodeFrom` /
`static #decodeInto`). §6.1.1's closing paragraph already exempts everything below
the generated layer — `feed`, `read_*`, `write_*`, `sequence_*` "is corelib API and
keeps its own names" — so a cursor-level entry point that is genuinely wanted belongs
to the corelib, not to the generated object.

**Adjacent, not claimed:** the Go backend emits `Decode<Name>From(io.Reader)`
(`DecodeProbeFrom`) as its streaming-in entry point where §6.1.1's table names
`decoder()`. The words are not literally `decode_from` and the name is consistent
with its own `DecodeProbe`, so it is raised in the issue as a separate question
rather than folded into this finding.
