# F-0026 — a re-opened blob_array wrapper keeps a stale zeroed element (C object API)

**Status:** ✅ **RESOLVED — [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) fixed & closed**
(commit `2416a2b`, "reset sized-blob used-length in `sofab_object_init` (§7.4 re-open)"; verified
2026-07-22 on `origin/main`). All 4 isolates → **all 13 drivers agree** (`c` now drops the re-opened
element); the `elem=="blob"` carve-out was removed from the repeated-id (§7.4) sweep (green with the
blob wrapper, 16 vectors) and the isolates promoted into `corpus/regression/` (`F0026_*`).
MESSAGE_SPEC §7.4 requires a re-opened **array wrapper**
to be **replaced whole**; the C object API had kept the earlier occurrence's slots, zeroed, instead of
dropping them. **Corelib-only** (`corelib-c-cpp`, the pure-C object API — the `c` driver), **not
codegen**. **Axis:** accept_value (round-trip) — all 12 accept, `c` re-encodes a value the other 11
drop. **Found:** 2026-07-21 by the repeated-id sweep (`engine/structured/sweep_repeated_id.py`, §7.4)
the moment a `blob_array` was added to `schema/probe.sofab.yaml` — the blob analogue of the
`string_array` wrapper the sweep already covered green.

## The split

