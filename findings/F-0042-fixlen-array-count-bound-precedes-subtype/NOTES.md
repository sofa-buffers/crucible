# F-0042 — the schema `count` bound is applied before the fixlen subtype decides the field is skippable

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Issue:** [go#58](https://github.com/sofa-buffers/corelib-go/issues/58), [java#53](https://github.com/sofa-buffers/corelib-java/issues/53), [cs#45](https://github.com/sofa-buffers/corelib-cs/issues/45)

**Assigned 2026-07-29.** This finding did not previously exist in Crucible's catalog: the
divergence was tracked from 2026-07-25 in
[generator#232](https://github.com/sofa-buffers/generator/issues/232) only, first as an open
*spec question* and then as an implementation gap. It is filed here now so the split has a
reproducer set and a row like every other finding.

**Filed 2026-07-29 against the seven corelibs**, each scoped to the rows that reproduce there:
[corelib-go#58](https://github.com/sofa-buffers/corelib-go/issues/58),
[corelib-java#53](https://github.com/sofa-buffers/corelib-java/issues/53),
[corelib-cs#45](https://github.com/sofa-buffers/corelib-cs/issues/45),
[corelib-dart#23](https://github.com/sofa-buffers/corelib-dart/issues/23),
[corelib-rs-no-std#60](https://github.com/sofa-buffers/corelib-rs-no-std/issues/60) (rows 2+4);
[corelib-rs#40](https://github.com/sofa-buffers/corelib-rs/issues/40),
[corelib-zig#27](https://github.com/sofa-buffers/corelib-zig/issues/27) (row 2 only — their hook
already fires past the `fixlen_word`, which is why row 4 is correct in both). generator#232 was
**closed as misfiled**: it sat in a repo that cannot make the change.

**Measured 2026-07-29** on the first fully-merged sparse-array family — corelibs **0.9.0 @
main**, sofabgen **0.21.0** — across the full 13-driver roster.

## The rule, now that the spec has ruled

CORELIB_PLAN §4.8 (landed on `main` with documentation#30, in `8087f1d`) states the decode
order for a fixlen array, and MESSAGE_SPEC §7.3 cross-references it:

1. read `element_count`, enforcing only the **format** ceiling `ARRAY_MAX`, allocating nothing;
2. read the `fixlen_word` (subtype + per-element length);
3. a **contradicting subtype** means skip the field per §7.3 — and the schema `count`
   **MUST NOT** be applied, because the field was never this array's value;
4. only a field that survives step 3 gets the schema bound (`element_count > count` → INVALID).

with two consequences called out as intended: truncation **between the two words** is
`INCOMPLETE`, not `INVALID`, and the format ceiling still fires on the count word.

This is what makes the issue actionable — it was blocked on "which rule wins" until the clause
landed.

## The six vectors

All at `arrays` (id 100) → `nested` (id 10) → id 0, declared `array<fp32, count 5>`.
`20` = `fixlen_word` for fp32 (4 B), `41` = fp64 (8 B) — the contradicting subtype.

| # | vector | wire | §4.8 says | measured |
|---|---|---|---|---|
| 1 | `r1_incount_mistyped` | count 3 ≤ 5, **fp64** | skip → `A`, field stays `[]` | **11 correct**; **java, csharp** emit `a6 06 56 05 03 20 …` — a 3-element zero array in the declared field |
| 2 | `r2_overcount_mistyped` | count 8 > 5, **fp64** | skip → `A` (step 3: bound not applied) | **6 correct** (c, cpp, cpp-c-cpp, py-cython, py-pure, typescript) · **7 reject** `R invalid_msg` (csharp, dart, go, java, rust-std, rust-nostd, zig) |
| 3 | `r3_overcount_matching` | count 8 > 5, fp32 | `INVALID` (step 4) | all 13 `R invalid_msg` ✅ |
| 4 | `r4_trunc_between_words` | count 8, EOF before the `fixlen_word` | `INCOMPLETE` | **8 correct** (`I`) · **5 reject** `R invalid_msg` (csharp, dart, go, java, rust-nostd) |
| 5 | `r5_overcount_matching_nopayload` | count 8 > 5, fp32, EOF | `INVALID` | all 13 `R invalid_msg` ✅ |
| 6 | `r6_ctl_valid` | count 3, fp32, full payload | accept, round-trip | all 13 `A`, byte-identical ✅ |

Rows 3, 5 and 6 being unanimous is what makes this precise: the bound itself, its
truncated form, and the happy path are all implemented correctly everywhere. Only the
**ordering** against the subtype splits the roster — rows 2 and 4 — and row 1 is a distinct
defect that happens to sit in the same hook.

Note rust-std's position differs between rows 2 and 4 (rejects row 2, correct on row 4), so
the two rows are not one switch.

## Attribution: corelib (the array header hook cannot see the subtype)

Established in generator#232 and unchanged by the 0.21.0 refactoring. Seven corelibs deliver
the array header hook *before* the `fixlen_word`, or without the subtype in it, so generated
code cannot express "skip first, bound second" at all:

| corelib | hook | fires | subtype visible |
|---|---|---|---|
| corelib-go | `ArrayBegin(id, count)` | after the count word | no |
| corelib-java | `arrayBegin(id, ArrayKind, count)` | after the count word | no |
| corelib-cs | `ArrayBegin(id, ArrayKind, count)` | after the count word | no |
| corelib-dart | `onArrayBegin(id, count)` | after the count word | no |
| corelib-rs-no-std | `array_begin(id, ArrayKind, count)` | after the count word | no |
| corelib-rs | `array_begin(id, ArrayKind, count)` | after the fixlen word | no (`ArrayKind::Fixlen`) |
| corelib-zig | `arrayBegin(id, ArrayKind, count)` | after the fixlen word | no (`.fixlen`) |

The fix is to widen the hook with the fixlen element subtype (and, for the first five, move it
past the `fixlen_word`); the generator then emits the same subtype-first guard it already emits
for a scalar bounded fixlen field. Both generator-only workarounds were measured and rejected
in the issue — each trades this split for a different one on rows 3/5.

## Row 1 is F-0039, not this finding

The java/csharp behaviour in row 1 — sizing the declared field from the count of a header that
is being skipped — is the same defect as **[F-0039](../F-0039-mistyped-array-allocates-declared-field/NOTES.md)**
([generator#254](https://github.com/sofa-buffers/generator/issues/254), G-0023), which was found
independently the same day through the §7.3 wiretype sweep with an `ARRAY_SIGNED` header at a
`u8[]` slot. This is its fixlen-array face: same `arrayBegin` allocation block, same two
backends. It is codegen; rows 2 and 4 are corelib. Keeping them apart is what keeps each issue
fixable on its own.

## Resolution

**Impls:** **corelib** — 7 on row 2 (csharp, dart, go, java, rust-std, rust-nostd, zig), 5 on row 4 (csharp, dart, go, java, rust-nostd); the array header hook fires before the `fixlen_word` or omits the subtype, so generated code cannot express the order at all · **Axis:** verdict

✅ **RESOLVED 2026-08-01** — all seven corelib issues closed 2026-08-01 ([go#58](https://github.com/sofa-buffers/corelib-go/issues/58), [java#53](https://github.com/sofa-buffers/corelib-java/issues/53), [cs#45](https://github.com/sofa-buffers/corelib-cs/issues/45), [dart#23](https://github.com/sofa-buffers/corelib-dart/issues/23), [rs#40](https://github.com/sofa-buffers/corelib-rs/issues/40), [rs-no-std#60](https://github.com/sofa-buffers/corelib-rs-no-std/issues/60), [zig#27](https://github.com/sofa-buffers/corelib-zig/issues/27)) — the array-header hook now carries the fixlen element subtype, consumed by the backends in [generator#259](https://github.com/sofa-buffers/generator/issues/259). **Re-verified 2026-08-01** against corelibs **0.10.0** + sofabgen **0.22.0**: all six vectors converge on all 13. Promoted into the regression gate as `F0042_*.bin`; the two carved-out `wiretype_sweep` cells are blocking again
