# F-0025 — a scalar fp field receiving an fp (fixlen) array wire type

**Status:** ✅ **RESOLVED — [generator#193](https://github.com/sofa-buffers/generator/issues/193) fixed & closed**
(post-0.19.4 sofabgen; verified 2026-07-22 on the CI build `0.0.0-20260722065611-f61a29b31c01`).
MESSAGE_SPEC §7.3 requires the field to be **skipped**; five backends were decoding the array's element
into the scalar. **Generator-only** (rust-std / rust-nostd / csharp / java / zig backends), the
**fp analogue of F-0021** — which [generator#183](https://github.com/sofa-buffers/generator/issues/183)
(0.19.3) fixed for **integer** arrays only. The fix arms the discard counter (`askip`) for the fp
array kinds in `arrayBegin` and adds the `askip` guard to the `fp32()`/`fp64()` callbacks (mirroring
#183/#188), so a scalar fp field fed an fp fixlen array now **skips** it. **Verified:** both reproducers
→ **all 12 skip** (re-encode to `5607a606560707c60c07ce0c07`); the wire-type (§7.3) sweep is green
(319 vectors, 0 divergences) and is now **blocking**; the 2 reproducers + 2 controls are in the
`corpus/regression/` gate (`F0025_*`). **Axis:** accept_value (accept-with-wrong-value vs skip). **Found:**
2026-07-21 by the wire-type sweep (`engine/structured/wiretype_sweep.py`) — the one residual after
F-0022/F-0023 were resolved in 0.19.4. **Resolved:** 2026-07-22.

## The residual after the §7.3 fixes landed

0.19.4 closed the §7.3 gaps at three positions — struct fields (F-0020), the array-fill arm
(F-0022, generator#188), and the string-array wrapper loop (F-0023, generator#189). A full wire-type
sweep of every field position × every construct then leaves **2 of 297 vectors** still divergent —
both one shape:

> a **scalar fp field** (`nested.f32` / `nested.f64`) receiving an **fp fixlen array**
> (`fp32[]` / `fp64[]` wire type, i.e. ArrayFixlen) of the same element type.

| camp | behaviour | drivers |
|---|---|---|
| **skip** (conformant §7.3) | field stays default | c, go, cpp, cpp-c-cpp, py-cython, py-pure, typescript (7) |
| **decode the element into the scalar** | `nested.f32 = 1.5` | **rust-std, rust-nostd, csharp, java, zig (5)** |

This is the **same five** as F-0021 (the shared-callback backends), the **same direction** (a
scalar field catching an array element), differing only in element type: F-0021 was integer
(`u8…u64` ← ArrayUnsigned, `i8…i64` ← ArraySigned), this is fp (`f32`/`f64` ← ArrayFixlen).

## The reproducer, byte for byte

`f32_recv_array_fp32.bin` = `56 05 01 20 0000c03f 07`:

| bytes | meaning |
|---|---|
| `56` | header `(id 10, WT_SEQ_BEG=6)` — open the `nested` struct |
| `05` | header `(id 0, WT_ARR_FIX=5)` — an **ArrayFixlen** at id 0, whose declared field `nested.f32` is a **scalar Fixlen** (WT_FIX=2) |
| `01` | array count = 1 |
| `20` | fixlen word `(width 4 << 3) | FP32` |
| `0000c03f` | fp32 payload `1.5` (0x3fc00000 LE) |
| `07` | WT_SEQ_END — close `nested` |

Wire type ArrayFixlen (5) ≠ the field's declared Fixlen (2), so §7.3 (documentation#23) requires
the field to be treated as unknown and **skipped**. The seven that skip re-encode the all-default
message (`5607a606560707c60c07`); the five store `nested.f32 = 1.5` and re-encode
`5602200000c03f…`. `f64_recv_array_fp64.bin` = `56 0d 01 41 …f83f 07` is the fp64 analogue at id 1.
Conformance (accept-vs-reject) **agrees** — all 12 accept, as a message with one skipped unknown
field is valid — so the split is purely on the **value**, exactly F-0021's axis.

## Why exactly these five — the same double gap as F-0021, un-extended to fp

The five deliver an array **element-by-element through the same callback used for a lone scalar**,
with `arrayBegin(id, kind, count)` announced first (the delivery design F-0021 documents and does
not change — it is streaming / zero-alloc, which rust-no-std and zig depend on). generator#183
armed a discard counter (`askip`) for that, but **scoped it to integer array kinds and the
integer callbacks only**. Two independent halves both miss fp:

**1. `arrayBegin` arms `askip` only for `Unsigned | Signed` array kinds — never `Fixlen` (fp).**

| backend | site | evidence |
|---|---|---|
| corelib-rs / -no-std | `message.rs:368` | `self.askip = match kind { ArrayKind::Unsigned \| ArrayKind::Signed => …, _ => 0 };` — the `Float`/`Fixlen` arm is `_ => 0` |
| corelib-java | `message.java:299` | `if (kind == ArrayKind.UNSIGNED \|\| kind == ArrayKind.SIGNED) { askip = count; … } else if (kind == ArrayKind.FIXLEN) { … afill … }` — the FIXLEN branch sets only `afill`, never `askip`. Its own comment: *"an **integer array** delivered at an id…"* |
| corelib-cs | `message.cs:281` | `askip = (kind == ArrayKind.Unsigned \|\| kind == ArrayKind.Signed) ? … : 0;` — the `ArrayKind.Fixlen` switch (`:304`) sets only `afill` |
| corelib-zig | `message.zig:281` | `self.askip = if (kind == .unsigned or kind == .signed) switch … else 0;` — the `.fixlen` switch (`:310`) sets only `afill` |

**2. The `fp32()` / `fp64()` callbacks lack the `askip` guard that `unsigned()` / `signed()` have.**

| backend | `unsigned`/`signed` guard | `fp32`/`fp64` guard |
|---|---|---|
| corelib-rs | `message.rs:275` / `:289` `if self.askip > 0 { … return; }` | **absent** — `fp32` (`:302`) goes straight to `(_Loc::Root_nested, 0) => self.m.nested.f32 = value` |
| corelib-java | `message.java:161` / `:180` `if (askip > 0) { askip--; return; }` | **absent** — `fp32` (`:197`) → `case 1: case 0: m.nested.f32 = value` |
| corelib-cs | `message.cs:195` / `:208` `if (askip > 0) { askip--; return; }` | **absent** — `Fp32` (`:220`) → `case (Root_nested, 0): m.nested.f32 = value` |
| corelib-zig | `message.zig:187` / `:208` `if (self.askip > 0) { … return; }` | **absent** — `fp32` (`:228`) → `0 => self.m.nested.f32 = value` |

Either half alone would suffice as a fix; both are missing for fp. The other seven skip
*structurally* or via an explicit wire-type check (go/python route arrays to a distinct method; c
uses a descriptor mask; cpp/cpp-c-cpp/typescript check the wire type before dispatch) — none of
which the shared-callback five do.

## Attribution — generator-only, no corelib change

The corelibs already announce `arrayBegin` with the count and kind (verified for F-0021:
`corelib-rs istream.rs:355`, `corelib-cs IStream.cs:413`, `corelib-java IStream.java:654`,
`corelib-zig istream.zig:303`). The generated visitor has the signal; it simply does not act on it
for the fp element type. The fix mirrors generator#183/#188 exactly, one line per half:

- generated `arrayBegin`: arm `askip = count` for `Fixlen` (fp) array kinds landing on a
  scalar-declared fp id (the same table already written for `Unsigned|Signed`);
- generated `fp32()` / `fp64()`: `if askip > 0 { askip -= 1; return; }` at the top, as
  `unsigned()` / `signed()` already have.

No corelib change for any of the five; the streaming delivery design stays.

## Reproducers

`f32_recv_array_fp32.bin`, `f64_recv_array_fp64.bin` — the 2 diverging vectors. Controls (all 12
agree, must stay agreeing):

- `control_f32_scalar_correct.bin` (`5602200000c03f07`) — a correctly-typed scalar `fp32` at
  `nested.f32` still decodes to `1.5` on all 12 (the skip fires only on the array-vs-scalar
  mismatch);
- `control_array_at_array_field.bin` (`a606560501200000c03f0707`) — a legitimate `fp32` array at
  the real array field `arrays.nested.fp32` still stores on all 12 — guards that the fix does not
  break real fp arrays.

```sh
# reproduces the split; go through run.sh (never point the comparator at drivers/*/build/
# after a limit-mode run — it leaves probe-dyn binaries there)
CORPUS=findings/F-0025-scalar-fp-field-receives-fp-array ./scripts/run.sh
# 4 inputs: 2 controls agree, 2 reproducers diverge (accept_value) — 7 skip vs 5 store
```

## Relationship to F-0020 / F-0021 / F-0022 / F-0023

The §7.3 axis, fourth position. F-0020 opened it (struct fields), F-0021 closed the integer
scalar←array corner (generator#183), F-0022 the array←scalar arm (generator#188), F-0023 the
wrapper-element loop (generator#189). This is the **fp** scalar←array corner that generator#183 left
uncovered — the sweep's last non-green residual. Isolate-green is not axis-green: F-0021's vectors
only exercised integer positions, so its fix looked complete while the fp position stayed broken.
