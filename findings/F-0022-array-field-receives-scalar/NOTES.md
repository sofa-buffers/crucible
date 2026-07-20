# F-0022 — an array-declared field receiving a scalar of its element type: decoded, not skipped

**Status:** **open — generator-only, the mirror of F-0021.** MESSAGE_SPEC §7.3 requires the
field to be **skipped**; five backends decode the bare scalar as a one-element array. Filed as
[generator#188](https://github.com/sofa-buffers/generator/issues/188).
**Axis:** verdict (accept-with-wrong-value vs skip) — all 12 accept; the 5 store a value the 7
do not. **Found:** 2026-07-20 by the **wire-type sweep** (`engine/structured/wiretype_sweep.py`)
on sofabgen 0.19.3, the first run of that suite.

## The observation

An **array-declared** field receiving a **scalar** whose wire type is the scalar form of its
element type. Wire type Unsigned ≠ ArrayUnsigned (§1), so §7.3 says skip. But:

| reproducer | bytes | meaning |
|---|---|---|
| `arru8_recv_scalar_u.bin` | `a6 06 00 05 07` | `arrays.u8` (id 0, declared `u8[]`) gets a bare `u8 = 5` |
| `arri8_recv_scalar_s.bin` | `a6 06 09 06 07` | `arrays.i8` (id 1, declared `i8[]`) gets a bare `i8 = 3` |
| `arrfp32_recv_scalar_fp32.bin` | `a6 06 56 02 20 00 00 c0 3f 07 07` | `arrays.nested.fp32` (100→10→0, declared `fp32[]`) gets a bare fixlen `fp32` |

`a6 06` opens the `arrays` struct (id 100), the field follows, `07` closes it. On decode:

| camp | behaviour | drivers |
|---|---|---|
| **skip** (conformant §7.3) | array stays empty | c, cpp, cpp-c-cpp, go, py-cython, py-pure, typescript (7) |
| **decode as a 1-element array** | `arrays.i8 = [3]` → re-encode `…a606 0c0106…` | **rust-std, rust-nostd, csharp, java, zig (5)** |

Same five backends as F-0021, over integer **and** fp arrays. Controls (all 12 agree): a
correctly-typed array (`a6 06 03 01 05 07`) and a correct scalar at a scalar id (`00 05`).

## This is the exact mirror of F-0021

F-0021 = a **scalar** field receiving an **array** wire type → fixed in generator#183 (0.19.3).
F-0022 = an **array** field receiving a **scalar** wire type → still open. Both are the same
shared-callback ambiguity, opposite directions.

The five corelibs deliver an integer/fp array **element-by-element through the same callback**
that also delivers a lone scalar (`unsigned()` / `signed()` / the fp readers), with
`array_begin(id, kind, count)` as context. So `unsigned(id, val)` fires for **both** a scalar
*and* each array element; the generated code must disambiguate by the `array_begin` state.

## Why generator#183 does not cover it (traced, 0.19.3)

The 0.19.3 fix guards the **scalar** arms against array elements — `drivers/rust/build/rs/src/message.rs`:

```rust
fn unsigned(&mut self, id, value) {
    if self.askip > 0 { self.askip -= 1; return; }   // §7.3: an array delivered at a scalar id
    match (self.cur, id) {
        (Root, 0) => self.m.u8 = value,                          // scalar arm — now guarded
        (Root_arrays, 0) => { self.m.arrays.u8[self.ai] = value; self.ai += 1; }  // array-fill arm — UNGUARDED
        _ => {}
    }
}
fn array_begin(&mut self, id, kind, count) {
    self.ai = 0;
    self.askip = match kind { Unsigned|Signed =>
        match (cur,id) { (Root_arrays, 0..=7) => 0, _ => count }, _ => 0 };  // arm the skip only at scalar positions
}
```

`array_begin` sets `askip = count` when an array arrives at a **scalar** position, and the
scalar arms honour `askip` — that is F-0021. But the **array-fill arms** `(Root_arrays, n) =>
fill` fire on *any* `unsigned()` at that `(cur, id)`. A bare scalar inside the `arrays` scope
arrives with `askip == 0` (no `array_begin`) and falls straight into the fill arm → stored as
element 0. There is no gate asking "did an `array_begin` for this id precede me?"

## The fix — symmetric to #183, generator-only

Arm the **fill** in `array_begin`, exactly as #183 armed the skip. For a legit array position,
`array_begin` sets a per-`(cur,id)` "expecting `count` elements" counter; the fill arm acts
only while that counter is positive and decrements it; a bare scalar (no `array_begin` → counter
0) leaves the fill arm unarmed, so the field falls through to `_ => {}` and is **skipped**.
Self-terminating via the count, chunk-safe (state lives in the generated visitor), and it does
not disturb a real array (armed by its `array_begin`) or a scalar following the array (counter
back to 0). **No corelib change** — the corelib already announces `array_begin` with the count
before the elements (verified for all five in F-0021's NOTES). The five backends are exactly
those; the other seven skip structurally or via an explicit wire-type check.

## Why the F-0021 fix looked complete but was not

F-0020/F-0021's promoted vectors only tested the **scalar-field** position receiving an array.
The **array-field** position receiving a scalar was never in a reproducer — so "F-0021
resolved, §7.3 axis green" was **isolate-green, not axis-green** (the recurring lesson, cf.
F-0017). The wire-type sweep enumerates *every* field position × *every* wire construct, so it
hit the array-field position on its first run. This is the argument for the sweep as a standing
suite.

## Reproducing

```sh
python3 oracle/cluster.py --corpus findings/F-0022-array-field-receives-scalar \
  --driver c:... --driver rust-std:... [all 12]
# 5 inputs: 2 agree, 3 diverge -> 1 cluster (7 skip vs 5 decode)
```

Build via `./scripts/run.sh` — never point the comparator at `drivers/*/build/` after a
limit-mode run (probe-dyn binaries there mis-report a sweep as ~all divergent).
