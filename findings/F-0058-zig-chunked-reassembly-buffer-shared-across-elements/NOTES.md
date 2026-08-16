# F-0058 — sofabgen's Zig backend shares one reassembly buffer across every split payload, so array elements alias each other

**Status:** ✅ **RESOLVED** — [generator#293](https://github.com/sofa-buffers/generator/issues/293) fixed by
**Guard:** corpus/regression — vectors promoted 2026-08-16. **Half a guard, stated plainly:** the gate replays them whole, so it holds the one-shot verdict. The chunk-boundary behaviour this finding was actually about is owned by `scripts/run-chunked.sh`, which does not replay this corpus — wiring it to is in docs/TODO.md.
**Issue:** [generator#293](https://github.com/sofa-buffers/generator/issues/293), [generator#295](https://github.com/sofa-buffers/generator/issues/295)
**Codegen:** G-0036 | [generator#293](https://github.com/sofa-buffers/generator/issues/293), [generator#295](https://github.com/sofa-buffers/generator/issues/295) | the generator side of F-0058 — the Zig backend's chunked reassembly buffer is shared across split payloads, so wrapper-array elements alias each other

generator#294 (`alloc.dupe` out of the shared `acc`), which turned out to be **incomplete**: re-measuring took
the axis from 25 mismatches to 14, not to 0. The residual was filed as
[generator#295](https://github.com/sofa-buffers/generator/issues/295) and fixed by generator#296 — *the
streaming decoder owns its payloads, it cannot borrow*. Verified 2026-08-04 over the 9038-input fuzzed corpus:
**19 mismatches → 0**. See [`results/FINDINGS.md`](../../results/FINDINGS.md), which owns this finding's state;
this file is the evidence. Also logged as codegen defect **G-0036**.

**Found 2026-08-04**, on the first run of the **chunked-decode axis**
([crucible#132](https://github.com/sofa-buffers/crucible/issues/132)). It is invisible to every
other gate in this repo by construction: the replay protocol hands each record over whole, and a
payload that arrives whole is never reassembled.

## What happens

Two `string_array` elements, each split across `feed` calls, **both end up holding the last
one's bytes**.

`c6 0c 02 12 61 62 0a 12 63 64 07` — eleven bytes, `string_array = ["ab", "cd"]`:

| | element 0 | element 1 |
|---|---|---|
| whole (one feed) — **correct** | `ab` | `cd` |
| `SOFAB_CHUNK=1` | **`cd`** | `cd` |

`blob_array` is identical (`ce 0c 02 13 61 62 0a 13 63 64 07` → `["ab","cd"]` becomes
`["cd","cd"]`), which is expected: both go through the same generated helper.

Every other implementation is chunk-invariant on these inputs. On the seed corpus the axis reports
**25 mismatches for zig and zero for c, rust-std, rust-nostd, cpp, cpp-fixed, cpp-c-cpp,
typescript, java, csharp and dart.**

## The cause — one shared buffer, and a slice into it

`_reassemble` in the **generated** `message.zig`:

```zig
fn _reassemble(self: *_dec_Probe, total: usize, offset: usize, chunk: []const u8) ?[]const u8 {
    if (offset == 0 and chunk.len >= total) return chunk; // whole payload, borrow it
    if (offset == 0) self.acc.clearRetainingCapacity();
    self.acc.appendSlice(self.alloc, chunk) catch { self.inv = true; return null; };
    if (self.acc.items.len < total) return null;          // more chunks to come
    return self.acc.items;                                //  <-- ONE buffer, reused
}
```

`self.acc` is a single `ArrayListUnmanaged(u8)` on the visitor. The returned slice is handed
straight to the store:

```zig
sofab.arrays.setElem([]const u8, self.alloc, &(self.m.string_array), id, "", chunk);
```

`setElem` stores the slice as-is — deliberately, because the borrow case above depends on it. So
the moment the *next* split payload calls `clearRetainingCapacity()` and appends over the same
memory, every element stored earlier is looking at the new content.

The whole-payload branch is fine: it borrows the caller's chunk, and different elements borrow
different regions of it. Only the reassembled branch collapses onto one buffer.

## It gets worse when the buffer grows

`clearRetainingCapacity` keeps the capacity, so a later payload larger than any before it makes
`appendSlice` **reallocate** — and the earlier elements' slices are then rebased onto whatever
sits at the old address.

`r2_realloc_rebases_first.bin`: element 0 is `ab` (2 B), element 1 is 60 bytes of `A B C …`:

| | element 0 | element 1 |
|---|---|---|
| whole — **correct** | `ab` (`6162`) | `ABCDEF…` (60 B) |
| `SOFAB_CHUNK=1` | **`AB`** (`4142`) | `ABCDEF…` (60 B) |

Element 0 now reads the first two bytes of the *reallocated* buffer.

Two consequences follow, and the second is the reason this is more than a wrong value:

1. **A stale-length read.** A slice stored when the buffer held 60 bytes still has length 60 after
   a 2-byte payload replaces it, so reading it walks past the live content into the allocation's
   spare capacity. This is visible in the seed corpus as `t5:66697665aa` — a 5-byte string read
   out of the 4-byte `five`, with one byte of adjacent memory.
2. **A dangling read under a freeing allocator.** Here the driver decodes into an arena, which
   does not release the old block, so the rebased read above returns stale-but-mapped bytes. Under
   a general-purpose allocator the same realloc frees the old block and the earlier elements
   become pointers into freed memory. *That step is reasoned from the code, not observed —* this
   driver uses an arena by design, and no sanitizer report was produced.

## Controls

| file | bytes | what it pins |
|---|---|---|
| `r0_two_string_elems.bin` | 11 | `string_array`: `["ab","cd"]` → `["cd","cd"]` |
| `r1_two_blob_elems.bin` | 11 | `blob_array`: same defect, same helper |
| `r2_realloc_rebases_first.bin` | 70 | growth reallocates and rebases the earlier element |
| `ctl_one_string_elem.bin` | 7 | **a single split element decodes correctly** |

The control is what pins the mechanism: with only one reassembled payload in the message there is
no second user of the buffer, and the value is right. The defect needs **two or more** payloads
that are split, which is why byte-at-a-time feeding finds it immediately and a two-way split
usually does not.

## Attribution — the generator (sofabgen's Zig backend)

`_reassemble` and the `setElem` call are both emitted into `message.zig`; neither is corelib code.
The corelib delivers `(total, offset, chunk)` faithfully — the accumulation is entirely the
generated visitor's, and so is the decision to store a slice rather than a copy. Whether an
element's destination needs its own copy is a *storage* question, which under CLAUDE.md's split is
generated code's to answer: it is the side that knows the field is a wrapper array whose elements
outlive the callback.

That the same schema, decoded by the same corelib, is correct in every other backend is the
second half of the argument — this is one backend's emitted reassembly, not a wire-level rule
anyone disagrees about.

## Suggested fix

Give each reassembled payload its own allocation instead of a shared buffer — the simplest
version is to `dupe` out of `acc` before handing the slice to `setElem`, which also removes the
stale-length and realloc hazards at once. Keeping the shared buffer and copying at the store side
would work too, but only if every store site remembers; the borrow branch already proves how easy
that is to miss.

## Effect on the Crucible gates

`zig` was held out of `scripts/run-chunked.sh`'s opt-in roster while this was open. **Back in as of
2026-08-04**, after the residual fix — and re-measured rather than assumed, which mattered: the
first fix closed the issue while leaving 14 live mismatches, so taking the closed ticket as proof
would have put the driver back into a blocking gate carrying them.

## A neighbouring, separate question

corelib-zig documented that a string or blob arriving whole in one chunk was **borrowed** from that
chunk and that "a fed chunk must outlive the message", which made `SOFAB_CHUNK_SCRUB` inapplicable
there while every other backend copied. generator#296 resolved that from the implementation side by
removing the borrow from the streaming path entirely, so the scrub axis now applies to zig like
everywhere else and the driver's exit-3 carve-out is gone. The family-level *spec* question remains
open as [documentation#37](https://github.com/sofa-buffers/documentation/issues/37).
