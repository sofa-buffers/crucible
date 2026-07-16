# F-0010 — under-count fixed array round-trips to different values (pad-to-capacity vs keep-count)

**Status:** open — **spec-underspecification** (candidate MESSAGE_SPEC clarification),
family-wide, not a single-repo bug. Needs triage/decision like F-0001 (truncation)
and F-0004 (UTF-8) before any per-impl issue.
**Found:** 2026-07-16 by the **cross-encode / structured-value oracle**, slice 2
(the array value space, `engine/structured/gen.py`) — on its first run over arrays.
**Axis:** accept_value (round-trip) — the same wire decodes to different values.

## The divergence (a clean 6-vs-6 camp split)

A fixed-count array (schema `count: 5`) that receives **fewer** than 5 elements on
the wire (`0 < wire count < 5`) re-encodes two different ways:

Input `arrays.u32 = [7,8,9]` (wire count 3) — `u32_count3.bin`:

| camp | decodes/re-encodes as | wire | drivers |
|---|---|---|---|
| **pad to capacity** | `[7,8,9,0,0]` (count 5) | `…2305 070809 0000…` | **c, rust-std, rust-nostd, cpp, cpp-c-cpp, zig** |
| **keep wire count** | `[7,8,9]` (count 3) | `…2303 070809…` | **go, py-cython, py-pure, java, typescript, csharp** |

`i16_count1.bin` (`arrays.i16 = [-42]`, count 1) splits the same way. The split is
**along the memory model**: fixed-array storage (systems langs — C `uint32_t[5]`,
Rust `[u32;5]`, C++ `std::array`, Zig) fills the array to its full capacity with the
default and re-encodes all 5; growable storage (managed langs — Go slice, Python
list, Java/C#/TS arrays) keeps the 3 elements it received and re-encodes count 3.

## Boundaries (isolated)

- **count 0** (explicit empty array) → **all agree** (`arr_empty` is in the green
  cross-encode gate): an all-default array is omitted on re-encode by everyone.
- **count == schema (5)** → **all agree** (full arrays are in the green gate).
- **count > schema** → INVALID for scalar arrays (that is F-0003 / generator#100,
  resolved). This is the distinct *under*-count case.

So the divergence is specifically `0 < wire count < schema count`.

## Why it matters / resolution path

An under-count array is a valid wire message (not truncated, not over-count) that
**round-trips to a different value** depending on the decoder's storage model — a
silent interop bug of the exact kind Crucible exists to catch, and one the
malformed-wire fuzzer would not cleanly produce (it needs a well-formed short array).

This is almost certainly a **MESSAGE_SPEC underspecification** rather than one impl's
bug — the spec fixes the array `count` in the schema and defines over-count as
INVALID (§3/§7), but does not say whether an *under*-count array decodes to `N`
elements or to the full schema capacity (default-filled). The two answers fall out
of the two natural storage models. Resolution: a MESSAGE_SPEC clause — most likely
"a fixed array decodes to its schema count, missing trailing elements defaulted"
(the fixed-storage reading, which matches how the schema declares the field), which
would move the managed camp to pad-to-capacity. Track like F-0001/F-0004 (spec-first,
family-wide), not as a scattershot of per-repo issues.

## Reproducers

- `u32_count3.bin` — `56 07 a6 06 23 03 07 08 09 07 07 c6 0c 07` (`arrays.u32=[7,8,9]`)
- `i16_count1.bin` — `56 07 a6 06 1c 01 53 07 07 c6 0c 07` (`arrays.i16=[-42]`)

## Harness note

Kept OUT of the green `corpus/structured/` cross-encode gate (which uses count-0 and
full-count arrays, all green); the under-count vectors live here as the finding —
mirroring how F-0004/F-0009's divergent inputs are kept out of the green gates.
