# F-0010 — under-count fixed array round-trips to different values (pad-to-capacity vs keep-count)

**Status:** ✅ **RESOLVED in sofabgen 0.17.2** ([generator#136](https://github.com/sofa-buffers/generator/issues/136),
PR #137) — the trim/pad question is settled family-wide. The clause was **adopted
upstream — [documentation#18](https://github.com/sofa-buffers/documentation/pull/18)**
merged (`ac621db`, §3 + §5.1), closing [documentation#16](https://github.com/sofa-buffers/documentation/issues/16).
A simpler **always-N** alternative was considered and rejected — *"a present fixed array always carries
exactly `N` elements on the wire"*: it would change only the keep-M camp and match the systems camp's
current encoding, but forgoes the trailing-default compaction; the adopted **sparse fill-to-N** reading
keeps that compaction. (Design alternative migrated from the retired `spec-proposals.md`.)
Like F-0001 (truncation) / F-0004 (UTF-8): resolved spec-first, then per-impl.
**Attribution settled: codegen (sofabgen), not corelib** — both fixes need schema
knowledge (`N`, fixed-vs-dynamic) the schema-agnostic corelib array writers don't
have; the corelibs faithfully write `count = len(passed slice)` and are correct.

**Re-verified 2026-07-16 (sofabgen 0.17.2):** the R1/R2 reproducers (`u32_count3`,
`i16_count1`) now round-trip to the **canonical count 3 / count 1 on all 12 drivers** —
the systems camp (c, rust×2, cpp, cpp-c-cpp, zig) now trims the trailing default run;
C got its half via **corelib-c-cpp#87** (`937f60b`). ⚠️ The **same go changeset**
introduced a *separate* regression — an all-default `count:N` array field emitted
explicitly instead of omitted (§2) — split out as **[F-0011](../F-0011-go-fixed-count-array-not-omitted/NOTES.md)**
/ [generator#139](https://github.com/sofa-buffers/generator/issues/139). That is not the
under-count value bug: go trims the *populated* array correctly here.

## Adopted resolution (documentation#18): sparse **fill-to-N**, elide the trailing default run

`count: N` is a **fixed-length** array of exactly `N` logical elements. A wire count
`M < N` is a *trailing-default run* (last `N−M` elements = element default). Normative:
- **decode** — MUST materialize exactly `N` elements (M received + defaults at `[M,N)`),
  **regardless of storage model** — a growable list MUST default-fill to `N` too.
- **canonical encode** — MUST set `M` = one-past-the-last-non-default element and
  MUST NOT emit the trailing default run. (A decoder still *accepts* a non-canonical
  wire that carries trailing defaults.)
- `M > N` and element id `≥ N` are `INVALID` (§7).

So the **canonical wire for `[7,8,9]` in a `count:5` array is count 3** (`2303 070809`),
not count 5 — the compact form, same sparse principle as omitting a default scalar field.

## Compliance re-check 2026-07-16 (all 12 drivers) — neither camp fully compliant

| camp | drivers | decode fill-to-N (§5.1) | canonical encode / elide trailing (§3) | round-trip wire |
|---|---|---|---|---|
| **systems** | c, rust-std, rust-nostd, cpp, cpp-c-cpp, zig | ✅ fills to N | ❌ **emits trailing run** (count 5) | `2305 070809 0000` |
| **managed** | go, py-cython, py-pure, java, typescript, csharp | ❌ **keeps M** (no fill) | ✅ canonical (count 3) | `2303 070809` |

- The **systems** camp's violation is **observable** on the wire (count 5 ≠ canonical
  count 3) — this is the F-0010 round-trip divergence. Fix: trim trailing default
  elements on encode.
- The **managed** camp's violation is **latent / round-trip-masked**: they hold only
  `M` elements (go confirmed by source — `[]uint32` slice, `m.U32 = _narrowU(v)`,
  encode writes `len(m.U32)`), so `len()==3` and `elem[3..5]` are absent instead of
  default `0`; but because their re-encode also yields count 3, the round-trip oracle
  sees canonical wire and can't flag it. Only a direct element/length access test can.
  **A genuine limitation of the round-trip oracle**, worth a dedicated element-access
  probe if we want to gate the managed camp's decode side.

Attribution of the systems-camp encode fix was traced (the F-0008 lesson applied):
the corelib array writers only write `count = len(passed slice)` (C
`sofab_ostream_write_array_of_*` gets the count as `field->size/element_size`; Rust
`write_array_unsigned(id, data: &[T])` writes `data.len()`; Go `WriteUnsignedArray`
writes `len(slice)`) and are **correct**. Both fixes need schema knowledge the corelib
lacks — `N` for decode-fill, and fixed-vs-dynamic for encode-trim (a *dynamic* array
must keep trailing defaults) — so it is a **codegen** change. Filed as
**[generator#136](https://github.com/sofa-buffers/generator/issues/136)** with R1/R2
reproducers + per-backend scope (encode-trim: all backends, observably wrong in the 6
fixed-storage ones; decode-fill-to-N: the 5 growable backends).
**Found:** 2026-07-16 by the **cross-encode / structured-value oracle**, slice 2
(the array value space, `engine/structured/gen.py`) — on its first run over arrays.
**Axis:** accept_value (round-trip) — the same wire decodes to different values.

## The divergence (a clean 6-vs-6 camp split)

A fixed-count array (schema `count: 5`) that receives **fewer** than 5 elements on
the wire (`0 < wire count < 5`) re-encodes two different ways:

Input `arrays.u32 = [7,8,9]` (wire count 3) — `u32_count3.bin`:

| camp | decodes/re-encodes as | wire | drivers |
|---|---|---|---|
| **pad to capacity** | `[7,8,9,0,0]` (count 5) | `…2305 070809 0000…` | **c, rust-std, rust-nostd, cpp, cpp-c-cpp, zig** |
| **keep wire count** | `[7,8,9]` (count 3) | `…2303 070809…` | **go, py-cython, py-pure, java, typescript, csharp** |

`i16_count1.bin` (`arrays.i16 = [-42]`, count 1) splits the same way. The split is
**along the memory model**: fixed-array storage (systems langs — C `uint32_t[5]`,
Rust `[u32;5]`, C++ `std::array`, Zig) fills the array to its full capacity with the
default and re-encodes all 5; growable storage (managed langs — Go slice, Python
list, Java/C#/TS arrays) keeps the 3 elements it received and re-encodes count 3.

## Boundaries (isolated)

- **count 0** (explicit empty array) → **all agree** (`arr_empty` is in the green
  cross-encode gate): an all-default array is omitted on re-encode by everyone.
- **count == schema (5)** → **all agree** (full arrays are in the green gate).
- **count > schema** → INVALID for scalar arrays (that is F-0003 / generator#100,
  resolved). This is the distinct *under*-count case.

So the divergence is specifically `0 < wire count < schema count`.

## Why it matters / resolution path

An under-count array is a valid wire message (not truncated, not over-count) that
**round-trips to a different value** depending on the decoder's storage model — a
silent interop bug of the exact kind Crucible exists to catch, and one the
malformed-wire fuzzer would not cleanly produce (it needs a well-formed short array).

This was a **MESSAGE_SPEC underspecification** — the spec fixed the array `count` and
defined over-count as INVALID (§3/§7) but not the *under*-count decode. **Now resolved:
documentation#18 adopted the sparse fill-to-N reading** (see the "Adopted resolution"
section above). Note the adopted answer is the *compact* one — decode fills to `N`
internally, but the **canonical wire elides the trailing default run** (count 3, not
5), so the managed camp's wire was already canonical and it is the **systems** camp
that must change (trim trailing defaults on encode). This is the opposite of the
"move the managed camp to pad-to-capacity" guess made when this finding was first
written. Tracked like F-0001/F-0004 (spec-first, family-wide).

## Reproducers

- `u32_count3.bin` — `56 07 a6 06 23 03 07 08 09 07 07 c6 0c 07` (`arrays.u32=[7,8,9]`)
- `i16_count1.bin` — `56 07 a6 06 1c 01 53 07 07 c6 0c 07` (`arrays.i16=[-42]`)

## Harness note

Kept OUT of the green `corpus/structured/` cross-encode gate (which uses count-0 and
full-count arrays, all green); the under-count vectors live here as the finding —
mirroring how F-0004/F-0009's divergent inputs are kept out of the green gates.
