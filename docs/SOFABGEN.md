# sofabgen improvement log

Weaknesses in **generated** code that Crucible surfaced while building drivers.
Crucible tests the corelibs, but the generated glue is part of what ships to
users — where the codegen makes a driver harder to write faithfully, or bakes in
a cross-implementation divergence, it is recorded here as a candidate change to
`sofabgen` (repo: `generator/`).

Each entry: what, where, why it matters for the differential fuzzer, proposed
fix. Status: `open` until the generator change lands.

## Tracking issues (generator repo)

| id | issue |
|---|---|
| G-0001 | [generator#79](https://github.com/sofa-buffers/generator/issues/79) |
| G-0002 | [generator#80](https://github.com/sofa-buffers/generator/issues/80) |
| G-0003 | [generator#81](https://github.com/sofa-buffers/generator/issues/81) |
| G-0004 | [generator#82](https://github.com/sofa-buffers/generator/issues/82) |
| G-0005 | [generator#83](https://github.com/sofa-buffers/generator/issues/83) |
| G-0006 | [generator#84](https://github.com/sofa-buffers/generator/issues/84) |
| G-0007 (= F-0003) | [generator#78](https://github.com/sofa-buffers/generator/issues/78) |

---

## G-0001 — generated Rust `decode` is infallible (discards the decode error)

**Status:** open · **Lang:** rust (both corelibs) · **Where:**
`generator/generators/rust/visitor.go:194`

The generated decoder is:

```rust
pub fn decode(data: &[u8]) -> Self {
    let mut m = Probe::default();
    { let mut v = V { .. }; let mut is = IStream::new(); let _ = is.feed(data, &mut v); }
    m   // <- feed's Result<()> is thrown away
}
```

`IStream::feed` returns `Result<()>` and the corelib *does* detect malformed
input (`Error::InvalidMsg`, …), but the generated wrapper drops it and always
returns a (best-effort) value. So the **generated Rust API can never reject** —
a real user gets silent best-effort decoding, and a differential driver cannot
read the corelib's accept/reject decision through the public API.

**Impact on Crucible:** the Rust driver must run a **two-pass** workaround —
call `Probe::decode` for the value, then re-run `IStream::feed` against a
null visitor to recover the verdict. Faithful but wasteful (decodes twice).

**Proposed fix:** emit a fallible entry point, e.g.
`pub fn try_decode(data: &[u8]) -> Result<Self, sofab::Error>` (or make `decode`
return `Result`). Then the driver is one pass and real users can handle errors.
The C (`sofab_ret_t`), Go (`error`), and Python (`Probe.decode` raises
`SofaError`) backends already surface the result — Rust and C++ are the outliers.
Python is a ready reference for the fallible shape to mirror.

## G-0002 — std vs no-std Rust diverge on invalid UTF-8 in a string

**Status:** open · **Lang:** rust · **Where:** `generator/generators/rust/`
(std uses `visitor.go`; no-std string emit differs)

Same wire bytes, different decoded string across the two Rust corelibs:

```rust
// std (corelib-rs):
String::from_utf8_lossy(&chunk[..total]).into_owned()   // invalid UTF-8 -> U+FFFD replacements
// no-std (corelib-rs-no-std):
core::str::from_utf8(&chunk[..total]).unwrap_or("")      // invalid UTF-8 -> empty string
```

A fuzzer will produce non-UTF-8 bytes in a string field; the two ports then
decode it to **different values** (replacement chars vs empty). That is a
generated-code divergence, not a wire-format one — the two Rust corelibs should
agree.

**Proposed fix:** pick one policy for invalid UTF-8 and emit it in both variants
(both lossy, or both reject via G-0001's fallible path). Whichever the spec
prefers — but it must be the same across the family.

## G-0003 — std vs no-std Rust diverge on a chunked (multi-feed) string

**Status:** open · **Lang:** rust · **Where:** `generator/generators/rust/`

The std visitor accumulates a string split across `feed` chunks (has an `acc`
buffer); the no-std visitor bails on any non-initial chunk:

```rust
// no-std:
fn string(&mut self, id, total, offset, chunk) {
    if offset != 0 || chunk.len() < total { return; }   // drops chunked strings entirely
    ...
}
```

Under incremental/streaming feed, a string delivered in pieces is reconstructed
by std but yields the default (empty) in no-std — divergence. (Not reachable in
single-shot decode, but Crucible's coverage engine will feed in chunks.)

**Proposed fix:** no-std should accumulate too (bounded by the field's
fixed capacity), or the constraint should be an explicit, surfaced error rather
than a silent drop.

## G-0004 — no-std silently drops an over-capacity string

**Status:** open · **Lang:** rust (no-std) · **Where:** `generator/generators/rust/`

```rust
(_Loc::Root, 3) => { self.m.s.clear(); let _ = self.m.s.push_str(_s); }
```

`heapless::String::push_str` is fallible (returns `Err` past capacity), and the
result is discarded. A string longer than the field's `maxlen` is **silently
dropped to empty** instead of rejected. Combined with G-0001 the caller gets no
signal at all.

**Proposed fix:** surface capacity overflow as an `Error` through the fallible
decode (G-0001). A fixed-capacity field overflowing is exactly the kind of thing
the embedded profile must report, not swallow.

## G-0005 — generated C++ `decode` is infallible (same gap as G-0001)

**Status:** open · **Lang:** cpp (both corelibs) · **Where:**
`generator/generators/cpp/` (the generated `static T decode(...)`)

```cpp
static Probe decode(const std::uint8_t *data, std::size_t len) {
    sofab::IStreamObject<Probe> in;
    in.feed(data, len);   // Result discarded
    return *in;
}
```

Same shape as G-0001: `IStreamObject::feed` returns a `Result` (with `.ok()` /
`.code()`), but the generated convenience `decode` throws it away and always
returns a value. A user of `Probe::decode` cannot tell a malformed message from a
valid one.

**Impact on Crucible:** smaller than Rust — the C++ driver simply uses
`IStreamObject` directly and reads `feed`'s returned `Result` (one pass, no
workaround). But the public convenience API still can't reject.

**Proposed fix:** offer a fallible form, e.g.
`static Result decode(const std::uint8_t*, std::size_t, Probe &out)` or
`std::optional<Probe> try_decode(...)`, so `Probe::decode` users get the verdict.
Align with G-0001 so C++, Rust, Go, and C all expose the decode result.

## G-0006 — generated Go `types.go` uses `bytes.Equal` without importing `bytes`

**Status:** open · **Lang:** go · **Where:**
`generator/generators/golang/` (per-file import collection for named/nested types)
· **Severity:** build-breaking

A blob field inside a **named/nested** struct lands its marshal in `types.go`,
which emits:

```go
if !bytes.Equal(m.BytesField, nil) { e.WriteBytes(3, m.BytesField) }
```

but `types.go`'s import block only has the corelib — **no `"bytes"`**. Go
imports are per-file, so `go build` fails:

```
types.go:140:6: undefined: bytes
```

`probe.go` (which also uses `bytes`) *does* import it, so the top-level message
compiles — but any schema with a blob in a nested struct (e.g. the full-scale
message's `nested.bytes_field`) breaks. Reproduced with sofabgen 0.15.0 against
the arena full-scale schema unchanged.

**Impact on Crucible:** blocks the Go driver for the full-scale schema.
Worked around in `drivers/go/build.sh` — after generation, inject `"bytes"` into
any generated file that references `bytes.` but does not import it. Remove the
workaround once fixed.

**Proposed fix:** collect imports per emitted file, not per message — every file
that references `bytes.` (or any std package) must import it.

## G-0007 — generated Rust array fill has no bounds check (crashes)

**Status:** open · **Lang:** rust (both corelibs) · **Where:**
`generator/generators/rust/visitor.go` (native-array element fill) ·
**Severity:** crash / DoS on untrusted input

The generated Rust visitor writes native-array elements by an unchecked running
index:

```rust
(_Loc::Root_arrays, 0) => { self.m.arrays.u8[self.ai] = value as u8; self.ai += 1; }
```

`self.ai` is not bounded against the array length, so a wire message with more
elements than the declared count panics (`index out of bounds`). The **C and Zig
backends already guard this** — Zig's `_put` drops excess elements
(`if (i.* >= s.len) return;`), C's fill is equivalently bounded. Rust is the
outlier and it crashes rather than clamping.

This is the codegen root cause of **F-0003** (found by the C pacemaker → the
differential loop). It panics in release too (Rust bounds-checks indexing), so it
is a real DoS in any Rust consumer of the generated code.

**Proposed fix:** mirror the Zig/C behavior — guard the fill index
(`if self.ai < N { ... ; self.ai += 1; }`), dropping or rejecting excess elements
per MESSAGE_SPEC. Apply to every native-array fill in the Rust backend (both the
std and no_std profiles are affected).
