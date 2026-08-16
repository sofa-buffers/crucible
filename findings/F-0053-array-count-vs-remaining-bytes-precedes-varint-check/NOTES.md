# F-0053 — an array count larger than the remaining bytes short-circuits to `INCOMPLETE` before the element varint is validated

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Issue:** [corelib-go#66](https://github.com/sofa-buffers/corelib-go/issues/66), [corelib-ts#82](https://github.com/sofa-buffers/corelib-ts/issues/82)

**✅ RESOLVED 2026-08-03** — [corelib-go#66](https://github.com/sofa-buffers/corelib-go/issues/66)
and [corelib-ts#82](https://github.com/sofa-buffers/corelib-ts/issues/82) both closed and fixed
(corelib-go#68, corelib-ts#84).

## Resolution

**Impls:** **corelib-go, corelib-ts** · **Axis:** verdict

All 5 reproducers produce **no cluster** against both corelibs' current `main`.
`r1_count11_overlong_elem` is now `R invalid_msg` on all 13 — go and typescript previously said
`I`, folding a malformed message into truncation against §5.2's precedence. The controls hold:
`ctl_count11_enough_bytes` is still `A`, `ctl_count10_same_bytes` and `ctl_bare_overlong` still
`R`. Read out per driver rather than inferred from "0 divergences", since a family-wide
over-rejection would present as the same unanimity.

Both oracles green (`materialize.sh` 108 × 13, 0 divergences, 0/108 C-anchor mismatches).
Reproducers are in the `corpus/regression/` gate as `F0053_*`, controls included, and the camp
signature is deleted from `results/known-clusters.txt`.

**Found 2026-08-03** in the first review of the nightly's accumulated corpus (8512 inputs,
17 camps, 9 of them unexplained). Cluster of **50 inputs**, minimized 25 B → **12 B**.

## The isolate

`43 0b 80 80 80 80 80 80 80 80 80 80` (12 B):

- `43` — field id **8** (undeclared at root), wire type **ARRAY_UNSIGNED** → the field is
  skipped, §5.2;
- `0b` — element count **11**;
- ten bytes, each with the continuation flag set, then end of input.

The element varint therefore **cannot terminate before its eleventh byte**, which exceeds
64 bits and is `INVALID` (CORELIB_PLAN §4.1) — F-0040's rule. The input is *also* truncated, and
§5.2 is explicit that `INVALID` dominates `INCOMPLETE`.

| verdict | drivers |
|---|---|
| `R invalid_msg` (**correct**) | c, cpp, cpp-c-cpp, csharp, dart, java, py-cython, py-pure, rust-no-std, rust-std, zig (11) |
| `I` | **go, typescript** (2) |

## The threshold names the mechanism

Sweeping the declared count against the same ten payload bytes:

```
count:      1  2  3  4  5  6  7  8  9 10 | 11 12 13 14 15
c:          R  R  R  R  R  R  R  R  R  R |  R  R  R  R  R
go:         R  R  R  R  R  R  R  R  R  R |  I  I  I  I  I
typescript: R  R  R  R  R  R  R  R  R  R |  I  I  I  I  I
```

The break is **exactly at 11** — the first count that exceeds the ten bytes on hand, since an
unsigned element is at minimum one byte. So go and typescript are not mis-parsing the varint:
they never look at it. A *"do I have enough bytes for `count` elements?"* pre-check runs first
and returns `INCOMPLETE`, discarding what is already provably malformed.

`ctl_count10_same_bytes` (count 10, identical payload) is unanimous `R`, and
`ctl_count11_enough_bytes` (count 11 with eleven legal one-byte elements) is unanimous — so it
is neither the count nor the bytes alone, but their relation.

## Only in the skip path — and why that is not a mitigation

`ctl_declared_position` puts the same shape at a **declared** array (`arrays.u8`, `count: 5`):
all 13 agree. That is not because the defect is absent there but because the schema `count`
bound fires first — a wire count of 11 against a declared 5 is `INVALID` under §7.1 whatever
happens next, so every implementation rejects for a different reason and the effect is masked.

The bug is therefore reachable exactly where **no schema bound applies**: an unknown field id
(§5.2) or a §7.3-mistyped one. Both are attacker-reachable — forward compatibility means any
decoder must accept ids it does not know.

## Attribution — `corelib-go` and `corelib-ts`

Skipping an unknown field is pure wire mechanics: the corelib reads the count and steps over
`count` varints with no schema knowledge whatsoever (that is what "skip like an unknown id"
means). Generated code is not consulted, so per CLAUDE.md's triage table this sits with the
corelib reader on both impls.

Two independent corelibs sharing one defect is unusual but coherent here: *"bail out early if
the declared count cannot possibly fit"* is an obvious optimisation to reach independently, and
it is only wrong because §5.2 fixes a precedence the optimisation silently inverts.

## Class

The same family as **F-0007 / F-0012 / F-0014 / F-0043**: a check that is correct in isolation
runs before the one §5.2 says must win. What is new is the *trigger* — previous members were
schema-bound checks (`maxlen`, element id, declared width) losing to truncation; here it is a
**count-versus-available-bytes** check, which is not a schema bound at all, beating a **format**
validity rule (§4.1's 64-bit varint ceiling).

## Why no gate caught it

`sweep_varint` covers §4.1 including the overlong forms, and `sweep_framing` covers unknown ids
at array wire types — but no vector combines them: an overlong element *inside* a skipped array
whose count outruns the input. The axes are each correct and the product cell is empty, the same
shape as F-0044 (unknown id × sequence-with-children) and F-0048 (repeated id × wrapper element).
`docs/TODO.md` carries the follow-up.
