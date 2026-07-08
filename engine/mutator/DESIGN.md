# Structure-aware mutator — design & build note

Target for `TODO.md` Phase 3 #1. A fresh session should be able to build the
mutator from this file + `docs/PLAN.md` §5 + `documentation/CORELIB_PLAN.md` §4.

## Why
The C pacemaker (`scripts/fuzz.sh`, the `CRUCIBLE_LIBFUZZER` path in
`drivers/c/driver.c`) currently uses libFuzzer's **byte-level** mutator. On a
self-describing TLV format that means most mutations corrupt an early
header/length byte and get rejected in the first parse step, so deep paths
(nested sequences, array counts, varint boundaries, the depth limit) are reached
only by luck. A **grammar-aware** mutator edits the wire at the *field* level, so
it stays parseable-ish and drives the decoder into those deep paths on purpose —
and it directly manufactures the two spec-question inputs (§7 truncation, §8
invalid UTF-8).

## Wire grammar it must know (authoritative: CORELIB_PLAN §4)
- **Varint** (§4.1): base-128 little-endian; **MSB `0x80` = continuation** ("more
  bytes"). IDs, lengths, counts, and integer values are all varints.
- **Field header** (§4.3): one varint `header = (id << 3) | type`; the low 3 bits
  are the wire type (8 types: unsigned varint `0`, signed zig-zag varint `1`,
  fixlen fp32/fp64/string/blob, arrays, and sequence begin/end — see the §4.3
  table for the exact tags).
- **Sequences** (§4.9): a begin marker … children … end marker; `MAX_DEPTH = 255`.
- A message is a flat stream of fields; no overall length prefix.

## Mutation operators (pick one per call, weight roughly evenly)
Operate on the raw wire bytes; best-effort walk field-by-field, then apply:

**Varint** — the highest-value class:
- truncate a varint (drop its terminating byte → **incomplete**, exercises §7);
- extend a varint (append continuation bytes, push **past 64 bits** → INVALID);
- flip a continuation bit; set to boundary values (`0`, `2^64-1`, `ID_MAX`, `> ID_MAX`).

**Header/type**:
- change a field `id` (tiny ↔ huge, straddle `ID_MAX`);
- change the 3-bit type tag (valid ↔ reserved/invalid; make a scalar look like a
  sequence or fixlen).

**Length / count**:
- for a fixlen field, set the declared length ≠ the bytes that follow (over/under
  → truncated payload, §7);
- for an array, claim a huge `count` (e.g. `2^32`) with few elements, or `0`.

**Sequence**:
- open a sequence without closing (dangling → §7 open-sequence);
- emit an end marker with nothing open (unbalanced);
- nest to `MAX_DEPTH ± 1` (255).

**Structural / value**:
- duplicate, drop, or reorder fields (ids out of order are legal — good for the
  decoder's skip/route paths);
- inject NaN/±inf/−0 bit patterns into fp32/fp64;
- inject **invalid UTF-8** bytes into a string payload (exercises §8).

## Hook (libFuzzer custom mutator)
Add to the pacemaker translation unit (`drivers/c/driver.c`, under
`#ifdef CRUCIBLE_LIBFUZZER`):

```c
size_t LLVMFuzzerCustomMutator(uint8_t *data, size_t size,
                               size_t max_size, unsigned int seed);
```

libFuzzer picks it up automatically when present — **no build change** beyond
having the function (`scripts/fuzz.sh` already links libFuzzer). Rules:

- Seed a tiny PRNG (e.g. xorshift) from `seed` — **do not** use `rand()`/time, so
  runs are reproducible.
- Respect `max_size` (never grow past it); return the new size.
- The mutator must **never crash** on malformed `data` (it mutates already-broken
  inputs). If the field walk fails, bail to the built-in mutator.
- **Mix in the default mutator** ~30–50% of the time:
  `return LLVMFuzzerMutate(data, size, max_size);` — keeps libFuzzer's generic
  power; the structure-aware ops add the grammar reach.

## Two corpus tracks (PLAN §5)
1. **Malformed track** — this mutator over `corpus/seeds` + `corpus/interesting`
   (raw/mutated bytes). Hunts crashes + accept/reject divergence. This is the
   first deliverable.
2. **Structured track** (follow-up) — valid-ish frames generated from the schema
   (e.g. encode random in-range messages via a driver's `encode`), fed as extra
   seeds. Hunts semantic value divergence. Can come after track 1.

## Done when
- libFuzzer coverage (`cov:` / `ft:`) rises faster and higher than the byte-mutator
  baseline (~`cov:550 ft:3616` in 26 s on the full-scale schema).
- The grown corpus visibly contains truncated-varint and invalid-UTF-8 inputs
  (spot-check), and `CLUSTER=1 CORPUS=corpus/interesting ./scripts/run.sh` surfaces
  clusters beyond today's top ~12 (new tail = new signal).
- Still deterministic per `seed`; the mutator never itself crashes/hangs.

## Note on the open findings
Building/running this does **not** depend on any corelib/generator fix. With the
known bugs still open, the differential loop stays red with the *known* clusters
(F-0001/F-0004/F-0005) — expected and tracked. To keep new signal from drowning,
optionally add the known clusters to `oracle/policy.yaml` as allow-entries first
(see TODO / STATUS).
