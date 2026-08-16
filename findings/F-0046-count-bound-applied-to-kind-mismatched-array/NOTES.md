# F-0046 — the schema `count` bound is applied to an array whose wire **kind** §7.3 says to skip


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Found 2026-08-01** by delta-minimizing cluster 6 of the 3-hour pacemaker round
(corelibs **0.10.0** + sofabgen **0.22.0**): **70 bytes → 5 bytes**.

The same ordering defect as **F-0042**, one level up. F-0042 was about the fixlen element
**subtype** (an fp32 array meeting a declared fp64 array) and is resolved — the corelib hook
widened and generator#259 consumed it. This is the array **kind** (`ARRAY_FIXLEN` arriving at
a field declared `ARRAY_SIGNED`), which that fix did not reach.

## The isolate

`mistyped_fixlen_array_overcount.bin` = `a6 06 0d 7f 20`

| bytes | meaning |
|---|---|
| `a6 06` | id **100** `SEQ_BEG` — the `arrays` struct |
| `0d` | id **1**, wire type `ARRAY_FIXLEN`. Field 1 of `arrays` is `i8[]` → `ARRAY_SIGNED`. A §7.3 **kind** contradiction, so the field **MUST be skipped** |
| `7f` | element count **127** — above the schema `count: 5`, but that bound belongs to a field this header is not |
| `20` | `fixlen_word`: subtype fp32, length 4. The message ends here — truncated |

| verdict | drivers |
|---|---|
| `I` (**correct** — the field is skipped, the message is merely truncated) | c, cpp, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, typescript, zig (11) |
| `R invalid_msg` | **rust-std, rust-no-std** (2) |

## Three controls pin it to exactly "skippable **and** over the bound"

| control | bytes | result | what it establishes |
|---|---|---|---|
| `ctl_count_within_bound` | `a6 06 0d 05 20` | **all 13 `I`** | with a count *within* `count: 5` the same mistyped array is skipped everywhere — so it is the bound being applied, not the kind mismatch itself |
| `ctl_welltyped_overcount` | `a6 06 0c 7f 07` | **all 13 `R invalid_msg`** | a *correctly typed* `ARRAY_SIGNED` with count 127 **is** INVALID on all 13 — the bound is right where it applies, so this is not about over-count detection being wrong |
| `ctl_mistyped_complete_inbounds` | `a6 06 0d 01 20 00 00 00 00 07` | **all 13 `A`** | the §7.3 skip path itself works: a complete, in-bounds mistyped fixlen array is skipped and the message round-trips |

The divergence needs **both** conditions at once — the header is skippable under §7.3 *and*
its count exceeds the declared field's bound. That is precisely the ordering F-0042 settled.

## Spec basis

MESSAGE_SPEC §7.3, **"Against a schema bound, this clause wins"**:

> the subtype is therefore decided first and the schema bound applied only to a field that
> survives it

and the clause it rests on:

> a decoder … **MUST NOT** decode its payload into the declared field

CORELIB_PLAN §4.8 gives the decode order for a fixlen array — count (format ceiling only, no
allocation) → `fixlen_word` → §7.3 skip **without** applying the schema `count` → bound only
for a survivor. §7.3's rationale says why: enforcing the bound first would make the verdict
depend on the count of *a field that is not the declared field's value*. `count: 5` belongs to
`arrays.i8`; this header is not `arrays.i8`.

## Attribution — generated code

`count: 5` is a schema fact, so per CLAUDE.md's triage this is `generator`. The corelib
reports `array_begin(id=1, kind=Fixlen, count=127)` faithfully; what varies is whether the
generated code consults the declared field's bound before or after deciding the header is not
that field's.

Note the camp: **only rust-std and rust-no-std**. Every other backend — including zig, which
shares the flat-visitor strategy — already orders it correctly, so this is a per-backend
ordering slip rather than a design gap.

## Repro

```
CORPUS=findings/F-0046-count-bound-applied-to-kind-mismatched-array ./scripts/run.sh
```

## Resolution

**Impls:** generator (**rust-std, rust-no-std**; codegen) — every other backend, zig included, already orders it correctly, so a per-backend slip rather than a design gap · **Axis:** verdict

✅ **RESOLVED 2026-08-02** — generator#271 fixed and closed the same day it was filed. the schema `count` is no longer applied to an array whose wire kind §7.3 says to skip. **Re-verified** on the post-fix family (sofabgen `0.0.0-20260802183113-4865f8515430`, corelibs @ main): all vectors converge across 13 drivers, and the verdict *direction* was checked, not just agreement. Reproducers promoted into the green `corpus/regression/` gate (117 → 160 inputs). *Original report:
