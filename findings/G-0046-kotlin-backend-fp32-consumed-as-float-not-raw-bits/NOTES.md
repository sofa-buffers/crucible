# G-0046 — the sofabgen Kotlin backend consumes an `fp32` as a `Float`, so on Kotlin/JS a signaling NaN is quieted

**Status:** ✅ **RESOLVED** — fixed upstream in [generator#716](https://github.com/sofa-buffers/generator/pull/716) (merged 2026-10-07, five days after this was filed), with [corelib-kotlin-mp#56](https://github.com/sofa-buffers/corelib-kotlin-mp/pull/56) underneath it. The generated visitor overrides **`fp32Bits`** and takes the wire pattern: a scalar stores `Float.fromBits(bits)` and keeps the pattern beside it in a public `<field>Fp32Bits: Int?` while the value is a NaN (`Seq.fp32NaNBits`), an array element goes in through `Seq.putFp32Bits` over `Seq.fp32BitsView`, and `OStream.writeFp32(id, value, raw)` re-emits it. Crucible's own half followed on 2026-10-12: `drivers/kotlin/materialize_gen.py` reads that channel instead of asserting it does not exist. **The `kotlin-js` leg is still quarantined, for an unrelated reason** — the image's `kotlinc-js` (2.4.10) is older than the Kotlin the corelib's JS klib is built with (2.4.21), and an older compiler ignores a newer klib silently: [crucible#244](https://github.com/sofa-buffers/crucible/issues/244).
**Guard:** corpus/structured — `043_f32_snan.bin` (scalar) and `083_arr_fp32_nan_bits.bin` (array element). The replay and materialized gates feed both on every run; they bind the `kotlin-js` row the moment crucible#244 lets it build, and they already bind the walker's new read path on the JVM and Native rows, where `<field>Fp32Bits` and `Seq.fp32BitsView` are null and the fallback has to be exact.
**Issue:** [generator#670](https://github.com/sofa-buffers/generator/issues/670) (filed 2026-10-02, closed 2026-10-07 by [generator#716](https://github.com/sofa-buffers/generator/pull/716))

**Found 2026-10-02** while wiring the Kotlin/JS leg of `drivers/kotlin/` (crucible#213). It is
the F-0049 / G-0033 shape again, in the one backend whose corelib already did its part.

## The split

`CORPUS=corpus/structured`, three drivers (`c`, `kotlin-jvm`, `kotlin-js`), both oracles:

| input | `c`, `kotlin-jvm` | `kotlin-js` |
|---|---|---|
| `043_f32_snan.bin` — scalar `nested.f32` = `0x7F800001` | writes `…01 00 80 7f` back | writes `…01 00 c0 7f` (`0x7FC00001`) — the quiet bit (`0x00400000`) is set |
| `083_arr_fp32_nan_bits.bin` — the same pattern as the first `fp32` array element | `…05 20 01 00 80 7f…` | `…05 20 01 00 c0 7f…` |

Every other input agrees: 24 881 inputs of the grown corpus, `corpus/structured`,
`conformance`, `seeds`, `regression` — the only divergences `kotlin-js` adds are these two.
(`corpus/interesting` has one unrelated `c` ≠ both Kotlin legs divergence, which `kotlin-jvm`
shows too.)

## The rule

CORELIB_PLAN §6.5 splits implementations in two. A **native-`fp32`** target is bit-exact for
free. A target whose `Float` is not a real binary32 — Kotlin/JS: a `Float` is a JS `number`, a
double — *cannot* be, because widening quiets a signaling NaN, so it MUST give bit-exact
consumers a raw-wire-bits path.

## Attribution: generated code, not the corelib

corelib-kotlin-mp **provides** the path. `Visitor.kt:52-70` delivers every `fp32` field and
array element through `fp32Bits(id, bits: Int)`, and documents that its *default*
implementation widens the bits into a `Float` and calls `fp32(id, Float)` — the lossy route,
there for a consumer that only wants the value. `OStream.writeFp32Bits` /
`writeArrayFp32Bits` are the matching encode half. The corelib hands over the four payload
bytes unchanged.

The generated visitor takes the lossy route. `drivers/kotlin/build/<target>/gen/…/Probe.kt`,
`_Probe__Visitor`:

```kotlin
override fun fp32(id: Int, value: Float) {   // :335 — never fp32Bits
    …   1 -> { m.arrays.nested.fp32[ai] = value; ai++ }   // :342, array element
    …   0 -> { m.nested.f32 = value }                      // :351, scalar
```

and the message stores a `Float` / `FloatArray`, so even an `fp32Bits` override would have
nowhere to put the bits. Which backend can fix it is not in doubt — only generated code knows
the message's field types and what it stores — so it goes to **`generator`**.

The sibling-backend comparison is the same one F-0049 drew: the TypeScript backend keeps a
public `f32Fp32Raw`; the Dart backend, before generator#275, kept it private. Kotlin keeps
none.

JVM and Kotlin/Native are unaffected only because `Float` is a real binary32 there; the
divergence is a property of the JS target, which is why it is invisible until that leg runs.

## What a fix needs

An `fp32Bits` override in the generated visitor, and a bits-carrying channel in the generated
message for a scalar and an array element that a bit-exact consumer — Crucible's materialized
walker — can read, as TypeScript and (after generator#275) Dart have.

## What the fix required on this side

The Kotlin materialized walker had the defect's premise written into it as a **type note**:

> `fp32` — a real Kotlin Float, so `Float.toRawBits()` is the exact wire pattern: nothing
> widened it through a double, so a signalling NaN survives and no `<field>Fp32Bits`
> companion channel (generator#275, the Dart case) is involved.

True on JVM and Native, false on Kotlin/JS — where a `Float` **is** a JS number — and it
named the very channel the fix then introduced. `drivers/kotlin/materialize_gen.py` now
emits `_f32(b, value, raw)` with the pattern beside the value:

- a scalar passes `<expr>Fp32Bits`, the companion the generated message keeps while the
  value is a NaN;
- an array reads `Seq.fp32BitsView(FloatArray): IntArray?` once per container and indexes
  it, which is the same public helper the generated visitor fills through.

Both are `null` where neither is needed, so JVM and Native keep `toRawBits()` — the
fallback, not an exception. That is also what the two guard vectors bind on those rows
today, with the JS row still out for crucible#244.
