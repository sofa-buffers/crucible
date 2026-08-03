# G-0013 — the heap backends never enforce an index-keyed array's schema `count`

**Status:** ✅ **fully fixed 2026-07-17**, in two steps —
[generator#142](https://github.com/sofa-buffers/generator/issues/142) (sofabgen 0.17.4:
the DoS is gone, cpp 226 MB → 10 MB, and the 9 heap backends reject) then
[generator#149](https://github.com/sofa-buffers/generator/issues/149) → #151/#150
(0.17.6: the fixed-capacity C family and no_std reject too, closing the residual where
`c`/`cpp-c-cpp`/`rust-nostd` still accepted and silently dropped). Re-verified: all 12
emit `R` on `overindex_clean`, which is in the green regression gate. Crucible finding **F-0013** (found
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
