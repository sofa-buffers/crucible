# G-0044 — the sofabgen Dart backend decodes `array of boolean` into raw integers: a non-zero element other than `1` is not normalized to `true`

**Status:** ✅ **RESOLVED** 2026-09-30 by **[generator#616](https://github.com/sofa-buffers/generator/issues/616)** (closed the day after it was filed), which needed a corelib change — verified here against `sofabgen 0.0.0-20260930053019-415c6cf6ab5f` with `corelib-dart@ed78b11`: the materialized differential over `corpus/regression` (261 inputs × 17 drivers, including the three vectors below) shows 0 divergence, and the generated field is now `InlineInt64Array(5, range: sofab.ElemRange.boolean)`. — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns the state, this file is the evidence.
**Guard:** corpus/regression — the vectors in this folder promoted 2026-09-30 as `G0044_*`, **and** a materialized-value pass over that corpus (`replay.yml`: `CORPUS=corpus/regression ./scripts/materialize.sh`). The second half is what makes the first one a guard: `run.sh` compares the re-encode, which was already correct.
**Issue:** [generator#616](https://github.com/sofa-buffers/generator/issues/616) (filed 2026-09-29)
**Corelib:** `corelib-dart` `702400d` — *"hold a boolean array's elements as 0/1 on decode (`ElemRange.boolean`)"*. The fix was a pair: the corelib gained the destination range, the generator asks for it. The separate question of a dedicated boolean *read* function in `corelib-dart` (§4.4) is not part of this finding.

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
- `materialize.sh` defaulted to `corpus/structured`, whose boolean arrays hold only `0`/`1`.
  The defect needs a non-canonical element, which only the fuzzed corpus carried — found by the
  nightly's merged corpus, not by any gate.

## Resolution and guard

Both sides moved within a day: `corelib-dart@702400d` added `ElemRange.boolean` (an array target
that holds its elements as `0`/`1`), and the generator emits it for a boolean array. The three
reproducers are now `corpus/regression/G0044_*` (`r0` element `2`, `r1` five elements
`[48,0,0,48,48]`, and the `1` control). Because the round trip was never the problem, the guard is
the materialized pass over that corpus, added to `replay.yml` beside the existing one over
`corpus/structured`.
