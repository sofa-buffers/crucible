# G-0005 — generated C++ `decode` is infallible (same gap as G-0001)

**Status:** ✅ **fixed** in sofabgen 0.15.1 (PR
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
