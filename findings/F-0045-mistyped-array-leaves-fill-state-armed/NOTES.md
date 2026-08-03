# F-0045 — a §7.3-skipped array leaves the fill state armed, so the *next* scalar is absorbed into an array


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-08-01** by delta-minimizing cluster 15 of the 3-hour pacemaker round
(corelibs **0.10.0** + sofabgen **0.22.0**): **468 bytes → 8 bytes**.

## The isolate

`mistyped_array_then_scalar.bin` = `a6 06 0b 01 04 00 00 07`

| bytes | meaning |
|---|---|
| `a6 06` | id **100** `SEQ_BEG` — the `arrays` struct |
| `0b 01 04` | id **1**, wire type `ARRAY_UNSIGNED`, count 1, element 4. Field 1 of `arrays` is `i8[]`, declared **ARRAY_SIGNED** — a §7.3 wire-type contradiction, so it **must be skipped** |
| `00 00` | id **0**, a bare **unsigned scalar**, value 0. Field 0 of `arrays` is `u8[]` |
| `07` | `SEQ_END` |

All 13 **accept**; they disagree on the value:

| camp | re-encodes to | drivers |
|---|---|---|
| both fields dropped (**correct**) | *(empty)* | c, cpp, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, typescript (10) |
| the scalar is absorbed → `arrays.u8 = [0]` | `a6 06 03 01 00 07` | **rust-std, rust-no-std, zig** (3) |

## Three controls — each one green, which is the whole point

| control | bytes | result |
|---|---|---|
| the mistyped array **alone** | `a6 06 0b 01 04 07` | **all 13 agree** — the §7.3 skip itself is correct |
| the bare scalar **alone** | `a6 06 00 00 07` | **all 13 agree** — F-0022's fix holds; a scalar at an array field is skipped |
| a **well-typed** array then the same scalar | `a6 06 0c 01 04 00 00 07` | **all 13 agree** — a correct array does not leave the state armed |

So neither construct diverges on its own, and a *correctly typed* array followed by the same
scalar is fine. Only the **sequence** mistyped-array → scalar breaks, which makes this a
**state-leak across fields**, not a per-field decode bug.

## Root cause — `array_begin` arms the fill on the kind *family*, not the declared kind

`drivers/rust/build/rs/src/message.rs:500`:

```rust
self.afill = match kind {
    ArrayKind::Unsigned | ArrayKind::Signed => match (self.cur, id) {   // <-- both kinds, one arm
        (_Loc::Root_arrays, 0) => count,
        (_Loc::Root_arrays, 1) => count,
        ...
        _ => 0,
    },
```

`afill` is the counter generator#188 introduced for F-0022: the scalar handlers only store
when a real array is in progress —
`(_Loc::Root_arrays, 0) => { if self.afill == 0 { return; } self.afill -= 1; … }` (line 377).

The arming arm lumps `Unsigned | Signed` together and keys only on `(scope, id)`. An
`ARRAY_UNSIGNED` at id 1 (declared **signed**) therefore arms `afill = 1` for a field §7.3
says to skip. Its own element is *not* stored — the unsigned element handler has no arm for
id 1 (that id lives in the signed handler, line 392) — so `afill` is never decremented and
stays at **1**. The next field, the bare scalar at id 0, then passes `if self.afill == 0`
and is pushed as a one-element array.

`askip` immediately above has the same lumping (`_Loc::Root_arrays, 1 => 0`), so the mistyped
array is not skipped there either.

Zig is character-for-character the same shape, `drivers/zig/build/src/message.zig:415`:

```zig
self.afill = switch (kind) {
    .unsigned, .signed => switch (self.cur) {
        .root_arrays => switch (id) { 0 => count, 1 => count, ... },
```

## Attribution — generated code, and a known defect shape

Schema facts only (which id is declared signed vs unsigned), so per CLAUDE.md's triage this
is `generator`. The corelib faithfully reports `array_begin(id=1, kind=Unsigned, count=1)`.

**This is the rust/zig analogue of G-0023** (F-0039), where *"the java and csharp backends …
`arrayBegin` lumps `UNSIGNED`/`SIGNED` into one skip-arm case and allocates the destination
regardless of the wire kind"*. That was fixed for java/csharp in generator#254 — which is
exactly why java and csharp are in the **correct** camp here and rust/zig are not. Same
lumping, different state variable: allocation there, `afill` here.

**The fix:** key the `afill` (and `askip`) arms on the field's **declared** array kind, not on
`Unsigned | Signed` jointly — the same change #254 made to the allocation arm. Affected:
**rust-std, rust-no-std, zig**.

## Spec basis

MESSAGE_SPEC §7.3: a field whose header wire type contradicts its declared type **MUST** be
skipped *"exactly as a field with an unknown id is skipped"*, and a decoder **MUST NOT**
decode its payload into the declared field. Arming a fill counter from such a header is
decoding a consequence of it — and here it corrupts a **different, later** field, which is
strictly worse than the mis-decode §7.3 forbids.

## Repro

```
CORPUS=findings/F-0045-mistyped-array-leaves-fill-state-armed ./scripts/run.sh
```
