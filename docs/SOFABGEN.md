# sofabgen improvement log

Weaknesses in **generated** code that Crucible surfaced while building drivers.
Crucible tests the corelibs, but the generated glue is part of what ships to
users — where the codegen makes a driver harder to write faithfully, or bakes in
a cross-implementation divergence, it is recorded here as a candidate change to
`sofabgen` (repo: `generator/`).

Each entry: what, where, why it matters for the differential fuzzer, proposed
fix. Status: `open` until the generator change lands.

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
The C (`sofab_ret_t`) and Go (`error`) backends already surface the result — Rust
is the outlier.

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
