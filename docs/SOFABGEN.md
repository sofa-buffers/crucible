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
| G-0013 | *(not yet filed)* | 🆕 **open — found 2026-07-16.** The heap backends (go, rust-std, cpp, py×2, java, ts, cs, zig) emit an **unbounded** container + fill for an index-keyed array, so the schema's `count: N` is enforced nowhere: an element at index ≥ N is **kept** (the 3 fixed-capacity profiles drop it — G-0011's #126 guard), and the `while (len <= id) push(default)` fill materializes `id+1` elements, so a **9-byte** input at index 2,000,000 costs cpp **226 MB** / go **122 MB** vs ~8 MB fixed — an unbounded-allocation DoS (the half of F-0008 that #126 left unfixed). Crucible finding **F-0013** |
| G-0012 | [generator#128](https://github.com/sofa-buffers/generator/issues/128) | ✅ **fixed in sofabgen 0.17.1** (commit `25d5853`, sized blob descriptor; re-verified 2026-07-16 — short blobs round-trip in `c`). Was: C backend generates a `blob` field as a bare `uint8_t[maxlen]` + the plain fixed-full-capacity `SOFAB_OBJECT_FIELD(...BLOB)` descriptor, with **no length member**. A blob is opaque bytes (no NUL recovery), so the object API pads a sub-`maxlen` blob to `maxlen` and drops an all-zero one — round-trip data loss. Fix: emit `{ uintX field_len; uint8_t field[N]; }` + `SOFAB_OBJECT_FIELD_BLOB_SIZED` (the corelib already provides it, byte-identical wire; the C++ backend already uses `FixedBytes<N>`). Crucible finding **F-0009** (found by the cross-encode oracle) |
| G-0011 | [generator#126](https://github.com/sofa-buffers/generator/issues/126) | ✅ **fixed in sofabgen 0.17.1** (commit `483c281`, bounded fill loop; re-verified 2026-07-16 — `c6 0c c6 07` → `I`, no hang). Was: C++ backend's generated `_FixedStrSeq`/`_FixedBlobSeq` (fixed-capacity string/blob arrays) do `while (out->size() <= id) out->emplace_back()`, but the corelib's fixed-capacity `InlineVector::emplace_back` is a no-op once full, so a wire element index `id ≥ N` (capacity) **loops forever** — a 4-byte DoS (`c6 0c c6 07`). Fixed-capacity C++ profile only; heap `std::vector` grows/terminates. Crucible finding **F-0008** (first mis-filed corelib-c-cpp#84, redirected via crucible#16). Fix: bound the fill by `N`, drop an over-capacity index (like the C/Zig backends) |
| G-0010 | [generator#120](https://github.com/sofa-buffers/generator/issues/120) | ✅ **fixed in sofabgen 0.16.2** (commit `26f1f4c`, PR #121): the generated zig `decode` now binds `feed(chunk)→Status` and surfaces `.incomplete` as `error.IncompleteMessage`. **Crucible driver.zig updated** to match (`error.Incomplete` → `error.IncompleteMessage`, two sites). **Re-verified 2026-07-15:** zig builds, F-0001 `80` → `I`, and the full 12-driver box is green. Was: sofabgen 0.16.1's zig backend `try`-discarded the new `Error!Status` return (compile error) — the zig analogue of G-0008. |
| G-0009 | [generator#112](https://github.com/sofa-buffers/generator/issues/112) | ✅ **fixed in sofabgen 0.16.1** (commit `7899c4b`, "heap unbounded array -> std::vector, not std::array<T,0>"). **Re-verified in Crucible 2026-07-15:** repro `03 03 07 08 09` → cpp decodes `[7,8,9]` (was `[]`) matching the family; cpp rejoined the limit-mode `arr` dimension (`scripts/run-limits.sh`), green. Was: sofabgen 0.16.0 C++ heap backend emitted a schema-*unbounded* array as `std::array<T, 0>`, silently dropping every element of an *accepted* array (the `max_dyn_array_count` cap itself still fired). Sibling of [generator#104](https://github.com/sofa-buffers/generator/issues/104) (C backend) |

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

**Former impact on Crucible:** the Rust driver used to run a **two-pass**
workaround — call `Probe::decode` for the value, then re-run `IStream::feed`
against a null visitor to recover the verdict. Faithful but wasteful (decoded
twice) — and, because the null visitor skipped the generated per-field checks, it
also missed the over-count-array rejection (see F-0003 / generator#100).

**Fix (shipped):** the Rust backend now emits a fallible entry point alongside
the back-compat `decode`:
`pub fn try_decode(data: &[u8]) -> Result<Self, sofab::Error>` (PR
[#88](https://github.com/sofa-buffers/generator/pull/88); `backend.go:303`,
`visitor.go:226`). Verified in the generated `message.rs` for both corelibs.
**Driver follow-up done** (crucible#10, 0.16.0 bump): `drivers/rust/driver.rs` is
now **single-pass** on `try_decode` — the two-pass workaround is **removed** —
mirroring the cs/java G-0008 fix. `Ok`→`A <hex>`, `Err(Incomplete)`→`I`, else
`R <class>`. Because `try_decode` runs the real generated visitor, rust now also
applies the over-count-array check (F-0003 / generator#100 re-triage — see
STATUS.md). The C (`sofab_ret_t`), Go (`error`), Python (`Probe.decode` raises),
and C++ (G-0005) backends all surface the result the same way.

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

## G-0009 — generated C++ emits a schema-*unbounded* array as `std::array<T, 0>`

**Status:** ✅ **fixed in sofabgen 0.16.1** (commit `7899c4b`, the count-less array
now generates `std::vector<T>`) — [generator#112](https://github.com/sofa-buffers/generator/issues/112).
Sibling of the C-backend [generator#104](https://github.com/sofa-buffers/generator/issues/104).
Surfaced adopting the limit-mode probe (`schema/probe-dyn.sofab.yaml`, crucible#10 /
generator#102) at sofabgen 0.16.0; **re-verified fixed in Crucible 2026-07-15** —
cpp decodes `03 03 07 08 09` → `[7,8,9]` (was `[]`) and rejoined the limit-mode
`arr` dimension (green). The rest of this entry documents the original 0.16.0 bug.

**Where:** the C++ backend, generated `probe.hpp` for a count-less `array` field.

**What:** the limit probe carries one schema-*unbounded* field of each kind — a
count-less array, a maxlen-less string, a maxlen-less blob:

```yaml
dyn_arr: { id: 0, type: array, items: { type: u32 } }   # no count -> unbounded
dyn_str: { id: 1, type: string }                        # no maxlen -> unbounded
dyn_blb: { id: 2, type: blob }                           # no maxlen -> unbounded
```

Every other backend maps the unbounded array to a **growable** type
(`uint[]` C#, `list[int]` Python, `number[]` TS, `[]const u32` Zig), and the C++
backend itself maps the unbounded **string**→`std::string` and **blob**→
`std::vector<std::uint8_t>`. But the unbounded **array** is emitted as a fixed
**zero-length** container:

```cpp
std::array<std::uint32_t, 0> dyn_arr = {};   // cannot hold any element
```

A count-less array should be `std::vector<std::uint32_t>` (the heap `cpp`
profile), mirroring the string/blob it sits next to. It looks like the backend
defaults a missing `count` to `0` and takes the fixed-`std::array<T,N>` path
meant for *bounded* arrays, instead of the dynamic-vector path.

**Why it matters (a value divergence on accepted arrays):** at decode,
`IStream::read` takes the span branch, reads `count_` varints off the wire but
writes only `min(sp.size(), count_) = 0` of them (`sofab.hpp` ~L1526). So a
**non-over-cap** array that C++ *accepts* decodes to **empty** while the family
decodes the real elements. Reproduced end-to-end: bytes `03 03 07 08 09`
(array id0 = `[7,8,9]`, under the cap) → Python/family `[7,8,9]`, C++ `[]`.

The `max_dyn_array_count` **cap itself is unaffected**: the corelib enforces it at
the array's count header (keyed on the generated `SOFAB_MAX_DYN_ARRAY_COUNT`
macro), *before* the broken container is touched — so an over-cap array still
yields `L`, agreeing with the family. The divergence is confined to the **value**
axis on accepted arrays; the verdict axis (`A`/`I`/`R`/`L`) is correct.
Confirmed on the limit-mode corpus vectors (caps baked at 8):

   | vector | family | C++ (this bug) | axis |
   |---|---|---|---|
   | `under_arr` (4 elems) | `A` `[1,2,3,4]` | `A` `[]` | **value divergence** |
   | `at_arr_8` (8, at cap) | `A` `[0..7]` | `A` `[]` | **value divergence** |
   | `over_arr` (16, over cap 8) | `L` (limit) | `L` | agree ✓ |

The maxlen-less **string** and **blob** are unaffected — only the array path is
broken — so C++ still exercises `max_dyn_string_len` / `max_dyn_blob_len` fully
and correctly.

**Proposed fix (generator):** in the C++ backend, a schema array with no `count`
must generate `std::vector<T>` (and the vector read/cap path), exactly as the
count-less string/blob already do — not `std::array<T, 0>`.

**Crucible disposition (resolved 2026-07-15):** with the 0.16.1 fix, the `cpp`
target **rejoined the array dimension** of limit mode — `scripts/run-limits.sh`
runs the full heap roster (incl. cpp) on the arr vectors and is green; the `NO_CPP`
hold-out was removed. While the bug was open, cpp was held out of *only* the array
dimension (it always ran the correct string/blob dimensions). The bug was never
worked around in generated code or masked in the comparator: a silent zero-length
array is exactly the kind of value divergence Crucible exists to catch. Repro:
`03 03 07 08 09` → cpp now `[7,8,9]` (was `[]`), and the `corpus/limits/arr/`
vectors all agree.

## G-0010 — generated zig `message.zig` discards the new finish-less decode `Status`

**Status:** ✅ **fixed in sofabgen 0.16.2** (generator [#120](https://github.com/sofa-buffers/generator/issues/120),
commit `26f1f4c` / PR #121) + a Crucible `drivers/zig/driver.zig` update. Surfaced
2026-07-15 pulling corelib-zig `main` (`0f861e4`, "decode: replace finish() with
feed(chunk)→status", plan §5/§6.1); fixed the same day. **Lang:** zig · **Where:**
the generator zig backend (generated `message.zig`), plus the Crucible
`drivers/zig/driver.zig`. The rest of this entry documents the original break.

**Fix as shipped:** the generated `Probe.decode` now returns `DecodeError!Probe`
where `DecodeError = sofab.Error || error{IncompleteMessage}`; it binds the corelib's
`feed(chunk)→Status` and returns `error.IncompleteMessage` when the terminal status
is `.incomplete` (generated `message.zig` L146-158). The Crucible driver maps that
error to the `I` verdict — `drivers/zig/driver.zig` changed `error.Incomplete` →
`error.IncompleteMessage` at both the verdict test and the reject-class switch.
Verified: zig builds `-OReleaseSafe`, `80` → `I`, empty → `A`, and the full
12-driver seed + limit box is green.

**What:** corelib-zig adopted the finish-less MESSAGE_SPEC §7 model — its `decode`
and `feed` now return `Error!Status` where `Status` is `{ complete, incomplete }`,
and **INCOMPLETE is a returned `Status`, not an error** (`istream.zig`: `pub fn
decode(buf, visitor) Error!Status`). sofabgen 0.16.1's zig backend predates this and
still emits:

```zig
try sofab.decode(data, &v);   // Error!Status now — the Status is ignored
```

which fails to compile: `error: value of type 'istream.Status' ignored`. And the
Crucible zig driver still switches on `error.Incomplete`, which is no longer a
member of the corelib's error set (`error: 'error.Incomplete' not a member of
destination error set`).

**Why it matters:** this is the **zig analogue of G-0008** (which fixed the same
INCOMPLETE-as-returned-status gap for C# and Java via status-surfacing
`TryDecode`/`tryDecode`). The corelib moved correctly to §7; the generated glue and
the driver must catch up or a zig consumer cannot tell COMPLETE from INCOMPLETE (and
here, cannot even build).

**Fix:** (1) generator zig backend surfaces the terminal `Status` from the generated
one-shot decode (a `tryDecode`-equivalent), mirroring the cs/java G-0008 fix; (2)
`drivers/zig/driver.zig` reads the `Status` and maps `.complete`→`A <hex>` /
`.incomplete`→`I`, dropping the `error.Incomplete` arm. Until both land, zig is held
out of `scripts/run.sh` / `run-limits.sh` (the box runs over the other 11 drivers).

## G-0011 — generated fixed-capacity C++ string/blob-array fill infinite-loops (DoS)

**Status:** open — [generator#126](https://github.com/sofa-buffers/generator/issues/126).
Surfaced 2026-07-15 by the structure-aware mutator + the comparator per-driver
timeout (Crucible finding **F-0008**). **Lang:** cpp (fixed-capacity / `c-cpp`
profile) · **Where:** the generator C++ backend, generated `_FixedStrSeq` /
`_FixedBlobSeq` in `probe.hpp`.

**What:** the generated element handler for a fixed-capacity string/blob array grows
the destination up to the wire element index, then writes at that index:

```cpp
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();   // id = wire element index
auto &s = (*out)[id]; ...
```

On the fixed-capacity profile `out` is the corelib's `InlineVector<T, N>`, whose
`emplace_back()` is a **no-op once full** (intentional — no heap growth):
`std::size_t i = len_ < N ? len_++ : N - 1;`. So a wire element index `id ≥ N` makes
`out->size()` stick at `N`, `size() <= id` stays true, and the `while` **never
terminates** — a 4-byte DoS (`c6 0c c6 07`: the nested `SEQUENCE_START` is element id
120 into the count-5 `string_array`). The heap profile (`std::vector`) grows and
terminates, so only the fixed-capacity C++ target hangs.

**Why it matters:** ships to any consumer of the fixed-capacity C++ profile (the
embedded target) — an unbounded loop on 4 untrusted bytes. Not a corelib bug (the
`InlineVector` cap is correct/intentional) and not a Crucible driver bug (single
`feed()`); purely the generated fill loop assuming `emplace_back()` always grows.

**Proposed fix:** bound the fill by the fixed capacity `N` and drop/ignore (or reject)
an element index `≥ N`, so the loop cannot spin on a full `InlineVector`
(`if (id < N) { while (out->size() <= id) out->emplace_back(); ... }`). Mirrors the
C/Zig backends dropping excess native-array elements (MESSAGE_SPEC §5.1). Harmless on
the heap profile.

> **Follow-up 2026-07-16 — "harmless on the heap profile" was too generous; see G-0013.**
> The fix landed on the fixed-capacity profile only, which left the heap profile as the
> lone outlier on the *value* (it **keeps** an over-index element where the fixed profile
> now drops it) and left its fill loop **unbounded** — the memory-amplification DoS this
> section's own text anticipated ("heap `std::vector` grows/terminates *or OOMs for a huge
> id*"). The hang was treated as the whole bug; it was half. Crucible finding **F-0013**.

**Correction note:** F-0008 was first mis-filed against corelib-c-cpp#84 (closed — the
corelib maintainer correctly showed `sofab_istream_feed` terminates and redirected via
crucible#16). The differential symptom (only `cpp-c-cpp` hangs) was real; the fix is
codegen.

## G-0012 — C backend generates a blob field without a length (round-trip data loss)

**Status:** open — [generator#128](https://github.com/sofa-buffers/generator/issues/128).
Surfaced 2026-07-15 by the cross-encode / structured-value oracle (Crucible finding
**F-0009**). **Lang:** c · **Where:** the generator C backend, generated `probe.h`
struct + `probe.c` field descriptors.

**What:** a `blob` field (e.g. `nested.bytes_field`, `maxlen: 4`) is generated as a
bare fixed array with the plain, fixed-full-capacity descriptor:

```c
typedef struct { … char str[33]; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD(3, message_probe_nested_t, bytes_field, SOFAB_OBJECT_FIELDTYPE_BLOB)
```

There is **no length member**, and a blob is opaque bytes (can contain `\0`), so the
object API cannot tell how many bytes are live. On re-encode it emits the full
`maxlen` (zero-padded); an all-zero sub-`maxlen` blob collapses to empty. A producer
on the C object API therefore cannot faithfully carry a blob shorter than `maxlen` —
silent round-trip data loss (`[0x01]` → `01 00 00 00`; `[0x00]` → dropped). `str`
round-trips because it is `char[maxlen+1]` and NUL-terminated; a blob can't be
NUL-recovered.

**Why it matters:** ships to every consumer of the generated C object API. Not a
corelib bug — the C `ostream`/`istream` take an explicit length (the C++ wrapper
`cpp-c-cpp`, using `FixedBytes<N>`, round-trips correctly over the *same* C sources).

**Proposed fix:** the corelib already offers the sized variant. Emit a companion
length member immediately before the buffer and use it:

```c
typedef struct { … uintX bytes_field_len; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD_BLOB_SIZED(3, message_probe_nested_t, bytes_field_len, bytes_field)
```

`SOFAB_OBJECT_FIELD_BLOB_SIZED` stores the received length on decode and "produces
byte-identical wire to a plain blob of the same actual length" (`object.h`), so the C
object API then matches the rest of the family byte-for-byte.

## G-0013 — the heap backends never enforce an index-keyed array's schema `count`

**Status:** 🆕 open, **not yet filed upstream**. Crucible finding **F-0013** (found
2026-07-16 while building `corpus/regression/`). Affects every **heap** profile: go,
rust-std, cpp, py-cython, py-pure, java, typescript, csharp, zig. The fixed-capacity
profiles (c, cpp-c-cpp, rust-nostd) are correct.

`schema/probe.sofab.yaml` declares `string_array` as `items: {type: string, count: 5}`.
That `count` reaches the fixed-capacity backends as a container capacity — and is then
**enforced**, because G-0011's fix bounded the fill by it. The heap backends emit an
**unbounded container** and an **unbounded fill**, so `count` is enforced nowhere:

```cpp
// c-cpp (fixed): the G-0011 / #126 guard — drops an over-index element
if (static_cast<std::size_t>(id) >= out->capacity()) return;
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();

// cpp (heap): no guard — grows to id+1 and keeps it
while (out.size() <= static_cast<std::size_t>(id)) out.emplace_back();
out[id] = std::move(_s);
```

Same shape in Rust, where the container type shows the cause directly — `rust-std` gets
`Vec<String>`, `rust-nostd` gets `heapless::Vec<heapless::String<64>, 5>`:

```rust
(_Loc::Root_string_array, _) => { while self.m.string_array.len() <= id as usize { self.m.string_array.push(Default::default()); } self.m.string_array[id as usize] = _s; }
```

**Two consequences.** (1) A **value divergence**: a `string_array` element at index 120
is dropped by the 3 fixed profiles and kept by the 9 heap profiles — all 12 *accept*, so
no accept/reject oracle sees it. (2) A **memory-amplification DoS**: the fill materializes
`id+1` elements and `id` is an unbounded varint, so a **9-byte** input at index 2,000,000
costs cpp **226 MB** / go **122 MB** where the fixed profiles stay at ~8 MB — raise the
index until OOM.

**Fix:** emit the schema `count` as a guard in *every* backend's index-keyed fill, not
only where the container happens to be fixed-capacity — the count is already known at
generation time (it is what produces `InlineVector<...,5>` / `heapless::Vec<_,5>`). The
C++ heap `_BlobSeq` has the identical unguarded shape, so index-keyed blob arrays are
almost certainly affected too (untested — `probe` has no blob array). If the spec instead
makes an over-index element `INVALID`, the guard becomes a reject; the allocation must be
bounded either way. See `findings/F-0013-overindex-string-array-element-kept-vs-dropped/`.
