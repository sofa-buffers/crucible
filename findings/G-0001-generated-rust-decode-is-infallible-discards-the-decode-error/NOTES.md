# G-0001 — generated Rust `decode` is infallible (discards the decode error)

**Status:** ✅ **fixed** in sofabgen 0.15.1 (PR
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
STATUS-LOG.md). The C (`sofab_ret_t`), Go (`error`), Python (`Probe.decode` raises),
and C++ (G-0005) backends all surface the result the same way.
