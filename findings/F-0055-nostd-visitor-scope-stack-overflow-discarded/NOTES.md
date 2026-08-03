# F-0055 — the no-std visitor's scope stack holds 8 entries, and its overflow is discarded — a field after the unwind is **silently lost**


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**✅ RESOLVED 2026-08-03** — [generator#283](https://github.com/sofa-buffers/generator/issues/283)
fixed by `bd67d2b`, *"stack only live scopes, so a deep skip can't lose"*.

## Resolution

**Impls:** generator (sofabgen **no-std backend**) — **G-0035** · **Axis:** accept_value

Verified on sofabgen `0.0.0-20260803165303-bd67d2b2f84c`, the **first artifact carrying the fix**
— the preceding build was 67 minutes older, so a sweep run shortly before still showed the camp.
A closed upstream ticket was explicitly not treated as a resolution here; the isolate was.

All 5 reproducers agree across 13 drivers, and the values are the point: rust-no-std re-encodes
`5602200000c03f07` (`nested.f32 = 1.5`) where it previously returned the **empty message**, and
`r3_depth9_wrapper_lost` yields `c60c020a4107`. Both controls (`ctl_depth8_ok` at the capacity
boundary, `ctl_no_nesting`) are unchanged.

The verdicts were read out per driver rather than inferred from "0 divergences". For a silent-loss
defect that check is not optional: had the fix gone the other way and *every* implementation
returned the empty message, the differential oracle would have reported the same unanimous
agreement. `materialize.sh` is 108 × 13 with 0 divergences and 0/108 mismatches against the C
anchor.

Reproducers promoted to the green `corpus/regression/` gate as `F0055_*`, both controls included,
and the camp signature is deleted from `results/known-clusters.txt` so a regression reports as
NEW.

**Found 2026-08-03** while triaging the two large `rust-nostd`-only camps from the nightly
corpus. Reached by reading the generated source after four black-box hypotheses had been
refuted; isolated to **24 bytes**.

## The defect

Generated `src/message.rs`, no-std backend:

```rust
stack: heapless::Vec<_Loc, 8>,
...
fn sequence_begin(&mut self, id: Id) {
    let _ = self.stack.push(self.cur);      // <-- capacity 8, and the Result is discarded
    self.cur = match (self.cur, id) { … _ => _Loc::Dead };
}
fn sequence_end(&mut self) {
    self.cur = self.stack.pop().unwrap_or(_Loc::Root);
}
```

Two problems in one line:

1. **Capacity 8.** CORELIB_PLAN §6.2 sets `MAX_DEPTH` to **255**. A message nested 9 deep is
   perfectly legal and the visitor cannot track it.
2. **The overflow is thrown away.** `heapless::Vec::push` returns a `Result`; `let _ =` drops
   it. Past eight entries the push silently does nothing, the matching `pop` then restores the
   *wrong* scope, and `cur` ends up somewhere it never was.

## The symptom is data loss, not a reject

`r1_depth9_field_lost.bin` (24 B) — open `nested` (id 10), open and close **8** unknown
sequences inside it, then set `nested.f32 = 1.5`, close:

| result | drivers |
|---|---|
| `A` → `56 02 20 00 00 c0 3f 07`, i.e. `nested.f32 = 1.5` | c, cpp, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, rust-std, typescript, zig (12) |
| `A` → **empty** — the field is gone | **rust-no-std** |

No error, no rejection: the message is accepted and a field the sender wrote has vanished.
`r2_depth20_field_lost.bin` shows the same at depth 20.

## The threshold is exactly the capacity

```
inner unknown levels:  4  5  6  7 | 8  9 10 11 12
c:                     ok ok ok ok | ok ok ok ok ok
rust-no-std:           ok ok ok ok | LOST LOST LOST LOST LOST
```

`nested` + 8 inner levels = **9 pushes** against a stack of 8. `ctl_depth8_ok.bin` (7 inner
levels, exactly at capacity) is unanimous, and `ctl_no_nesting.bin` confirms the field itself
is fine.

## Why an earlier depth test missed it

Nesting **only** unknown sequences and then unwinding is unaffected — verified to depth 14. With
every scope `_Loc::Dead`, the dropped pushes are the deepest ones, and the surplus pops return
`unwrap_or(_Loc::Root)`, which happens to be the correct final scope. The corruption needs a
**real scope underneath the overflow** — that is what `nested` provides here, and it is why
F-0050's depth vectors (255/256 nesting, no field set) agree across all 13.

## Attribution — generator (sofabgen **no-std backend**)

The stack, its capacity and the discarded `Result` are all in generated code. corelib-rs-no-std
delivers `sequence_begin` / `sequence_end` faithfully; nothing in the corelib knows or bounds
the visitor's scope stack.

Corroborated by `rust-std`, which is **correct**: same schema, same generator, different
backend — the std one uses a growable `Vec`. A split between two profiles of one language
indicts the generated container (CLAUDE.md heuristic 3), and here the container is literally the
difference.

## Fix

Either is sufficient, and they are not exclusive:

- size the stack to `MAX_DEPTH` (255) rather than 8, and/or
- stop discarding the overflow — the visitor already carries an `err` flag (it is what turns
  into `Error::BufferFull`), so `if self.stack.push(self.cur).is_err() { self.err = true; }`
  would at least surface the condition instead of corrupting the value.

Silently returning a wrong value is the worst of the three possible outcomes; even a spurious
error would be an improvement.

## Relation to the two large camps

This was found while chasing `7f7060b8` (22 inputs, 1247 B) and `8e989f1f` (1 input, 3861 B),
where `rust-no-std` alone **rejects**. Both are large, deeply nested and repetitive, so the same
overflow is the likely mechanism — a desynchronised `cur` can land on a scope whose next field
trips `inv`, which would present as `R invalid_msg`. **That link is not proven**: what is proven
here is the silent-loss form. The two camps stay open in `docs/TODO.md` until one of them is
minimized to a vector that demonstrates the reject path directly.