Re-open the `blob_array` wrapper (id 201) with a *different* element than the first opening. §7.4
(documentation#23): an **array wrapper is replaced whole** on re-open — the earlier contents are
discarded. The `string_array` (id 200) equivalent is uniform across all 12; the **blob** wrapper
splits `c` off alone.

| camp | behaviour on re-open | drivers |
|---|---|---|
| **replace whole** (conformant §7.4) | earlier element dropped | go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig (11) |
| **keep the earlier slot, zeroed** | element 0 survives as an all-zero blob | **c (1)** |

## The reproducers, byte for byte

`blob_reopen_empty.bin` = `ce0c 0213dead 07 ce0c 07` (10 B) — the minimal isolate:

| bytes | meaning |
|---|---|
| `ce0c` | header `(id 201, WT_SEQ_BEG=6)` — open `blob_array` |
| `0213dead` | element `id 0`, fixlen word `(len 2 << 3) \| BLOB(3)`, payload `de ad` |
| `07` | WT_SEQ_END — close |
| `ce0c` | header `(id 201, WT_SEQ_BEG)` — **re-open** `blob_array` |
| `07` | WT_SEQ_END — close (empty second opening) |

Per §7.4 the second (empty) opening **replaces** the array whole → the final `blob_array` is empty.

- **11 drivers** re-encode `…c60c07 ce0c07` — `blob_array` present but empty (element 0 dropped). ✓
- **c** re-encodes `…c60c07 ce0c 0213 0000 07` — element 0 **survives** as a 2-byte blob `00 00`. ✗

`blob_reopen_two.bin` = `ce0c 0213dead 07 ce0c 0a13beef 07` (14 B) is the direct mirror of the
green `string_array` control: first opening sets element `id0 = dead`, second sets `id1 = beef`.
The 11 replace → `{id1 = beef}`; **c** merges+zeros → `{id0 = 0000, id1 = beef}`. Conformance
agrees (all 12 accept — a re-opened wrapper is legal), so the split is purely on the **value**.

## Root cause — the sized-blob length is not reset on the §7.4 replace-init

The C object API implements §7.4's replace-whole correctly at the dispatch level: on opening a
`fixed_seq` wrapper it re-initialises the holder before reading the new occurrence
(`vendor/corelib-c-cpp/src/object.c:562-565`):

```c
// MESSAGE_SPEC §7.4: a re-opened array wrapper *replaces* the array value whole …
// Reset its slots to their defaults on open so a later occurrence overwrites rather than merges;
if (nested->info->fixed_seq)
    sofab_object_init(nested->info, nested->dst);
```

The bug is one level down, in `sofab_object_init` (`object.c:231-256`). A **sized blob** slot is laid
out `{ len; buf[N]; }` with the length member **immediately before** the buffer, and its descriptor
(`SOFAB_OBJECT_FIELD_BLOB_SIZED`, `object.h:112`) sets `(offset, size)` to cover **only `buf`**; the
companion length lives at `offset - nested_idx` (`nested_idx` holds the length width). Every other
site honours that convention:

| function | site | handles the sized-blob length? |
|---|---|---|
| `_field_is_default` | `object.c:205-212` | ✅ reads used_len at `offset - nested_idx` |
| `sofab_object_encode` | `object.c:354-365` | ✅ reads used at `offset - nested_idx` |
| decode store | `object.c:499-505` | ✅ writes used at `offset - nested_idx` |
| **`sofab_object_init`** | **`object.c:242-254`** | ❌ **generic `memset(obj+offset, 0, field->size)` — zeros `buf` only; never touches `len`** |

So the reset zeros the buffer but leaves `items[0].len == 2` stale. On re-encode `_field_is_default`
sees `used_len != 0` → element 0 is "present" → emitted as a 2-byte `00 00` blob. A **string** slot
has no separate length (it is NUL-terminated / content-derived), so zeroing its buffer *does* reset
it to empty — which is why `string_array` (id 200) replaces correctly and only the blob wrapper breaks.

## Attribution — corelib, not codegen

Per the CLAUDE.md triage: *does the fix need knowledge only the schema has?* **No.** The descriptor
already flags the slot as a sized blob (`type == BLOB && nested_idx != 0`) and encodes the length
width in `nested_idx`; `sofab_object_init` has every fact it needs. The fix is a corelib one-liner —
give `sofab_object_init` the same `nested_idx != 0` branch its three sibling functions carry, zeroing
the length at `offset - nested_idx`. **The generated descriptor is correct** (it faithfully describes
the documented sized-blob ABI). Filed against **`corelib-c-cpp`**:
[corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) (observed on `56c88fa`).

Confirmed corelib-only by the sibling profile (CLAUDE.md diagnostic step 3): `cpp-c-cpp` — the C++
wrapper over the *same* corelib-c-cpp `istream`/`ostream` — **agrees with the family**, because it
uses the C++ `sofab::FixedBytes` object layer, not the C `object.c` descriptor path. Only the pure-C
object API reopens through `sofab_object_init`. This is the reset/init counterpart of the
neighbourhood F-0009 (sized-blob encode) and F-0013 (`_BlobSeq` over-index) already hardened — a
distinct residual reachable **only** via a §7.4 wrapper re-open, which had no test until `probe`
carried a blob array.

## Reproducers

`blob_reopen_empty.bin` (minimal, 10 B), `blob_reopen_two.bin` (14 B, the string-control mirror) —
the 2 diverging vectors. Controls (all 12 agree, must stay agreeing):

- `control_str_reopen.bin` (`c60c020a4107c60c0a0a4207`) — the **string_array** re-open at id 200,
  the exact analogue: all 12 replace to `{id1='B'}`. Isolates the divergence to the blob element type.
- `control_blob_single.bin` (`ce0c0213dead07`) — a `blob_array` opened **once** (no re-open) with
  element 0 = `dead`: all 12 keep it. Guards that a plain blob array is fine; only the re-open init breaks.

```sh
# reproduces the split; go through run.sh (never point the comparator at drivers/*/build/
# after a limit-mode run — it leaves probe-dyn binaries there)
CORPUS=findings/F-0026-c-blob-wrapper-reopen-stale-element ./scripts/run.sh
# 4 inputs: 2 controls agree, 2 reproducers diverge (accept_value) — c keeps a zeroed element
```

## Relationship to the §7.4 family and the blob path

The §7.4 axis (repeated-id sweep), a new position. F-0019 opened it (duplicate sequence id — merge
vs replace) and was resolved family-wide in 0.19.2; the sweep confirmed the **string** wrapper
re-open green at every position. Adding the `blob_array` exercised the same rule on a sized-blob
holder for the first time and caught the reset gap. The over-bound blob path (§7.1, over-index /
over-maxlen) that F-0013 left untested for lack of a blob array is, by the same integration,
**green** — so `_BlobSeq` enforces its `count`/`maxlen`; only the re-open init is wrong.

Kept **out** of the green `corpus/regression/` gate and carved out of the blocking repeated-id sweep
axis (`sweep_repeated_id.py`, the `elem == "blob"` skip) until the corelib fix lands — mirroring how
F-0025 keeps the wiretype axis report-only. When it lands: re-pull corelibs, drop the skip, verify
the axis goes green, promote `blob_reopen_empty.bin` into the gate.
