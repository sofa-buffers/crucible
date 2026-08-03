# F-0011 — go emits an all-default `count:N` array field instead of omitting it (§2)

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.

## The regression

sofabgen 0.17.2 landed the F-0010 fix (generator#136, the §3 fixed-count trailing-default
rule). For **11 of 12** backends this is correct. The **go** backend over-corrected
(commit `684656d`, "fix(go): a count:N array's default is N elements long"): a
**fixed-count (`count:N`) array field whose value is all-element-default (empty)** is now
emitted as an **explicit empty array** (`<header> 00`) instead of being **omitted** per
the MESSAGE_SPEC §2 sparse-default rule.

`empty_arrays.bin` (`5607 a606 5607 07 c60c 07`, no array populated):

| | re-encoded wire |
|---|---|
| **family (11, canonical)** | `5607 a606 560707 c60c 07` (all-default arrays omitted) |
| **go (0.17.2, wrong)** | `5607 a606 0300 0c00 1300 1c00 2300 2c00 3300 3c00 5605 00 20 0d00 4107 07 c60c 07` |

go inserts every `count:5` array as an explicit empty: `03 00` (u8 id0, count 0), `0c 00`
(i8 id1), `13 00` (u16), `1c 00` (i16), `23 00` (u32), `2c 00` (i32), `33 00` (u64),
`3c 00` (i64), then the nested fp-array struct + string array likewise.

## Why it is wrong

MESSAGE_SPEC §2/§3: "Whether the field appears at all is the ordinary ≠-default test of
§2, applied to the full `N`-element value; a schema `default` shorter than `N` stands for
that default padded to `N` with element defaults." These array fields declare **no**
`default`, so the default is the `N`-element all-zero value. An empty/all-zero `count:5`
array **equals its default** → **MUST be omitted** (it reappears on decode via the
`[M,N)` element-default fill). The "explicit empty array, `M=0`" §3 wire form is only for
the case where the `N`-element value differs from a *non-empty* schema `default`.

## Boundaries / cross-checks (go-only, `count:N`-array-specific)

- **Union suite** (schema has no `count:N` arrays) → all 12 incl. go **agree** (green).
- **Limit mode** (`probe-dyn`, *dynamic* count-less arrays) → go **agrees** (green) —
  dynamic arrays are correctly not omitted/trimmed.
- **F-0010 under-count** (`undercount_siblings.bin`, `arrays.u32=[7,8,9]`) → go trims the
  *populated* u32 array to the canonical count 3 correctly (the §3 fix works), but also
  emits the *sibling* all-default arrays as explicit empties. So the trailing-trim half of
  F-0010 is right in go; only the all-default **omission** regressed.

## Relationship to F-0010

F-0010 (under-count pad-vs-keep) is **resolved** by sofabgen 0.17.2 for the trim/pad
question across all 12 backends (see F-0010 NOTES). This finding is the *separate*
regression the same go changeset introduced — the ≠-default omission test, not the
under-count value.

## Reproducers

- `empty_arrays.bin` — `5607 a606 5607 07 c60c 07` (minimal: no array set).
- `undercount_siblings.bin` — `5607 a606 2303 070809 5607 07 c60c 07`
  (`arrays.u32=[7,8,9]`; shows the sibling-array regression alongside the correct u32 trim).

## Harness note

Kept OUT of the green gates (like the other divergent-input findings). The seed +
cross-encode gates are **red on go** until generator#139 lands; the other 11 backends are
green and F-0010 has converged for them.

## Resolution

**Impls:** corelib-go (codegen) · **Axis:** accept_value (round-trip)

✅ **resolved — [generator#139](https://github.com/sofa-buffers/generator/issues/139) fixed in sofabgen 0.17.3** (commit `0713b94`). Short-lived regression: commit `684656d` (0.17.2, while fixing F-0010) made go emit all-default `count:N` arrays explicitly instead of omitting them (§2); go-only. **Re-verified 2026-07-16 (0.17.3):** `empty_arrays` → all 12 omit the arrays; full box green again. Found on the 0.17.2 bump, fixed on the 0.17.3 bump same day
