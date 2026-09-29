# G-0044 — the sofabgen Dart backend decodes `array of boolean` into raw integers: a non-zero element other than `1` is not normalized to `true`

**Status:** 🔴 **OPEN** — filed 2026-09-29; [`results/FINDINGS.md`](../../results/FINDINGS.md) owns the state, this file is the evidence.
**Issue:** [generator#616](https://github.com/sofa-buffers/generator/issues/616) (filed 2026-09-29)
**Corelib:** none owns the defect. The open question on the corelib side (no dedicated boolean *read* function in `corelib-dart`, §4.4) is separate and is not part of this finding.

**Found 2026-09-29** by the materialized-value oracle over the merged nightly corpus
(24 440 inputs, nightly 36546281225): 7 inputs, all on field 204 (`flag_array`), all `dart`
alone against the other 16 drivers.

## The rule

CORELIB_PLAN §4.4 (documentation `b6586b5`): a decoder **MUST** read every value other than
`0` as `true`, and a boolean carries no width bound. MESSAGE_SPEC §4.7 makes an `array of
boolean` an array of unsigned integers, so the rule binds each element as it binds a scalar
(the same reading G-0042 established for the C++ backend).

## The divergence

`schema/probe.sofab.yaml`: `flag_array: { id: 204, type: array, items: { type: boolean, count: 5 } }`.

| input | bytes | §4.4 requires | 16 drivers | `dart` |
|---|---|---|---|---|
| `r0_arr_elem_two.bin` | `e3 0c 01 02` | decoded `[true]` | `[u1]` | **`[u2]`** |
| `ctl0_arr_elem_one.bin` | `e3 0c 01 01` | `[true]` | `[u1]` | `[u1]` (control) |

The **round trip is unaffected**: Dart re-encodes `e3 0c 01 01` like everyone else, because
the backend normalizes on encode. Only the decoded value differs, which is why every
round-trip gate is green and only the element-access oracle sees it.

## Attribution: generated code

`drivers/dart/build/bin/message.dart` (sofabgen `0.0.0-20260929152859-f8d3ecc3b7ff`,
corelib-dart `8d51a53`):

- **decode** — `onUnsignedArray(204, count)` returns `o.flag_array`, a plain
  `InlineInt64Array(5)` with no range and no boolean handling; the corelib fills it raw.
- **encode** — the same backend emits `_bools01(flag_array)` before `writeUnsignedArray`, so
  it *knows* the field is a boolean array and normalizes one direction only.
- **scalar** — `o.flag = value != 0;` is correct.

That the field is a boolean array is a schema fact; the corelib sees an unsigned array. Siblings
normalize in the visitor (`push(value != 0)` in Rust and C#, `append(..., v != 0)` in Go), which
is what isolates Dart.

## Why nothing else caught it

- The §4.4 family of `sweep_tolerance` asserts `same:` re-encode equality; Dart re-encodes
  correctly, so it passes.
- `materialize.sh` defaults to `corpus/structured`, whose boolean arrays hold only `0`/`1`.
  The defect needs a non-canonical element, which only the fuzzed corpus carries.

Once fixed, the two vectors belong in `corpus/regression` and a non-canonical boolean-array
element belongs in the materialized gate's corpus.
