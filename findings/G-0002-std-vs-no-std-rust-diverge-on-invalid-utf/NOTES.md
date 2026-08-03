# G-0002 — std vs no-std Rust diverge on invalid UTF-8 in a string

**Status:** ✅ **fixed** in sofabgen 0.15.1 (PR
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
