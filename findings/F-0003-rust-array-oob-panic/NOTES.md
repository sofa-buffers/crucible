# F-0003 — Rust decoder panics (index out of bounds) on an over-long array

> **✅ FULLY RESOLVED 2026-07-15 (sofabgen 0.16.1).** The residual over-count
> *accept* divergence (generator#100) is fixed by commit `ca0fda7` ("reject
> over-count scalar arrays in every backend"). Re-verified with a clean
> non-truncated over-count(8>5) array (`a6 06 03 08 01..08 07`): **all 12 drivers
> reject** (`R`) — rust-std/nostd reject with the family. The rest of this file is
> the earlier history (crash fix + the then-open residual). Note the old 145-byte
> reproducer is contaminated (over-count *and* truncated), so rust/zig report `I`
> there; the clean isolate above is the correct test.

**Status:** ✅ **crash fixed** — bounds check added in sofabgen's Rust backend; PR
[sofa-buffers/generator#87](https://github.com/sofa-buffers/generator/pull/87)
(codegen root cause G-0007, issue [generator#78](https://github.com/sofa-buffers/generator/issues/78)).
⚠️ **residual divergence — now triaged & tracked:** re-verifying 2026-07-08
(**sofabgen 0.15.1 + corelib-rs / corelib-rs-no-std @main**) shows the fix makes Rust
**accept** the over-long array (silently dropping the excess elements): both `rust-std`
and `rust-nostd` now return a decoded message where the other **10** drivers reject it.
The crash became an **accept-vs-reject verdict divergence, 2 vs 10**. **Triage result:**
an over-**count** scalar array (wire count > schema `count` N) is **INVALID** per
MESSAGE_SPEC §3+§7 — the excess-drop is a codegen bug, not legal leniency; **no**
`policy.yaml` allow-entry. Tracked in
[**generator#100**](https://github.com/sofa-buffers/generator/issues/100) (the Rust
backend must reject, like c/cpp-c-cpp). **Axis: crash → verdict (`R`).** Note this is a
**different axis from F-0001**: over-length → `R` (INVALID); truncation → `I`
(INCOMPLETE). The new third verdict `I` (crucible#8) does **not** apply here.
See the re-run table below.
**Found:** Phase 3, first differential run over the **C-pacemaker's** discovered
corpus (a crash 8 hand-seeds never reached)
**Axis:** crash (memory-safety-adjacent — a panic, not UB)
**Affects:** `corelib-rs` (std) **and** `corelib-rs-no-std` — both panic

## What

The generated Rust array-fill visitor writes native-array elements with **no
bounds check on the running index** (`message.rs`):

```rust
(_Loc::Root_arrays, 0) => { self.m.arrays.u8[self.ai] = value as u8; self.ai += 1; }
//                          ^^^^^^^^^^^^^^^^^^^^^^^^^ no `self.ai < len` guard
```

The native array has the schema's declared length (5). A hostile message that
delivers **more than 5 elements** for that array drives `self.ai` to 5, and the
indexed write panics:

```
thread 'main' panicked at message.rs:224:41:
index out of bounds: the len is 5 but the index is 5
```

This panics in **release** too (Rust bounds-checks indexing unconditionally), so
it is a real crash / denial-of-service on untrusted input, not a debug artifact.

## The family is inconsistent here

Other backends bound this. Zig's generated fill drops excess elements:

```zig
fn _put(s, i, v) { if (i.* >= s.len) return; ... }   // "excess elements are dropped"
```

C fills fixed arrays with an equivalent guard. Rust (both corelibs) does not —
it indexes unchecked and panics. So this is a **codegen divergence** that becomes
a **crash**.

## Reproducer

`array_overflow.bin` (145 bytes, minimized from a 754-byte pacemaker input):

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0003-rust-array-oob-panic/array_overflow.bin | drivers/rust/build/rs/target/debug/harness
# thread 'main' panicked ... index out of bounds: the len is 5 but the index is 5
```

## Why the differential loop surfaced it as a harness error

The comparator feeds the whole corpus to each driver in one persistent process;
the Rust driver aborted mid-stream, so it returned fewer lines than inputs. The
comparator now isolates this (reports "driver X crashed after N inputs") instead
of a bare exit-2 — see the crash-isolation change in `oracle/comparator.py`.

## Fix

**Fixed** in `sofabgen`'s Rust backend (`generators/rust/visitor.go`,
`emitNativeArrayStore`): the native-array element fill is now bounds-checked like
the Zig/C backends, dropping excess elements per MESSAGE_SPEC §5.1:

```rust
(_Loc::Root_arrays, 0) => { if self.ai < 5 { self.m.arrays.u8[self.ai] = value as u8; self.ai += 1; } }
```

The guard covers every native-array element arm (unsigned, signed, enum, bool,
bitfield, float) across both the std and no_std profiles. PR
[sofa-buffers/generator#87](https://github.com/sofa-buffers/generator/pull/87)
(issue [generator#78](https://github.com/sofa-buffers/generator/issues/78),
codegen weakness **G-0007** in docs/SOFABGEN.md).

**Verified:** rebuilt the Rust driver with the fixed `sofabgen` and re-fed
`array_overflow.bin` — the harness that previously panicked (`index out of
bounds: the len is 5 but the index is 5`, exit 101) now cleanly accepts and drops
the overflow (exit 0), for both the `rs` and `rs-no-std` variants.

## Update — 2026-07-08 (sofabgen 0.15.1 + corelib-rs / -no-std @main)

`generator#78` landed: the Rust array fill is now bounds-checked, so the **panic /
DoS is gone** (0 crashes on `array_overflow.bin`). But the chosen fix *accepts* the
message and drops the excess, rather than rejecting it — which the rest of the
family does not. Feeding the reproducer through all 12 drivers:

| verdict | drivers |
|---|---|
| **A** (accept, excess dropped) | **rust-std, rust-nostd** |
| **R** (reject) | c, go, cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig |

So the outcome is now a **2-accept-vs-10-reject verdict divergence** — Rust is the
lone accepting camp. (Among the 10 rejecters the *reject class* also varies —
c/cpp-c-cpp say `usage`, csharp says `other`, the rest `invalid_msg` — a secondary,
policy-tolerated warning; note F-0003's original NOTES claimed Zig "drops excess",
but on this input Zig rejects.) This crossed from the **crash** axis to the
**verdict** axis and is **not covered by any open generator issue**. Next step is a
triage decision: is rejecting the over-long array the specified behavior (→ Rust
codegen bug, reopen/new issue) or legal leniency (→ `policy.yaml` allow-entry)?
