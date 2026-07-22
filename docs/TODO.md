# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible found are
**not** here — they live in the owning repos (catalog: [`../results/FINDINGS.md`](../results/FINDINGS.md),
codegen defects: [`SOFABGEN.md`](../results/SOFABGEN.md), spec proposals: [`spec-proposals.md`](spec-proposals.md)).
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

**As of 2026-07-22:** 26 findings catalogued, **25 resolved, 1 by-design, 0 open**. **F-0022**
(§7.3 array-field←scalar, generator#188), **F-0023** (§7.3 wrapper-element, generator#189), and
**F-0024** (§5.2 Rust `try_decode` INCOMPLETE-over-INVALID, generator#190 / G-0016) were all
**resolved in sofabgen 0.19.4** (2026-07-21) — re-verified, isolates promoted into the regression gate,
and the malform×truncation sweep axis promoted from report-only to blocking. **F-0025** (§7.3 fp
scalar←array, **generator#193**) is **resolved 2026-07-22** on the latest green sofabgen CI build:
verified all-agree, the wiretype (§7.3) sweep promoted **report-only → blocking**, isolates into the
gate (73 → 77). **F-0026** (corelib-c-cpp#106 — §7.4 `blob_array` wrapper re-open stale element) is
**resolved 2026-07-22** (corelib-c-cpp `2416a2b`): verified all-13-agree, the last sweep carve-out
(`elem=="blob"` in `sweep_repeated_id.py`) dropped, isolates into the gate (77 → 81). **No open finding
remains.** F-0018 (embedded U+0000 in a
`string`) is **by-design**: a NUL-terminated C-string profile projects `A\0B` → `A` on re-encode;
valid on the wire, preserved by the other 10 profiles, sanctioned in `oracle/policy.yaml` (§8).
All three Crucible-authored MESSAGE_SPEC clauses are adopted (documentation#17/#18/#20); §7.3/§7.4
adopted in documentation#23. Six green suites (seeds / cross-encode / union / limit /
**regression** (the last at **81 inputs**) / **materialized** (element-access, 75×12)) run in CI,
plus the **structural sweep gate** (`scripts/sweep.sh`; **all six axes now blocking-green, no carve-out**).
`./scripts/bootstrap.sh` keeps sofabgen at the latest release and the corelibs at `origin/main`.

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
- [ ] **Multi-impl coverage** (the biggest architectural gap). Only the C corelib is
      coverage-instrumented, so the fuzzer steers toward C-complex paths only — F-0012 (a TS
      bug) was found via the differential, not coverage. Instrumenting a second engine (rust via
      cargo-fuzz, or go) would steer toward paths complex in *other* languages. The C pacemaker
      is saturated (cov ~569 on `probe`), so this is where new depth comes from.
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
- [ ] **Corpus hygiene**: minimize `corpus/interesting/` (~44k files, never merged) with
      libFuzzer `-merge` — only ~320 are coverage-distinct, so every full differential over it
      pays for the redundancy.

## Open — waiting on upstream, then verify

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

- [ ] **`image.yml`**: confirm the GHCR toolchain image is seeded and the live runs are green
      (authored + run once; verify it's actually driving `replay`/`nightly`).
- [ ] **Build-reuse in `replay.yml`**: each of the seven gates rebuilds all 13 drivers, so CI
      pays the build 7×. Cache/reuse the built drivers across gates.
- [ ] **Devcontainer image**: verify it builds and every driver builds *inside* it (so far
      spot-verified in the bare workspace + hand-installed clang).
- [ ] **OSS-Fuzz** onboarding for continuous fuzzing (eventual).

## Done — key harness milestones (finding history is in `../results/FINDINGS.md` + `../results/SOFABGEN.md`)

- [x] **Structure-aware mutator** (`engine/mutator/`) wired via `LLVMFuzzerCustomMutator` +
      `scripts/fuzz.sh`; 336k-mutation ASan soak clean. **Comparator crash- + hang-isolation**
      (per-driver `--timeout`; `[TIMEOUT]` reported as a DoS finding).
- [x] **Cross-encode oracle** (`engine/structured/gen.py` + `scripts/cross-encode.sh`) — found
      F-0009 + F-0010. **Union suite** (`schema/probe-union.sofab.yaml` + `scripts/run-union.sh`).
- [x] **Regression gate** (`corpus/regression/`, 29 × 12, in `replay.yml`) — every resolved
      finding's reproducer, admitted only when green *for the reason the finding is about*;
      contaminated originals get clean isolates via `engine/structured/isolates.py`.
- [x] **All three spec proposals adopted** — §5.2 precedence (documentation#17), §3/§5.1
      fixed-count fill-to-N (#18), §7.1 declared-bounds-bind-every-target + §6.2.1 receiver
      limits + `LimitExceeded` (#20). Drafts in `spec-proposals.md`.
- [x] **`bootstrap.sh` reworked** — always installs the latest sofabgen **release** binary
      (sha256-verified) and fetches corelibs to `origin/main`; no skip-if-present (a stale
      toolchain once mis-reported the versions compared). Escapes: `SOFABGEN_VERSION=` / `NO_FETCH=`.
- [x] **zig driver unbroken** (G-0010 / sofabgen 0.16.2). **java driver stale-jar fixed**
      (2026-07-17): `drivers/java/build.sh` rebuilds the corelib jar when the source is newer,
      not just when it's missing — a cached jar had once masked an F-0016 corelib fix.
- [x] **F-0001** target met (all 12 emit `I`); the **INVALID-vs-INCOMPLETE precedence family**
      resolved via the adopted clause + per-corelib fixes; **F-0013 / F-0014 / F-0015 / F-0016**
      all filed with precise codegen-vs-corelib attribution and verified fixed.
