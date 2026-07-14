# sofabgen improvement log

Weaknesses in **generated** code that Crucible surfaced while building drivers.
Crucible tests the corelibs, but the generated glue is part of what ships to
users — where the codegen makes a driver harder to write faithfully, or bakes in
a cross-implementation divergence, it is recorded here as a candidate change to
`sofabgen` (repo: `generator/`).

Each entry: what, where, why it matters for the differential fuzzer, proposed
fix. Status: `open` until the generator change lands.

**As of sofabgen 0.15.2 (verified 2026-07-09 against the generator source at HEAD
`fc46953`): all seven weaknesses G-0001..G-0007 are resolved — the fixes shipped
in sofabgen 0.15.1 (`git tag --contains` on each merge → `v0.15.1`).**
Note G-0002 was the *intra-Rust* std/no-std disagreement (now fixed — both empty
on invalid UTF-8); the *family-wide* invalid-UTF-8 policy across all ten corelibs
is the separate finding **F-0004** / spec §8 (epic [#85](https://github.com/sofa-buffers/generator/issues/85)),
still open. Per-entry evidence below; Crucible drivers may still carry now-dead
workarounds (e.g. the Rust two-pass) — those are driver-side follow-ups, not
generator gaps.

## Tracking issues (generator repo)

| id | issue | status |
|---|---|---|
| G-0001 | [generator#79](https://github.com/sofa-buffers/generator/issues/79) | fixed — PR [#88](https://github.com/sofa-buffers/generator/pull/88) (0.15.1) |
| G-0002 | [generator#80](https://github.com/sofa-buffers/generator/issues/80) | fixed — PR [#91](https://github.com/sofa-buffers/generator/pull/91) (0.15.1); family-wide UTF-8 continues as F-0004 / [#85](https://github.com/sofa-buffers/generator/issues/85) |
| G-0003 | [generator#81](https://github.com/sofa-buffers/generator/issues/81) | fixed — PR [#92](https://github.com/sofa-buffers/generator/pull/92) (0.15.1) |
| G-0004 | [generator#82](https://github.com/sofa-buffers/generator/issues/82) | fixed — PR [#93](https://github.com/sofa-buffers/generator/pull/93) (0.15.1) |
| G-0005 | [generator#83](https://github.com/sofa-buffers/generator/issues/83) | fixed — PR [#89](https://github.com/sofa-buffers/generator/pull/89) (0.15.1) |
| G-0006 | [generator#84](https://github.com/sofa-buffers/generator/issues/84) | fixed — PR [#90](https://github.com/sofa-buffers/generator/pull/90) (0.15.1) |
| G-0007 (= F-0003) | [generator#78](https://github.com/sofa-buffers/generator/issues/78) | fixed — PR [#87](https://github.com/sofa-buffers/generator/pull/87) |
| G-0008 | [generator#105](https://github.com/sofa-buffers/generator/issues/105) | ✅ **fixed** — PR [generator#106](https://github.com/sofa-buffers/generator/pull/106) (sofabgen 0.15.3): status-surfacing `TryDecode`/`tryDecode`; part of §7 epic [#86](https://github.com/sofa-buffers/generator/issues/86) |

---

## G-0001 — generated Rust `decode` is infallible (discards the decode error)

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#88](https://github.com/sofa-buffers/generator/pull/88), fixes #79) · **Lang:**
rust (both corelibs) · **Where:** `generator/generators/rust/visitor.go`

The generated decoder *was*:

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

**Fix (shipped):** the Rust backend now emits a fallible entry point alongside
the back-compat `decode`:
`pub fn try_decode(data: &[u8]) -> Result<Self, sofab::Error>` (PR
[#88](https://github.com/sofa-buffers/generator/pull/88); `backend.go:303`,
`visitor.go:226`). Verified in the generated `message.rs` for both corelibs.
**Driver follow-up (not blocking):** `drivers/rust/driver.rs` still runs the
two-pass workaround; it can now collapse to a single `try_decode` call. The C
(`sofab_ret_t`), Go (`error`), Python (`Probe.decode` raises), and now C++
(G-0005) backends all surface the result.

## G-0002 — std vs no-std Rust diverge on invalid UTF-8 in a string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#91](https://github.com/sofa-buffers/generator/pull/91), fixes #80) · **Lang:**
rust · **Where:** `generator/generators/rust/visitor.go`

Same wire bytes *used to* decode to a different string across the two Rust
corelibs:

```rust
// std (corelib-rs)   — WAS:
String::from_utf8_lossy(&chunk[..total]).into_owned()   // invalid UTF-8 -> U+FFFD replacements
// no-std (corelib-rs-no-std):
core::str::from_utf8(&chunk[..total]).unwrap_or("")      // invalid UTF-8 -> empty string
```

A fuzzer produces non-UTF-8 bytes in a string field; the two ports then decoded
it to **different values** (replacement chars vs empty) — a generated-code
divergence, not a wire-format one.

**Fix (shipped):** both profiles now agree — std was changed to
`core::str::from_utf8(&chunk[..total]).map(|s| s.to_owned()).unwrap_or_default()`
(empty on invalid), matching no-std (PR
[#91](https://github.com/sofa-buffers/generator/pull/91); `visitor.go` UTF-8 emit
+ `backend_test.go:81`). **Verified empirically:** the F-0004 reproducer
`invalid_utf8.bin` now yields byte-identical driver output for `rust-std` and
`rust-nostd` (`A 5607a606560707c60c07`).

**Consequence for F-0004:** rust-std moved from the *U+FFFD* camp to the *empty*
camp. This closes the intra-Rust half; the **family-wide** invalid-UTF-8 split
(raw / U+FFFD / empty / reject across all ten corelibs) is finding **F-0004**,
resolved in spec §8 and tracked as epic [#85](https://github.com/sofa-buffers/generator/issues/85)
(corelibs adopting the opt-in strict check) — still open.

## G-0003 — std vs no-std Rust diverge on a chunked (multi-feed) string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#92](https://github.com/sofa-buffers/generator/pull/92), fixes #81) · **Lang:**
rust · **Where:** `generator/generators/rust/visitor.go`

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

**Fix (shipped):** the no-std visitor now accumulates chunked string/blob into
`self.acc` like std (PR [#92](https://github.com/sofa-buffers/generator/pull/92),
commit `b8e0693`). Verified: the generated no-std `message.rs` reads
`core::str::from_utf8(&self.acc[..total])`. Combined with G-0004, an over-capacity
accumulation is surfaced as an error rather than silently dropped.

## G-0004 — no-std silently drops an over-capacity string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#93](https://github.com/sofa-buffers/generator/pull/93), fixes #82) · **Lang:**
rust (no-std) · **Where:** `generator/generators/rust/visitor.go`

The over-capacity fill *was* discarded silently:

```rust
(_Loc::Root, 3) => { self.m.s.clear(); let _ = self.m.s.push_str(_s); }
```

`heapless::String::push_str` is fallible (returns `Err` past capacity), and the
result was discarded. A string longer than the field's `maxlen` was **silently
dropped to empty** instead of rejected. Combined with G-0001 the caller got no
signal at all.

**Fix (shipped):** the fill now flags capacity overflow, e.g.
`... let _ = self.m.nested.str.push_str(_s); if self.m.nested.str.len() != _s.len() { self.err = true; }`,
and `err` is surfaced through the new fallible `try_decode` (G-0001) as an
`Error` (PR [#93](https://github.com/sofa-buffers/generator/pull/93), commit
`d56a1a7`). Verified in the generated no-std `message.rs`.

## G-0005 — generated C++ `decode` is infallible (same gap as G-0001)

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#89](https://github.com/sofa-buffers/generator/pull/89), fixes #83) · **Lang:**
cpp (both corelibs) · **Where:** `generator/generators/cpp/backend.go`

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

**Fix (shipped):** the C++ backend now emits a fallible form alongside `decode`:
`static sofab::IStreamImpl::Result try_decode(const std::uint8_t *data, std::size_t len, Probe &out)`
(PR [#89](https://github.com/sofa-buffers/generator/pull/89); `cpp/backend.go:221`).
Verified in the generated `probe.hpp`. C++, Rust (G-0001), Go, and C now all
expose the decode verdict. The Crucible C++ driver already read `feed`'s Result
directly, so no driver change is required.

## G-0006 — generated Go `types.go` uses `bytes.Equal` without importing `bytes`

**Status:** **fixed** in sofabgen 0.15.2 (PR
[#90](https://github.com/sofa-buffers/generator/pull/90), fixes #84) · **Lang:**
go · **Where:** `generator/generators/golang/` (per-file import collection for
named/nested types) · **Severity:** was build-breaking

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

**Impact on Crucible:** blocked the Go driver for the full-scale schema.
Previously worked around in `drivers/go/build.sh` (inject `"bytes"` into any
generated file that referenced `bytes.` but did not import it); that workaround
was **removed** once 0.15.2 emitted the import correctly — verified: generated
`types.go` now carries its own `"bytes"` import, so the injection no longer
fires.

**Proposed fix:** collect imports per emitted file, not per message — every file
that references `bytes.` (or any std package) must import it.

## G-0007 — generated Rust array fill has no bounds check (crashes)

**Status:** fixed (PR [generator#87](https://github.com/sofa-buffers/generator/pull/87)) ·
**Lang:** rust (both corelibs) · **Where:**
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

**Fix (shipped):** mirrored the Zig/C behavior — the fill index is now guarded
(`if self.ai < N { ... ; self.ai += 1; }`), dropping excess elements per
MESSAGE_SPEC §5.1. Applied in `emitNativeArrayStore` so it covers every
native-array element arm (unsigned, signed, enum, bool, bitfield, float) across
both the std and no_std profiles. PR
[generator#87](https://github.com/sofa-buffers/generator/pull/87). Verified via
F-0003's `array_overflow.bin`: the rebuilt Rust driver goes from panic (exit 101)
to clean accept (exit 0) on both the `rs` and `rs-no-std` variants.

## G-0008 — generated one-shot decode discards the INCOMPLETE status (C#, Java)

**Where:** the generated `Probe.Decode`/`Probe.decode` for the *status-returning*
corelibs — C# (`Message.cs`) and Java (`Probe.java`).

**What:** under MESSAGE_SPEC §7 (finish-less three-valued decode), those corelibs
surface `INCOMPLETE` as a **returned status**, not a thrown error:
`IStream.Feed(...)` returns `DecodeStatus.Incomplete` (C#) and `IStream.status()`
returns `DecodeStatus.INCOMPLETE` (Java) — `feed` does *not* throw on a truncated
message. But the generated one-shot decode calls `feed` and **throws the status
away**:

```csharp
public static Probe Decode(byte[] data) {
    var m = new Probe(); var v = new ProbeVisitor(m);
    new IStream().Feed(data, 0, data.Length, v);   // DecodeStatus DISCARDED
    return m;
}
```

So a truncated message decodes without error and is indistinguishable from a
COMPLETE one — the generated decode **collapses INCOMPLETE into ACCEPT**, the
exact F-0001 bug the verdict axis exists to catch. Confirmed empirically: a lone
`0x80` re-encoded byte-identical to the empty message (`A 5607...`) before the
driver workaround.

**Why it matters:** this is the INCOMPLETE-dimension analogue of G-0001/G-0005
(which fixed the *reject* dimension — a fallible decode — but not the
*accept-vs-incomplete* dimension). The generated glue hides a real outcome the
corelib computes correctly.

**Former driver workaround (now removed):** `drivers/cs/Driver.cs` and
`drivers/java/Driver.java` used to take the **verdict** from a direct
`IStream.Feed`/`feed` + status read (a no-op visitor), and the **value** from the
generated decode — the same two-pass pattern the Rust driver uses for G-0001.

**Fixed** in sofabgen 0.15.3 (PR
[generator#106](https://github.com/sofa-buffers/generator/pull/106), closes
generator#105, under the §7 epic
[#86](https://github.com/sofa-buffers/generator/issues/86)): the generated
one-shot decode for the status-returning corelibs now surfaces the terminal
`DecodeStatus` via a status-returning entry point — C#
`DecodeStatus TryDecode(byte[] data, out T msg)` and Java
`DecodeStatus tryDecode(byte[] data, T out)` — so a caller can tell COMPLETE from
INCOMPLETE without re-running `feed`. The exception-throwing corelibs (Go, Rust
via feed, C++, C, Python, TS, Zig) already propagate INCOMPLETE through the
generated decode — only the status-returning pair needed the codegen change.

**Driver follow-up done** (crucible#10, sofabgen 0.16.0 bump): the two-pass
workaround is **removed** — `drivers/cs/Driver.cs` and `drivers/java/Driver.java`
now take both verdict and value from a single `TryDecode`/`tryDecode` call
(`Complete`→`A <hex>`, `Incomplete`→`I`, malformed throw→`R <class>`). Verified:
lone `0x80` still reports `I` (not the pre-fix `A`), and both drivers agree with
the family on the F-0001 seeds.
