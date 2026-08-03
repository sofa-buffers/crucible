# F-0049 — the dart backend keeps a scalar `fp32`'s raw wire bits **private**, so no consumer can read a signaling NaN bit-exactly


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-08-02** while re-checking F-0031 against the corelibs. It is the residual of
F-0031 — and the only part of it that is *not* a Crucible-side defect.

## The §6.5 split

CORELIB_PLAN §6.5 divides implementations in two:

- **Native-`fp32` targets** (c, cpp, rust, go, java, csharp, zig) satisfy bit-exactness *for
  free* — the value never passes through a double.
- **Double-only targets** (typescript, python, dart) cannot, because widening `fp32 → fp64`
  **sets the quiet bit** and destroys a signaling NaN. They therefore **MUST** *"provide a
  **raw-wire-bytes** path for bit-exact consumers (transcode, round-trip, any re-encode)"*.

The round-trip half works everywhere: `CORPUS=findings/F-0049 ./scripts/run.sh` is **green on
all 13**. What is missing in dart is the *"for bit-exact **consumers**"* half.

## The defect

Generated `message.dart` parks the bits in a **library-private** field with no accessor:

```dart
class ProbeNested {
  double f32 = 0.0;
  int? _f32Fp32Bits;          // <-- private; no getter anywhere in the file
  ...
  void marshal(sofab.Encoder e) {
    if (f32.isNaN && _f32Fp32Bits != null) { e.writeFp32Bits(0, _f32Fp32Bits!); }
```

That serves the type's *own* re-encode and nothing else. Dart privacy is per-library, so any
consumer in another file — a transcoder, a bit-exact comparator, Crucible's materialized walker
— cannot reach it. The value channel is all that is left, and it has already been widened.

The **typescript** backend, same language class, same corelib support, gets it right:

```ts
class ProbeNested {
  f32: number = 0;
  f32Fp32Raw: Uint8Array | null = null;   // <-- public
```

A sibling-backend split with the corelib held constant — CLAUDE.md heuristic 3.

## The reproducers

| file | verdict |
|---|---|
| **`f32_snan_scalar.bin`** | scalar `nested.f32` = `0x7F800001`. Round-trip green on all 13. **Materialized: 12 drivers emit `f7f800001`, `dart` emits `f7fc00001`** |
| `ctl_f32_qnan_scalar.bin` | the same position with a *quiet* NaN payload (`0x7FC00001`) — all 13 agree. The quiet bit is already set, so widening cannot change it; this shows the path is only lossy for the **signaling** case |
| `ctl_f32_snan_array.bin` | the same sNaN as an **fp32 array element** — all 13 agree, dart included. A decoded fp32 array is a `Float32List`, whose byte buffer still holds the wire bits, so a consumer *can* get at them there |

The third control is the sharp one: it pins the defect to the **scalar** position specifically.
Dart is bit-exact at the array position and not at the scalar, purely because one container
exposes its bytes and the other field does not.

## Attribution — generated code (`generator`, dart backend), **G-0033**

- **corelib-dart is conformant.** It supplies both halves of the raw channel:
  `Encoder.writeFp32Bits` (`lib/src/encoder.dart:278`) and raw NaN bits on decode
  (`lib/src/decoder.dart:27`). Nothing to fix there.
- **The generated type** decides the field's visibility, and chose private.

Fix: expose the bits — a public field as the ts backend does (`f32Fp32Raw`), or a getter
(`int? get f32Fp32Bits`). One line per scalar `fp32` field.

## Relationship to F-0031

F-0031 catalogued this as *"corelib-py + corelib-ts + corelib-dart, corelib-only"*. That
attribution was **wrong on all three counts**, established 2026-08-02:

| impl | what it actually was |
|---|---|
| py-cython | already fixed upstream; left the camp before this re-check |
| **go** | **Crucible's own driver** — `drivers/go/driver.go` read the value via `reflect.Value.Float()`, which widens `float32 → float64`. corelib-go and the generated code never widen, which is why the round-trip oracle never saw it. Fixed here |
| **typescript** | **Crucible's own driver** — the walker repacked the widened double instead of reading the `f32Fp32Raw` channel the generated code already exposed. Fixed here |
| **dart** | the genuine residual — **this finding** |

So F-0031 produced no upstream issue and never should have: two thirds of it was our own
measurement apparatus, and the corelibs had shipped their §6.5 work.

## Resolution

**Impls:** generator (sofabgen **dart backend**) — **G-0033** · **Axis:** accept_value (materialized oracle only)

✅ **RESOLVED 2026-08-02** — [generator#275](https://github.com/sofa-buffers/generator/issues/275) fixed and closed the same day it was filed: `fix(dart): the fp32 raw-bits companion must be consumer-visible` (sofabgen `0.0.0-20260802192533-88a6833a2f72`). The generated field is now the public `int? f32Fp32Bits`. **Crucible's own half had to follow** — the fix only *exposes* the bits; `drivers/dart/materialize_gen.py` was still formatting the widened double, so the divergence would have persisted as ours. The walker now reads the companion (`_f32Scalar`), mirroring the `_f32Elem` array path added the same day. **Verified on the oracle that can see it**: `materialize.sh` 108 × 13, 0 divergences, C anchor 0/108 — `run.sh` was green throughout and says nothing here. `f32_snan` is back in `corpus/structured`, so the scalar sNaN now sits in a blocking gate. *Original report:
