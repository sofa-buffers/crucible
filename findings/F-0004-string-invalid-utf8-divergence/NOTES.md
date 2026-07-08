# F-0004 — invalid UTF-8 in a string: four behaviors, driven by the string type

**Status:** resolved in spec — `MESSAGE_SPEC.md` §8 (opt-in strict UTF-8 check,
default off; conformance/fuzz runs it on). Corelib work: expose the check as a
config flag and enable it under the fuzzer.
**Found:** Phase 3, C-pacemaker → differential loop; **corrected** with a clean
isolate (the original write-up was skewed — see below)
**Axis:** verdict + accept_value (hard, when the check is on)

## The true split (clean isolate)

Reproducer `invalid_utf8.bin` = a well-formed message whose only anomaly is a
`nested.str` payload `41 ff 42` ("A", `0xff`, "B") — `0xff` alone is not valid
UTF-8. Feeding it to every driver:

| behavior | impls | why — the decode target's string type |
|---|---|---|
| **preserve raw** (`…41 ff 42…`) | c, cpp, cpp-c-cpp, **zig** | byte-container string, no UTF-8 check: `char[]`, `std::string`, `[]const u8` |
| **U+FFFD replace** (`…41 efbfbd 42…`) | rust-std, java, csharp, **typescript** | Unicode string whose constructor replaces: `from_utf8_lossy`, `new String(b, UTF_8)`, `Encoding.UTF8.GetString`, `TextDecoder` |
| **empty / dropped** | rust-nostd | heapless `String` via `from_utf8().unwrap_or("")` |
| **reject** (`R invalid_msg`) | go, py | explicit strict check: Go `utf8.Valid(b)`; Python `bytes.decode("utf-8")` (strict by default) |

The behavior **falls out of the target string type**, not a deliberate corelib
choice: Unicode-string types (Rust/Java/C#/JS/Python `str`) cannot hold non-UTF-8
bytes at all, so they replace or reject; byte-container types (C/C++/Go/Zig) carry
raw bytes, and only Go (explicit `utf8.Valid`) and Python (strict `.decode`)
actually reject.

## Correction to the original write-up

The first version claimed a 3-way split with TypeScript and Zig in the *reject*
camp. That was wrong: it was based on a **complex** pacemaker input where TS/Zig
rejected for *other* structural reasons — and all rejects look identical
(`R invalid_msg`) because the reject class is coarse. Isolated cleanly, **TS does
U+FFFD** and **Zig preserves raw**. Lesson: characterize a divergence with a
*minimal* input that isolates the one behavior, not a raw fuzzer finding.

## Resolution — MESSAGE_SPEC.md §8

`string` is UTF-8; `blob` is the type for opaque bytes. The **strict, conformant**
behavior is to reject invalid UTF-8 as `INVALID` (§7). Because validation has a
cost and several native string types don't check, the corelib **MAY gate the
check behind a config flag that MAY default OFF**:

- **check on** → reject invalid UTF-8 (family-uniform, conformant);
- **check off** (default allowed) → implementation-defined (raw bytes, or the
  Unicode type's replacement) — zero-cost decode, outside the strict contract.

Conformance testing and this differential fuzzer run with the check **on**, so all
implementations agree.

**Implementation tracked:** [generator#85](https://github.com/sofa-buffers/generator/issues/85)
(epic: `SOFAB_STRICT_UTF8` flag + check across corelibs, codegen call sites for
rust/java/cs/zig, and Crucible verification). The check's *placement* follows each
corelib's memory model — corelib-internal where the corelib builds the string
(c/cpp/go/py/ts), codegen-invoked where the generated code builds it
(rust/java/cs/zig).
