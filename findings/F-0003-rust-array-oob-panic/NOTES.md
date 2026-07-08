# F-0003 — Rust decoder panics (index out of bounds) on an over-long array

**Status:** open — crash / DoS; codegen root cause (see docs/SOFABGEN.md G-0007)
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

In `sofabgen`'s Rust backend, bound the array-fill index like the Zig/C backends
(drop or reject excess elements). Tracked as **G-0007** in docs/SOFABGEN.md. Until
fixed, an untrusted Sofab message can crash any Rust consumer of the generated
code.
