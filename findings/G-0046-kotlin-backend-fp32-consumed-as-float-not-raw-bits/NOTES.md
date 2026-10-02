# G-0046 — the sofabgen Kotlin backend consumes an `fp32` as a `Float`, so on Kotlin/JS a signaling NaN is quieted

**Status:** 🔴 **OPEN** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status; this file is the evidence. The JS leg that exposes it is quarantined meanwhile (`drivers/roster`).
**Guard:** corpus/structured — `043_f32_snan.bin` (scalar) and `083_arr_fp32_nan_bits.bin` (array element): the replay and materialized gates both see them as soon as the `kotlin-js` row is un-quarantined.
**Issue:** [generator#670](https://github.com/sofa-buffers/generator/issues/670) (filed 2026-10-02)

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
