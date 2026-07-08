# F-0003 — Rust decoder panics (index out of bounds) on an over-long array

**Status:** fixed — bounds check added in sofabgen's Rust backend; PR [sofa-buffers/generator#87](https://github.com/sofa-buffers/generator/pull/87) (codegen root cause G-0007, issue [generator#78](https://github.com/sofa-buffers/generator/issues/78))
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
