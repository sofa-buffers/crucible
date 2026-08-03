# G-0011 — generated fixed-capacity C++ string/blob-array fill infinite-loops (DoS)

**Status:** ✅ **fixed in sofabgen 0.17.1** (commit `483c281`, bounded fill loop) —
[generator#126](https://github.com/sofa-buffers/generator/issues/126) closed
2026-07-15. Re-verified 2026-07-16: `c6 0c c6 07` → `I`, no hang. Fix: bound the fill
by `N` and drop an over-capacity index, as the C and Zig backends already did.
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
