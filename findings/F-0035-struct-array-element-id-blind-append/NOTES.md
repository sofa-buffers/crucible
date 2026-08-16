# F-0035 — generated struct-array element decode appends id-blind (10 backends), corrupting values on id gaps and reopens


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — vectors promoted 2026-08-16, replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Filed:** [generator#247](https://github.com/sofa-buffers/generator/issues/247)

**Family:** `poc/omit-all-default-sequences` (found 2026-07-27, the day WP-05 folded
`struct_array` into `probe`; the code paths are branch-independent — verify against
`main` once the POC merges).

## The split

`gap_elem.bin` — `u8=1` + `seq[202]( elem0{k=1}, elem2{k=3} )`, element id 1 absent
(an interior gap):

| camp | re-encode | meaning |
|---|---|---|
| `c`, `cpp`, `dart` | `seq[202]( elem0{k=1}, elem1(), elem2{k=3} )` | element **placed at its id**; the gap reconstructs the all-default element — the 3-element array `[{k:1}, {}, {k:3}]` (§5.1) |
| `go`, `rust-std`, `rust-nostd`, `cpp-c-cpp`, `py-cython`, `py-pure`, `java`, `typescript`, `csharp`, `zig` | `seq[202]( elem0{k=1}, elem1{k=3} )` | element **appended** — `{k:3}` lands at **index 1**, the array silently shortens to `[{k:1}, {k:3}]` |

`reopen_elem.bin` — element id 0 framed twice (`{k=5}` then `{v="A"}`): the placing
camp **merges** into one element `{k:5, v:"A"}` (§7.4 struct-merge applied at the
element position); the appending camp emits **two** elements `[{k:5}, {v:"A"}]`.
`ctl_dense.bin` (dense ids 0,1) — all 13 agree, which is why the value corpus (whose
canonical wire is always dense) never showed this.

## Why the appending camp is wrong

MESSAGE_SPEC §5.1: the element id **is** the array index (*"id = index"*, length =
*highest present id + 1*). The POC §2 sharpens the stakes: element presence *carries
the container length*, so an id-blind append changes the decoded **value**, not
bytes. corelib-cpp documents the rule verbatim, with this exact counterexample
(`sofab.hpp:3040-3049`, `MessageSeq::deserialize`):

> *"the element id IS the array index, so an element is PLACED at `dest[id]`, never
> appended. … Appending instead would silently SHORTEN the array by the size of the
> gap: wire `06 0005 07 16 0009 07` … is the 3-element array `[5, 0, 9]`, not `[5, 9]`."*

## Attribution — codegen (generator), G-0020

The generated code, not the corelibs: sofabgen's **leaf**-element path already places
by id, its **struct**-element path appends. Both are visible side by side in one
generated file (`drivers/python/build/gen/message.py`, `Probe._unmarshal`):

- `string_array` (id 200): `while len(self.string_array) <= _ef0.id: append("")` then
  `self.string_array[_ef0.id] = d.string()` — **id-honoring**.
- `struct_array` (id 202): `_e0._unmarshal(d); self.struct_array.append(_e0)` —
  `_ef0.id` consulted only for the capacity check, **never for placement**.

The `cpp` vs `cpp-c-cpp` split inside one language is the classic generated-container
indictment (CLAUDE.md triage step 3): heap `cpp` decodes through corelib-cpp's
`MessageSeq` (id-placing, quoted above), while the `c-cpp` profile's generated C++
object layer carries its own append-shaped container path.

## Repro

```
CORPUS=findings/F-0035-struct-array-element-id-blind-append ./scripts/run.sh
```

Carved out of the blocking axes until fixed (the F-0034 pattern):
`sweep_repeated_id` (202 element reopen) and `sweep_empty_frame`
(`interior_gap_elem`, `empty_merge` at the element position) mark the cells with
this finding id.

## Resolution

**Impls:** generator (codegen, **G-0020**) — 10 backends (go, rust×2, cpp-c-cpp object layer, py×2, java, ts, cs, zig); `c`/`cpp`/`dart` place by id · **Axis:** accept_value (round-trip; a decoded-**value** corruption)

✅ **RESOLVED in sofabgen 0.21.0** — [generator#247](https://github.com/sofa-buffers/generator/issues/247) closed. **Re-verified 2026-07-29** against corelibs **0.9.0 @ main** + sofabgen **0.21.0** — the first family carrying the merged sparse-array rewrite (documentation#29/#31). All three reproducers (`ctl_dense`, `gap_elem`, `reopen_elem`) now agree across the 13-driver roster. *History:* Found 2026-07-27, the day WP-05 folded `struct_array` into `probe` (poc family). §5.1: the element id IS the index, length = highest present id + 1; corelib-cpp's `MessageSeq` documents it verbatim with this exact counterexample (`sofab.hpp:3040`). Smoking gun in one generated file: `message.py` places `string_array` by id (`list[_ef0.id] = …`) but `append`s `struct_array` elements. The `cpp` vs `cpp-c-cpp` split inside one language indicts the generated container (triage step 3). Dense-id control agrees on all 13 — canonical wire is always dense, which is why the value corpus never saw it. Carved out of the blocking `sweep_repeated_id` + `sweep_empty_frame` cells; reproducers in `findings/F-0035…/`
