# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible found are
**not** here — they live in the owning repos (catalog: [`../results/FINDINGS.md`](../results/FINDINGS.md),
codegen defects: the `G-00NN` rows in [`FINDINGS.md`](../results/FINDINGS.md), spec clauses: adopted upstream in `documentation` (MESSAGE_SPEC/CORELIB_PLAN)).
Crucible's job is to catalog, attribute, and **verify** them.

**Blob-array integration 2026-07-21 (F-0013 blob-path follow-up):** a `blob_array` (id 201, the blob
analogue of `string_array`) was added to `schema/probe.sofab.yaml` and wired through all six sweep axes
+ `gen.py` + the truncation rich message. Drivers rebuilt schema-agnostically (no driver change). Two
results: (1) the **over-bound §7.1 blob path is GREEN** — over-index / over-maxlen blob elements → all
12 reject, so `_BlobSeq` enforces its `count`/`maxlen`; the long-open F-0013 blob-path re-check is
**answered**. (2) A **new finding, F-0026** — the §7.4 `blob_array` wrapper **re-open** keeps a stale
zeroed element on the C object API (corelib-c-cpp `sofab_object_init` never resets a sized blob's
companion length); `string_array` is uniform. Corelib-only, minimal isolate, carved out of the blocking
repeated-id sweep axis until fixed.

