# F-0048 — a repeated **wrapper-array element id** is appended to, not replaced, on `rust-no-std` — surfacing as a spurious `buffer_full`


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-08-02** by triaging **cluster 4** of the 2026-08-02 re-cluster (= cluster 5 of
the 2026-08-01 snapshot), the last untriaged cluster of that round: **305 bytes → 11 bytes**.

The cluster was carried in `docs/TODO.md` as an open question — *legal constrained-profile
bound (CORELIB_PLAN §6), or a finding?* It is **a finding**, and the `buffer_full` verdict
that made it look like a capacity bound is a **misfire**: no capacity is ever exhausted.

## What the cluster actually was

8 inputs (305–332 B), all decoding — per the other 12 impls — to a `string_array` of **three
short elements**, comfortably inside `count: 5` and `maxlen: 64`. They are long because they
write the **same element ids over and over**; under MESSAGE_SPEC §7.4 the last occurrence
wins, so the value stays small. `rust-no-std` alone rejected them `buffer_full`.

Those 8 were the *only* `buffer_full` verdicts in the entire 5306-input corpus.

## The mechanism

Generated `src/message.rs` (no-std backend) assembles chunked payloads in `acc` and dispatches
the sink **once per complete string** (lines 442–449), so each sink arm receives a whole
value. Three arms write strings; only one of them omits the reset:

| line | sink | code | correct? |
|---|---|---|---|
| 451 | `nested.str` (scalar) | `str.clear(); str.push_str(_s)` | ✅ replaces |
| 453 | `struct_array[i].v` | `v.clear(); v.push_str(_s)` | ✅ replaces |
| **452** | **`string_array[id]`** | **`_e.push_str(_s)`** — no `clear()` | ❌ **appends** |
| **475** | **`blob_array[id]`** | **`_e.extend_from_slice(_b)`** — no `clear()` | ❌ **appends** |

The **rust-std** backend gets the same position right — `self.m.string_array[id as usize] =
_s;` (assignment). So this is a split *inside one language*, between two profiles generated
from one schema: the classic signal that the generated container is at fault, not the corelib.

### Why the symptom is `buffer_full` and not a wrong value

Each arm guards its write with a capacity check that presumes the destination was empty:

```rust
let _ = _e.push_str(_s);
if _e.len() != _s.len() { self.err = true; }   // -> Error::BufferFull
```

With the `clear()` missing, the **second** occurrence of an id makes `_e.len()` the running
total while `_s.len()` is only the latest value, so the guard trips on any duplicate id —
**regardless of capacity**. `r1` is 11 bytes and accumulates 4 bytes into a `String<64>`: no
overflow is possible, and it still rejects.

That guard is what keeps the underlying §7.4 violation from being a silent value bug: every
concatenation that would corrupt the value also trips it. Fixing the guard **without** adding
the `clear()` would convert this verdict bug into a data-corruption bug — the fix is the
`clear()` (or `= _s`), matching lines 451/453 and the std backend.

## The reproducers

**`r1_string_elem_written_twice.bin`** = `c6 0c 02 12 41 42 02 12 43 44 07` (11 B) —
`string_array` opened; element 0 written `"AB"`, then element 0 written `"CD"`; end.

| verdict | drivers |
|---|---|
| `A` → `c60c0212434407`, i.e. `string_array[0] = "CD"` (**correct**, §7.4 last-wins) | c, cpp, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, rust-std, typescript, zig (12) |
| `R buffer_full` | **rust-no-std** |

**`r3_blob_elem_written_twice.bin`** = `ce 0c 02 13 41 42 02 13 43 44 07` (11 B) — the blob
twin (line 475). Same 12-vs-1 split, confirming both arms carry the defect.

**`r2_string_elem_overflow_by_repeat.bin`** (163 B) — element 0 written `"AB"` forty times.
The shape the fuzzer actually found; same verdict as `r1`, which is the point: 4 accumulated
bytes and 80 accumulated bytes fail identically, so capacity is not the trigger.

## Controls (all unanimous across 13)

| control | what it isolates |
|---|---|
| `ctl_string_elem_written_once` | one write to element 0 — the write path itself is fine |
| `ctl_blob_elem_written_once` | same for blob |
| `ctl_string_two_distinct_elems` | elements 0 **and** 1 written once each — two writes are fine when the **ids differ**, so it is the repeat, not the count |
| `ctl_scalar_string_written_twice` | `nested.str` written twice — that arm **has** the `clear()`, so a repeated *scalar* string is handled correctly. Proves the defect is specific to the wrapper-array element sink |

Together these pin the axis to exactly one thing: **a repeated element id inside an array
wrapper**.

## Spec basis

MESSAGE_SPEC **§7.4** (verified at documentation `70f9123`, the tip):

> Ids are unique within a sequence scope … so an encoding that repeats one is **not
> well-formed** and producers **MUST NOT** emit it. A decoder **MUST** nevertheless process it
> deterministically, and **MUST NOT** report it as `INVALID`. … For each field id in a scope,
> the **last** occurrence applies.

Two independent violations by `rust-no-std`:

1. the last occurrence does **not** apply — earlier ones are concatenated onto it; and
2. the input is reported as an error, where the clause says a decoder **MUST NOT** reject it.

`buffer_full` is not `INVALID`, but it is still a rejection of input the clause requires be
processed deterministically. Note §7.4 concerns a repeated **field id in a scope**; an array
wrapper's *elements* are ids in the wrapper's scope (§5.1 — each element carries its own
`(id, type)` header), so the clause binds here directly.

## Attribution — generated code (`generator`, no-std backend), **G-0032**

Per CLAUDE.md's triage rule, the question is which side had the information to get it right:

- The **corelib** hands the visitor `(id, total, offset, chunk)` and is schema-agnostic by
  design — it has no idea `string_array` is a bounded wrapper, nor which occurrence is last.
  It delivered every byte faithfully; `src/istream.rs` is not implicated.
- The **generated** visitor owns the destination container, its capacity, and the
  assign-vs-append decision. Its own sibling arms (451/453) and its own std counterpart do it
  correctly.

This is heuristic 3 from CLAUDE.md — a split between two profiles of one language indicts the
generated container — and it is the same shape as **F-0013** and **F-0010**.

The fix is one line per arm: `_e.clear()` before the append (or assignment, as std does), at
generated `message.rs` lines 452 and 475 — i.e. in the no-std backend's wrapper-array element
sink template, for both the string and blob element paths.

## Why no gate caught it

No existing vector writes the same wrapper-array element id twice. **F-0019** established the
duplicate-id axis and MESSAGE_SPEC §7.4, but its vectors repeat a *sequence* id
(`nested`, `arrays`) and an array **wrapper** id — never an **element** id *inside* a wrapper.
That is the untested cell, and it is the second time a §7.4 blind spot has produced a finding
here. `docs/TODO.md` carries a sweep-axis item to close it.
