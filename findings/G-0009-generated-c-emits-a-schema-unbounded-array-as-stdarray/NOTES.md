# G-0009 — generated C++ emits a schema-*unbounded* array as `std::array<T, 0>`

**Status:** ✅ **fixed in sofabgen 0.16.1** (commit `7899c4b`, the count-less array
**Issue:** [generator#112](https://github.com/sofa-buffers/generator/issues/112)

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
