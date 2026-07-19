# F-0021 — a scalar integer field receiving an array wire type of the same signedness

**Status:** **open — generator-only, one issue.** MESSAGE_SPEC §7.3 requires the field to be
**skipped**; five backends decode it instead. Filed as [generator#183](https://github.com/sofa-buffers/generator/issues/183).
**Axis:** verdict (accept-with-wrong-value vs skip) — all 12 accept; the 5 write a value the
7 do not. **Found:** 2026-07-19, re-checking F-0020 on sofabgen 0.19.2.

## The residual after F-0020's §7.3 fix

§7.3 (documentation#23) landed in 0.19.2 for most profiles (generator#174, corelib-c-cpp#100,
corelib-cpp#43). A systematic sweep of every top-level field id × every wire type then leaves
**8 of 55 mismatch vectors** still divergent — all one shape:

> an integer **scalar** field receiving an integer **array** wire type of the **same
> signedness** (`u8…u64` ← ArrayUnsigned, `i8…i64` ← ArraySigned).

| camp | behaviour | drivers |
|---|---|---|
| **skip** (conformant §7.3) | field stays default | c, cpp, cpp-c-cpp, go, py-cython, py-pure, typescript (7) |
| **decode the element into the scalar** | `u8 = 5` | **rust-std, rust-nostd, csharp, java, zig (5)** |

`03 01 05` = field id 0 (declared `u8`) carrying ArrayUnsigned, count 1, value 5 → the 5
re-encode `u8 = 5`; the 7 skip. Every other mismatch (47/55) now skips on all 12.

## Why exactly these five (traced)

The distinction is **not** "visitor vs pull" — go and python are visitor-based too and skip
correctly. It is **how the corelib delivers an integer array**:

| delivery | corelibs | scalar field catches an element? |
|---|---|---|
| a distinct array method (`unsignedArray(id, [])`) | go, python | no — generated array-handler has no scalar-id case |
| explicit wire-type check before dispatch | c (descriptor mask), cpp/cpp-c-cpp (guard), typescript (`c.wire`) | no — guard skips |
| **element-by-element through the scalar callback** | **rust-std, rust-nostd, csharp, java, zig** | **yes** |

The five deliver each array element through the same `unsigned(id, val)` / `signed(id, val)`
used for a lone scalar, with `arrayBegin(id, kind, count)` announced first. The generated
visitor dispatches on the id alone (`(Root, 0) => m.u8 = value`), so the element lands in the
scalar's arm — the code never learns it came from an array.

The other 47 mismatches skip *structurally*: a signed wire at an unsigned-declared id is
delivered via `signed()`, whose match has no arm for that id → falls through. Only an array
of the **same** signedness hits the matching callback, so the structural skip has nothing to
fall through.

**This delivery design is not a defect** — it is streaming and zero-extra-allocation, which
corelib-rs-no-std and corelib-zig depend on for no-heap decode. The fix does not change it.

## Attribution — generator-only, no corelib change (verified per source)

Every one of the five announces `arrayBegin` **before** the elements, **with the count**:

| corelib | call site |
|---|---|
| corelib-rs | `istream.rs:355` `v.array_begin(id, kind, count)` → element resume state |
| corelib-rs-no-std | `istream.rs:457` `visitor.array_begin(self.id, self.array_kind, count)` → element state |
| corelib-cs | `IStream.cs:413` `visitor.ArrayBegin(id, kind, remaining)` before the loop; the fast path (`FastVarintArray`) calls it too |
| corelib-java | `IStream.java:654` `visitor.arrayBegin(id, arrayKind, c)`; doc: *"fires exactly once, just before the elements are delivered"* |
| corelib-zig | `istream.zig:303` `visitor.arrayBegin(id, kind, count)` → `array_int` resume state (opt-in via `@hasDecl`) |

So the generated code has the signal and the count already. The fix:

- generated `arrayBegin`/`array_begin`: if `(scope, id)` is a **scalar-declared** field, set
  `skip_remaining = count`;
- generated `unsigned()`/`signed()`: `if skip_remaining > 0 { skip_remaining -= 1; return; }`.

Self-terminating via the count (no array-end callback needed); survives chunk boundaries (the
flag lives in the generated visitor); does not disturb a legitimate array field (`(scope, id)`
is an array → flag never set) nor a scalar following the array (count reaches 0). For
`rust`/`rust-nostd` the generated `array_begin` hook already exists (it resets the element
index) — the fix is added match arms; for `zig` the generator must add an `arrayBegin`
method. **No corelib change** for any of the five.

## Reproducers

`u{8,16,32,64}_recv_array_unsigned.bin`, `i{8,16,32,64}_recv_array_signed.bin` — the 8
diverging vectors. Controls (all 12 agree, must stay agreeing):

- `control_u8_scalar_correct.bin` (`00 05`) — a correctly-typed scalar still decodes;
- `control_array_at_array_field.bin` (`a6 06 03 01 05 07`) — a legitimate `u8` array inside
  the `arrays` struct (id 100) still stores — guards that the fix does not break real arrays.

```sh
python3 oracle/cluster.py --corpus findings/F-0021-scalar-field-receives-array-wire-type \
  --driver c:... --driver rust-std:... [all 12]
# 10 inputs: 2 agree, 8 diverge -> 1 cluster (7 skip vs 5 decode)
```

Build via `./scripts/run.sh` — never point the comparator at `drivers/*/build/` after a
limit-mode run (it leaves `probe-dyn` binaries there, which mis-reports a full sweep as ~all
divergent).

## Relationship to F-0017 / F-0020

The §7.3 axis. F-0017 fixed one isolate; F-0020 opened the axis; 0.19.2 closed 47/55. This is
the last 8 — the array-into-scalar corner the shared-callback backends miss. Isolate-green is
not axis-green.
