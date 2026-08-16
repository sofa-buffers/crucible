# F-0031 — an fp32 *signaling* NaN is quieted (0x7F800001 → 0x7FC00001) by py-cython / typescript / dart

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — vectors promoted 2026-08-16, replayed by the resolved-findings gate on every push; a divergence there means this bug came back.

**Axis:** accept_value (round-trip **and** materialized/raw-bits). **Impls:** `py-cython`, `typescript`,
`dart` (3) vs the other **10** (incl. `py-pure`). **Corelib, not codegen** — fp32 storage/materialization
is a corelib concern, schema-independent.

## The split — a signaling NaN fp32 is quieted

MESSAGE_SPEC / CORELIB_PLAN §4.6 (:263-267): *"Float payloads are stored as **raw IEEE-754 little-endian
bytes**, so every value — including `±0`, `±inf`, and `NaN` — round-trips **bit-for-bit**. The corelib
**never inspects or normalizes** the value; `NaN` is just another float payload."* There is **no sNaN
carve-out** — a signaling NaN must round-trip bit-for-bit like any other payload.

Reproducer: `nested.f32` = **fp32 signaling NaN `0x7F800001`** (exponent all-ones, mantissa MSB clear,
low bit set).

| camp | re-encodes / materializes the fp32 as | drivers |
|---|---|---|
| **preserve** (conformant §4.6) | `0x7F800001` (wire `01 00 80 7f`; materialized `f7f800001`) | c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, **py-pure**, java, csharp, zig (10) |
| **quiet the sNaN** | `0x7FC00001` (wire `01 00 c0 7f`; materialized `f7fc00001`) — the mantissa MSB (bit 22) is set, turning the signaling NaN into a quiet one | **py-cython, typescript, dart (3)** |

Splits on **both** oracles: the round-trip re-encode (`accept_value` hex) and the materialized element
walk (raw bits) — the materialized oracle compares floats bit-for-bit, so the quieting is directly visible.

## Scope — only fp32 sNaN; qNaN payloads and fp64 sNaN are fine

The neighbouring vectors **agree across all 13**:
- `f32_qnan_payload` (`0x7FC00001`, already quiet) — preserved by all (control `f32_qnan_payload.bin`).
- `f32_nan_neg` (`0xFFC00000`) — preserved by all.
- `f64_snan` (`0x7FF0000000000001`) — preserved by all (control `f64_snan.bin`).

So the defect is narrowly the **quieting of a *signaling* NaN on the fp32 path**: `0x7F800001` differs
from a quiet NaN only in bit 22 (the "is-quiet" bit), and the three implementations set it. This is the
classic **sNaN-quieting on load into a wider float register**: `py-cython`, `typescript` (JS `number`),
and `dart` materialize an fp32 through a 64-bit double, and loading a signaling NaN into a double quiets
it. `py-pure` (pure-Python, no C-double round-trip on the fp32 path) preserves it — the sibling split that
pins it to the double-backed fp32 representation, not "all of Python".

## Attribution — corelib (three impls), not codegen

Per the CLAUDE.md triage: *does the fix need knowledge only the schema has?* **No.** fp32 bit preservation
is a wire-value property (§4.6), schema-independent; the corelib "never inspects or normalizes" — quieting
is exactly the normalization the spec forbids. The generated code hands the corelib 4 raw bytes; the
corelib is what stores them through a double and quiets the sNaN. To preserve, the fp32 path must carry the
raw 4 bytes (or a same-width float) rather than widening to a double before re-emit/materialize — the same
storage choice `py-pure` and the 9 other backends already make. Filed against **corelib-py** (the Cython
engine — `py-pure` is conformant, so this is engine-specific), **corelib-ts**, **corelib-dart**.

*(canonical.md:107-109 already flagged this as a "known per-language limit, harmless for current seeds" —
WP-06 is the first suite to carry an fp32 sNaN vector, so it turns the flagged limit into a catalogued,
spec-cited finding. If the maintainers decide double-backed fp32 cannot preserve sNaN and the spec should
sanction it, this converts to an `oracle/policy.yaml` allowed-divergence citing §4.6 instead — ground
rule 6. Filed as a finding first because the spec today is unambiguous: bit-for-bit, no normalization.)*

## Reproduce

```sh
# built against probe; nested.f32 = fp32 sNaN 0x7F800001
CORPUS=findings/F-0031-fp32-snan-quieted-py-cython-ts-dart ./scripts/run.sh
# f32_snan.bin: py-cython/typescript/dart re-encode 0x7FC00001, the other 10 keep 0x7F800001.
# f32_qnan_payload.bin, f64_snan.bin: controls — all 13 agree (preserved).
```

## Regression-gate & promotion

Held **out** of the green `corpus/structured/` cross-encode + materialized gate (`gen.py` omits the
`f32_snan` vector, with a comment) until the three impls preserve the sNaN — mirroring the F-0025/F-0026
arc. When they do: add the `f32_snan` vector back to `gen.py::vectors()`, regenerate `corpus/structured/`,
and verify all 13 preserve `0x7F800001`. The subnormal / qNaN-payload / negative-NaN / fp64-sNaN / +0.0
vectors WP-06 added are already in the green gate.

## Resolution

**Impls:** **RE-ATTRIBUTED 2026-08-02 — not the corelibs.** py-cython left the camp (fixed upstream); `go` and `typescript` were **Crucible's own drivers**; the residual `dart` scalar is **codegen** (**G-0033**, split out as F-0049). corelib-py / -ts / -dart are conformant and no issue was filed · **Axis:** accept_value (round-trip + materialized)

✅ **RESOLVED 2026-08-02 — the fix was never deficient; the measurement was.** Re-checked against the corelibs: the round-trip oracle is green on all 13 (the §6.5 raw path works family-wide), and the three materialized-oracle stragglers were **not** corelib defects. **`go`**: `drivers/go/driver.go` read the value through `reflect.Value.Float()`, which widens `float32 → float64` and sets the quiet bit — proven with a standalone Go program (`reflect .Float()` → `7fc00001`, `.Interface()` → `7f800001`); corelib-go and the generated code keep a native `float32` throughout, which is exactly why the round-trip never saw it. **`typescript`**: the walker repacked the widened double via `setFloat32` instead of reading `f32Fp32Raw`, the raw channel the generated code already exposed. Both fixed here; `dart`'s array position too (`Float32List` byte buffer). **Residual: the `dart` *scalar* position only**, where the generated bits are library-private with no accessor — split out as **F-0049 / G-0033**. Lesson recorded in STATUS-LOG: filing this upstream would have been the F-0008 mistake three times ove **Arc complete 2026-08-02:** F-0049 closed too (generator#275), so every impl is bit-exact at both fp32 positions and `f32_snan` is back in the structured gate. F-0031 produced no upstream issue and correctly so — of its three stragglers two were Crucible's own drivers and the third was a codegen visibility gap