**Array-of-struct integration (WP-05) — DONE 2026-07-27** on the `poc/omit-all-default-sequences`
family (F-0030 / corelib-c-cpp#109 fixed there): `struct_array` (id 202, `struct{k: u32, v: string
maxlen 16}`, count 5) is in `schema/probe.sofab.yaml`; `gen.py` encodes it canonically (§2/§5.1 **as amended by
documentation#31**: interior all-default element = id **gap**, the last element always written —
as an empty frame when all-default — and an *empty* array omits the wrapper) with 8 `sw_*` value
vectors; the `struct_wrapper` node landed in all 9 walkers (5 runtime:
py/go/ts/java/cs; 4 generated: cpp-shared/rust-shared/zig/dart; C is descriptor-generic) +
`materialize.py`; `sweep_positions.py` carries the new positions (`seq_swrapper` wrapper, element-0
`seq_struct`, element k/v leaves) so the position-driven axes sweep them, and
`sweep_empty_frame.py` pins the element rules (interior gap / last element kept).
Array-of-union / array-of-array remain follow-ups (below).

**docs/improvements.md work packages — COMPLETE 2026-07-23 (all 11 landed or deferred-with-reason).**
The 2026-07-22 coverage-audit backlog is cleared: WP-01/02A/03/04/05/06/07/08/09/10/11 all merged (PRs
#88,#94,#90,#91,#93,#95,#96,#97,#98,#99,#92). Surfaced findings **F-0027..F-0032** (+ spec hole
documentation#24), 10 upstream issues. `docs/improvements.md` is retired; the **deferred residue** lives
here:
- [ ] **WP-02 Part B** — union *materialized* (element-access) oracle: the C anchor materializes a union
  out-of-the-box (form `{opt_id:value}` per member), but the 6 runtime + 6 generated walkers need the
  `union` descriptor node + a `materialize.py` union reference (~12 walkers across 10 langs). Part A
  (union cross-encode) is green and gated.
- [x] **WP-05 completion** — DONE 2026-07-27 (see the dated entry above).
- [ ] **WP-08(c)** — the explicit `[]` that overrides a **non-empty** declared array `default`: still
  the only §2 case with no vector, and it needs a schema field carrying `default:` (any array now has
  an empty value — the 2026-07-27 "fixed-count has none" reasoning died with documentation#31). Add a
  defaulted array to `schema/probe-dyn.sofab.yaml` (heap roster), vectors = {absent → declared default;
  explicit empty wrapper → `[]`; framed non-default}. `sofabgen` accepts `default:` (verified).
- [x] **The materialized oracle vs §5.1 wrapper length** — RESOLVED 2026-07-28 by
  [documentation#31](https://github.com/sofa-buffers/documentation/pull/31): `count` is a
  capacity, so *highest present id + 1* is the spec's own rule and the oracle was right.
  The contradiction was in §5.1's "N for every target", now gone.
- [x] **Dynamic-array last-element rule untestable** — RESOLVED 2026-07-28: #31 generalized
  the rule from *dynamic* to **every** wrapper array, so probe's `count: 5` wrappers test it
  (`corpus/conformance/e_wrapper_*`, the `cap_sa_*` cross-encode vectors).
- [x] **The family still ships trim-on-encode / fill-on-decode** (documentation#31) —
  **DONE 2026-08-02: it does not, and no upstream issue was needed.** Both halves of this item
  had already converged and the item was simply never re-checked:
  - *The generator rollback.* `_trim_tail` / `_pad_to` are gone from **every** backend.
    `corpus/conformance/b_array_*` are **green**, not the "expected red" this item predicted:
    `[1,2,3,0,0]` and `[1,2,3]` each round-trip to themselves, so they are the two distinct
    values #31 requires rather than collapsing onto one wire form.
  - *corelib-c-cpp for F-0036.* Already resolved in sofabgen 0.21.0 (generator#248) and
    re-verified 2026-07-29; re-verified again 2026-08-02 — `c` itself round-trips all three
    reproducers byte-identically, keeping the `0e 07` trailing empty frame and the `[{}]`
    single all-default element. Nothing to file.

  Both were checked on the **value**, not on agreement alone (c / go / rust-nostd read out
  individually — C object API, heap and fixed-capacity profiles), because a family-wide wrong
  answer is invisible to a differential oracle.
- [ ] **Lazy-depth divergence sweep** (POC CORELIB_PLAN §6): the bounded hold-back
  (`SOFAB_LAZY_SEQ_DEPTH` = 8 in corelib-c-cpp; rs-no-std likewise) only becomes observable with
  all-default sequence chains nested deeper than 8 — `probe` nests 3. A dedicated deep schema + suite
  would pin the legal non-canonical frames (policy carve-out
  `bounded-lazy-seq-depth-noncanonical-frames` is already in `oracle/policy.yaml`, dormant).
- [ ] **WP-10 Part B phase 2** — an opt-in `STRICT_UTF8=OFF` suite (env-gated build variant + per-profile-class
  `policy.yaml` allowances citing §8): deferred as a non-default-config follow-up; needs the gen#85
  Unicode-string config audit first. Phase-1 reachability audit is done (byte-container profiles OFF-capable
  → raw bytes; audit table was in improvements.md WP-10, mirrored in git history).


---

## Open — engine & oracles

- [ ] **Finer reject-class taxonomy** (`oracle/canonical.md` + drivers + comparator + `policy.yaml`).
      Investigated 2026-07-17: the corelibs collapse *all* malformed-wire reasons into one
      `InvalidMessage` (spec §6.3), so a *semantic* taxonomy (truncated / bad-varint / depth /
      …) is **not** available from return codes. The achievable, valuable version is a
      **two-tier grade**: normalise the class mapping across all 13 drivers, then distinguish
      `invalid_msg` (a clean wire-reject) from `usage`/`argument`/`other` (a generated-layer /
      API error). Make the **cross-tier** case hard — an impl whose generated layer errors
      where the family cleanly rejects is a codegen smell (the F-0003/F-0008 class) — and keep
      within-tier differences soft. Also de-noises the fuzzer clusters (a big share of residual
      "divergences" are reject_class-only, verdict-agreeing).
- [x] **Element-access / materialized-value probe** — **DONE 2026-07-21, all 12 drivers.**
      A second canonical form (`oracle/materialized.md`): `SOFAB_MATERIALIZE=1` makes a driver
      emit a full walk of the **decoded value** (every field + array element, floats as raw bits,
      `len:hex` strings/blobs) as its `A` payload, targeting the round-trip form's recorded blind
      spot (`canonical.md` §Tradeoff — a decode that differs only where the sparse wire elides,
      F-0010's class). Reuses the comparator unchanged (`accept_value` axis); `scripts/materialize.sh`
      runs the 12-driver differential over `corpus/structured` → **75×12, 0 divergences**, every
      driver matching the `engine/structured/materialize.py` reference byte-for-byte; the default
      round-trip path is unchanged. C is the schema-agnostic anchor (object-descriptor walk); the
      other 11 hand-walk with a schema-type table. **Measured design fact:** numeric arrays are
      already materialized to N in memory family-wide, so this form's live signal is the **wrapper
      arrays** + **element-level fidelity** + **regression-proofing**, not F-0010's exact shape
      (resolved). Surfaced nuance: the **Go** corelib leaves an absent numeric array `nil` (its
      driver pads to N for the dump — same logical value, benign).
    - [x] Wired into CI as a standing gate (`replay.yml`, 2026-07-21): the materialized differential
          (agreement, 75×12) + the C-anchor conformance check vs the reference (a family-wide-wrong
          dump is agreement-green but conformance-red).
    - [x] **Generated schema-type table** (2026-07-21, `engine/structured/schema.py` →
          `oracle/materialized-schema.json`): the typed field tree (kinds/ids/counts/nesting) is now
          derived from `schema/probe.sofab.yaml`, not hardcoded. The **reference** (`materialize.py`)
          is driven by it — the ground truth is schema-agnostic, so a schema type/shape change updates
          it automatically. `materialize.sh` regenerates + `cmp`-checks the committed artifact so it
          can't drift. **This also backstops the drivers:** the CI conformance check runs every driver
          against the schema-driven reference, so a hardcoded driver walker that fails to follow a
          schema change now **fails the gate loudly** instead of drifting silently.
    - [x] **Reflection-language walkers consume the descriptor** (2026-07-21): go/ts/java/cs/python
          now load `oracle/materialized-schema.json` at runtime and walk the decoded value generically
          (reflection by field name) — **schema-agnostic**, no hardcoded shape. `materialize.sh` exports
          `SOFAB_MATERIALIZE_SCHEMA`; 75×12 stays 0-divergence. So the schema-agnostic set is now C +
          go/ts/java/cs/python (7 of 12 targets).
    - [x] **rust / cpp / zig generate their walker source** (2026-07-21): no usable runtime reflection,
          so each has a build-time generator (`drivers/<lang>/materialize_gen.py`, run by `build.sh`)
          that unrolls the descriptor into straight-line walker source — regenerated every build. All 12
          drivers are now **schema-agnostic**: a schema change reflows to every walker with zero
          hand-editing. 75×12 stays 0-divergence; the generators run cleanly during the default `run.sh`
          builds too. **The materialized-value oracle is fully complete** — no open refinements.
- [ ] **Encoder-side fuzzing.** The pacemaker is **decode-only**; encoders are only exercised
      via cross-encode's deterministic values. Mutate the *value* (floats, boundary ints, array
      sizes, unicode) and feed all 12 *encoders* → compare bytes. Reaches encoder divergences
      (and encoder UB like the old F-0002) via coverage, not just replay.
- [ ] **Multi-impl coverage** (the biggest architectural gap). Only the C corelib actually
      *steers* the fuzzer, so it explores C-complex paths only — F-0012 (a TS bug) was found via
      the differential, not coverage. Instrumenting a second engine would steer toward paths
      complex in *other* languages. The C pacemaker is saturated (cov ~569 on `probe`), so this is
      where new depth comes from. *(update 2026-07-23: coverage **entry points** now exist for
      go/ts/java/cs — `drivers/go/fuzz_test.go`, `drivers/ts/fuzz.ts`, `drivers/java/FuzzProbe.java`,
      `drivers/cs/Fuzz.cs` — but none is compiled by its `build.sh` or wired into `fuzz.sh`/`nightly.yml`;
      rust has none, zig/dart are placeholders. Remaining work: wire one in as a second steering engine.)*
- [ ] **Differential-cluster A/B** of the grammar vs byte-level corpora — the mutator's real
      "done when". Ideally in the nightly. (Mutator itself is built; `engine/mutator/DESIGN.md`.)

## Open — schemas & corpus

- [x] **blob array** — **DONE 2026-07-21.** Added `blob_array` (id 201) to `probe` + all six sweep
      axes. The over-index / `maxlen` blob paths (§7.1) that F-0013 could not test for lack of a field
      are now **green** (all 12 reject); the §7.4 wrapper re-open surfaced **F-0026** (corelib-c-cpp,
      open). The C++ heap `_BlobSeq` guard held.
- [ ] **More corner-case schemas** beyond the single full-scale `probe`:
  - **recursive types** (`$ref`, trees) to exercise `MAX_DEPTH`, and a **map** (`array of
    struct{k,v}`) — the last format features `probe` doesn't cover.
  - *(update 2026-07-23: `MAX_DEPTH` is already exercised by `engine/structured/sweep_framing.py`
    — the past-`MAX_DEPTH` nesting vector that surfaced F-0029 — but via synthetic bytes, not a
    recursive `$ref` schema. The **map** (`array of struct{k,v}`) is modeled in `schema.py`
    (`struct_wrapper`) yet held out of `probe` pending F-0030 — that is the "WP-05 completion"
    residue item at the top of this file.)*
- [ ] **Corpus hygiene**: minimize `corpus/interesting/` (~44k files, never merged) with
      libFuzzer `-merge` — only ~320 are coverage-distinct, so every full differential over it
      pays for the redundancy.

## Open — waiting on upstream, then verify

- [x] **F-0039 / generator#254 — DONE (generator `main` @ 9c71fde, 2026-07-29).** The java and
      csharp backends no longer size a declared array from a header §7.3 says to skip: the
      generated `arrayBegin` now guards each allocation with `if (kind != ArrayKind.X) break;`.
      `wiretype_sweep` went **30 → 2** divergences.
- [x] **F-0042 — the last two `wiretype_sweep` cells — DONE (2026-08-01).** The corelib
      array-header hook widened to carry the fixlen element **subtype** (all seven issues closed:
      corelib-go#58, -java#53, -cs#45, -dart#23, -rs-no-std#60, -rs#40, -zig#27) and the backends
      consume it in generator#259. The carve-out is deleted; `wiretype_sweep` is **361 → 363
      vectors, green**, and the six reproducers are in `corpus/regression/` as `F0042_*`.

- [x] **File the three open findings upstream — DONE (2026-08-01).** All three went to
      `generator`; each has a G-number in `results/FINDINGS.md`. Now waiting on the fixes:
      - ~~**F-0038's dart residual** → [generator#265](https://github.com/sofa-buffers/generator/issues/265)
        (**G-0025**)~~ — ✅ **FIXED 2026-08-01, verified 2026-08-02.**
        [generator#269](https://github.com/sofa-buffers/generator/pull/269) emits the
        resolve-then-leave override unconditionally, so a string-free scope no longer inherits
        corelib-dart's validating default. **F-0038 is fully resolved** (all 13 agree; vectors
        promoted into `corpus/regression/`, 112 → 117).
      - **F-0033** → [generator#266](https://github.com/sofa-buffers/generator/issues/266)
        (**G-0026**): enforce the declared integer width as a validity bound (documentation#32,
        §1/§7.1 — over-width is INVALID, never masked, never kept). Today only `c` /
        `cpp-c-cpp` are conformant.
      - **F-0043** → [generator#267](https://github.com/sofa-buffers/generator/issues/267)
        (**G-0027**): decide a schema-bound violation **at the word** that carries the violating
        number, not after payload bytes arrive.

- [ ] **Triage the 2026-08-01 fuzz round's unattributed clusters** (snapshot + camps in
      [`../results/CLUSTERS.md`](../results/CLUSTERS.md)). Priority order:
      1. [x] **Cluster 3 — DONE 2026-08-01: minimized to F-0044** (128 B -> 6 B, three controls).
         A child of a *skipped unknown sequence* binds into the enclosing scope on the
         flat-visitor backends. Filed as generator#268 (**G-0028**).
      1b. [x] **Clusters 14 / 15 — DONE 2026-08-01.** 14 is the **product of F-0044 and F-0033**,
         not a finding of its own (proven with an in-range control and a no-wrapper control);
         it closes when either does. 15 minimized to **F-0045** (468 B -> 8 B): a §7.3-skipped
         array leaves `afill` armed and the next scalar is absorbed into an array. Filed as
         generator#270 (**G-0029**).
      2. [x] **Clusters 4, 6, 7, 8, 10, 17 — DONE 2026-08-01**, all minimized and attributed:
         **4 + 17** are F-0043 at an uncovered position (a `string_array` element, `maxlen: 64`)
         and demonstrate its off-by-one crisply — 0 payload bytes → 8 impls say `I`, 1 byte → 3.
         Worth appending to generator#267. **6** → **F-0046** (generator#271). **7** is a **legal**
         divergence: CORELIB_PLAN §6.4 grants a `MAY`, raised upstream as documentation#33 —
         re-triage once that rules. **8** is F-0044's second symptom (verdict flip; noted on
         generator#268). **10** → **F-0047** (generator#272).
      3. [x] **Cluster 5 (2026-08-01) = cluster 4 (2026-08-02), 8 inputs — DONE 2026-08-02:
         minimized to F-0048** (305 B → 11 B, 4 controls). **A finding, not the legal
         CORELIB_PLAN §6 bound it resembled** — and not a capacity issue at all: the no-std
         backend's wrapper-array **element** sink appends instead of replacing (generated
         `message.rs` 452/475, no `clear()`), so MESSAGE_SPEC §7.4 last-wins is violated and the
         accompanying guard `_e.len() != _s.len()` misfires into `buffer_full` on any duplicate
         element id at any size. rust-std gets the same position right, which is what pins it to
         codegen (**G-0032** → [generator#273](https://github.com/sofa-buffers/generator/issues/273)). That the rewrite of `istream.rs` left it unmoved is
         explained: the defect was never in the corelib.
         **This closes the 2026-08-01 round's triage — all 17 clusters attributed.**

- [ ] **New sweep axis: an unknown *sequence* id carrying children** (coverage gap exposed by
      F-0044). `sweep_framing.py` uses unknown ids (50/51) only with scalar / fixlen / array wire
      types, so no axis ever opened an unknown SEQ_BEG with a payload inside — which is why a
      6-byte defect had to be found by the fuzzer instead. Vectors: unknown seq × {empty, one
      scalar child, nested sequence child, child whose id collides with a real field of the
      enclosing scope}, at every sequence position.

- [ ] **New sweep axis: a repeated *element* id inside an array wrapper** (coverage gap exposed
      by F-0048). **F-0019** established the §7.4 duplicate-id axis, but its vectors repeat a
      *sequence* id (`nested`, `arrays`) and an array **wrapper** id (200) — never an **element**
      id *inside* a wrapper, which is the cell F-0048 lives in. Second time a §7.4 blind spot has
      cost a finding. Vectors: element id repeated × {same value, different value, empty-then-value,
      value-then-empty, enough repeats to exceed `maxlen` if concatenated} × {`string_array`,
      `blob_array`, `struct_array`}, plus the same at a *scalar* string field as the control that
      already passes. Both oracles — the value split is what the round-trip oracle sees only when
      the verdict does not flip first.

- [ ] **Re-enable `sweep_malform_truncate`'s broadened truncation when F-0043 closes.** The axis
      currently applies the full offset sweep only to the STRUCTURAL malformations; the
      schema-bound half is a two-line deletion in `engine/structured/sweep_malform_truncate.py`
      (43 → 96 vectors). The carve-out previously cited F-0032, which is resolved — it is F-0043
      that keeps it, and the boundary offset is precisely what it hides.

- [ ] **Re-enable the *scalar* `f32_snan` in `engine/structured/gen.py` when F-0049 closes.**
      Narrowed 2026-08-02 from "F-0031 / three impls" to **one cell: dart at the scalar
      position** (F-0049 / G-0033 → [generator#275](https://github.com/sofa-buffers/generator/issues/275) — the generated raw bits are library-private). go and
      typescript were **our own drivers** and are fixed; the corelibs were never at fault.
      The **array** position is now covered and green on all 13 (`arr_fp32_nan_bits`, added
      the same day — §6.5 requires bit-exactness at *every* fp32 position and only the scalar
      one had a vector). Re-enabling needs `scripts/materialize.sh` green, not just `run.sh`.

- [x] **fp32 sNaN at the array element position — DONE 2026-08-02.** §6.5 requires
      bit-exactness "at **every** `fp32` position: a **scalar** `fp32` (§4.6) **and** each
      element of an **`fp32` array** (§4.8)"; only the scalar had a vector, so a defect confined
      to the array path was invisible. `arr_fp32_nan_bits` (sNaN / qNaN-payload / −NaN /
      subnormal / 1.0 control, as raw bytes) is in `corpus/structured` and green on all 13.
      Required `arr_fp()` to accept pre-packed bytes, mirroring the scalar `fp32()` escape.

- [x] **F-0022 / generator#188** — **DONE (sofabgen 0.19.4, 2026-07-21).** The generated array-fill
      arm now carries the §7.3 guard (`if self.afill == 0 { return; }`) and `array_begin` arms `afill`
      only at a real array position; a bare scalar at an array id is skipped. All 5 isolates → 0
      divergences across 12; promoted into `corpus/regression/` (`F0022_*`, gate 59 → 64).
- [x] **F-0023 / generator#189** — **DONE (sofabgen 0.19.4, 2026-07-21).** The `string_array`
      wrapper-element loop now emits the same §7.3 guard the struct-field dispatch had (TS
      `message.ts:372`, Py `message.py:446`, C++ `_StrSeq`); a mis-typed element is skipped. All 5
      isolates → 0 divergences across 12; promoted into `corpus/regression/` (`F0023_*`, gate 64 → 69).
- [x] **F-0025 / generator#193** — **DONE (post-0.19.4 sofabgen CI build, 2026-07-22).** §7.3, a
      **scalar fp field** (`nested.f32`/`f64`) receiving an fp **fixlen array** stored the element
      instead of skipping (rust-std/rust-nostd/java/csharp/zig). The **fp analogue of F-0021** (generator#183
      covered integers only): the generated `arrayBegin` now arms `askip` for the fp array kinds too, and
      the `fp32()`/`fp64()` callbacks carry the `askip` guard. **Verified:** `sweep_run.py wiretype_sweep`
      → green (319 vectors, 0 div); both reproducers → all-12-skip. Promoted the wiretype (§7.3) axis
      **report-only → blocking** in `scripts/sweep.sh`; the 2 reproducers + 2 controls into
      `corpus/regression/` (`F0025_*`, gate 73 → 77). generator#193 closed.
- [x] **F-0024 / generator#190 (G-0016)** — **DONE (sofabgen 0.19.4, 2026-07-21).** The generated
      `try_decode` now captures `feed` without `?`, checks `v.inv`, and returns `InvalidMsg` before
      surfacing the Incomplete (`message.rs:235/242/246`) → INVALID dominates a truncated tail (§5.2).
      Verified: 4 isolates → 0 divergences; malform×truncation sweep green (18 malformed×{complete,trunc}
      → `R`, 0 conformance failures). **Sweep axis promoted report-only → blocking**; 4 vectors into the
      gate (`F0024_*`, 69 → 73).
- [x] **F-0004 / generator#85** — **DONE 2026-07-18 (crucible#55).** sofabgen 0.18.0 shipped the
      strict-UTF-8 codegen (generator#162) + per-corelib checks; Crucible built all drivers with
      the check ON (c/c-cpp opt in via `-DSOFAB_ENABLE_STRICT_UTF8`; zig via `build_options`),
      added 11 invalid-UTF-8 seeds + 3 valid controls (`engine/structured/utf8_seeds.py`), and
      confirmed **all 12 `R invalid_msg`** on malformed / **all 12 `A`** on valid. Promoted into
      the regression gate (29 → 43).
- [x] **F-0018** — **CLOSED by-design 2026-07-18 (not a bug).** Embedded U+0000 in a `string`:
      a NUL-terminated C-string profile projects `A\0B` → `A` on re-encode. The corelib receives
      the full value; the projection is inherent to the C-string convenience (`strlen` is correct),
      and the lossless path is the byte/length visitor API. Recorded as an allowed divergence in
      `oracle/policy.yaml` (axis `accept_value`, MESSAGE_SPEC §8); SOFABGEN G-0015 withdrawn. A
      one-line §8 spec note (embedded-U+0000 preservation is implementation-defined for a
      NUL-terminated profile) is the only optional follow-up.
- [x] **F-0013 blob path** — **DONE 2026-07-21.** Added the `blob_array` schema (above); the
      over-index + over-maxlen blob paths (§7.1 over-bound sweep) are **green** — all 12 reject, so
      the 0.17.6 fixed-capacity fix covered `_BlobSeq`, not just strings. (The same integration
      surfaced **F-0026**, a *different* blob path — the §7.4 wrapper re-open reset — now the open
      corelib-c-cpp item below.)
- [x] **F-0026 / [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106)** — **DONE (corelib-c-cpp `2416a2b`, 2026-07-22).** The C object API's §7.4
      `blob_array` wrapper **re-open** kept a stale zeroed element: `sofab_object_init` zeroed a sized
      blob's buffer but not its companion length. The fix resets that length on the replace-init.
      **Verified:** all 4 isolates → all-13-agree; the `elem == "blob"` skip in `sweep_repeated_id.py`
      was dropped and the repeated-id (§7.4) sweep is green with the blob wrapper (16 vectors); the 2
      reproducers + 2 controls promoted into `corpus/regression/` (`F0026_*`, gate 77 → 81). Issue closed.

## Open — CI / infra

- [ ] **`image.yml`**: confirm the GHCR toolchain image is seeded and the live runs are green.
      *(update 2026-07-23: confirmed `replay.yml`/`nightly.yml` **do** consume
      `ghcr.io/sofa-buffers/crucible-ci:latest`; the remaining task is confirming the image is
      seeded and a live run is green.)*
- [ ] **Build-reuse in `replay.yml`**: each of the seven gates rebuilds all 13 drivers, so CI
      pays the build 7×. Cache/reuse the built drivers across gates.
- [ ] **Devcontainer image**: verify it builds and every driver builds *inside* it (so far
      spot-verified in the bare workspace + hand-installed clang). *(update 2026-07-23:
      `.devcontainer/{Dockerfile,devcontainer.json,start.sh}` exist and `image.yml` builds them;
      still no CI evidence every driver builds inside the image — blocked on the `image.yml` item above.)*
- [ ] **OSS-Fuzz** onboarding for continuous fuzzing (eventual).

## Done — key harness milestones (finding history is in `../results/FINDINGS.md`)

- [x] **Structure-aware mutator** (`engine/mutator/`) wired via `LLVMFuzzerCustomMutator` +
      `scripts/fuzz.sh`; 336k-mutation ASan soak clean. **Comparator crash- + hang-isolation**
      (per-driver `--timeout`; `[TIMEOUT]` reported as a DoS finding).
- [x] **Cross-encode oracle** (`engine/structured/gen.py` + `scripts/cross-encode.sh`) — found
      F-0009 + F-0010. **Union suite** (`schema/probe-union.sofab.yaml` + `scripts/run-union.sh`).
- [x] **Regression gate** (`corpus/regression/`, 29 × 12, in `replay.yml`) — every resolved
      finding's reproducer, admitted only when green *for the reason the finding is about*;
      contaminated originals get clean isolates via `engine/structured/isolates.py`.
- [x] **All four spec proposals adopted** — §5.2 precedence (documentation#17), §3/§5.1
      fixed-count fill-to-N (#18), §7.1 declared-bounds-bind-every-target + §6.2.1 receiver
      limits + `LimitExceeded` (#20), §7.3/§7.4 mis-typed-header + repeated-id (#23). Provenance
      migrated into the finding `NOTES.md`; the `spec-proposals.md` draft file is retired.
- [x] **`bootstrap.sh` reworked** — always installs the latest sofabgen **release** binary
      (sha256-verified) and fetches corelibs to `origin/main`; no skip-if-present (a stale
      toolchain once mis-reported the versions compared). Escapes: `SOFABGEN_VERSION=` / `NO_FETCH=`.
- [x] **zig driver unbroken** (G-0010 / sofabgen 0.16.2). **java driver stale-jar fixed**
      (2026-07-17): `drivers/java/build.sh` rebuilds the corelib jar when the source is newer,
      not just when it's missing — a cached jar had once masked an F-0016 corelib fix.
- [x] **F-0001** target met (all 12 emit `I`); the **INVALID-vs-INCOMPLETE precedence family**
      resolved via the adopted clause + per-corelib fixes; **F-0013 / F-0014 / F-0015 / F-0016**
      all filed with precise codegen-vs-corelib attribution and verified fixed.
