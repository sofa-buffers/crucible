# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible found are
**not** here — they live in the owning repos (catalog: [`../results/FINDINGS.md`](../results/FINDINGS.md),
codegen defects: [`SOFABGEN.md`](SOFABGEN.md), spec proposals: [`spec-proposals.md`](spec-proposals.md)).
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

**As of 2026-07-21:** 26 findings catalogued, **23 resolved, 1 by-design, 2 open (1 generator, 1 corelib)**. **F-0022**
(§7.3 array-field←scalar, generator#188), **F-0023** (§7.3 wrapper-element, generator#189), and
**F-0024** (§5.2 Rust `try_decode` INCOMPLETE-over-INVALID, generator#190 / G-0016) were all
**resolved in sofabgen 0.19.4** (2026-07-21) — re-verified, isolates promoted into the regression gate,
and the malform×truncation sweep axis promoted from report-only to blocking. The one open finding is
**F-0025** (§7.3 fp scalar←array, **generator#193**) — the fp analogue of F-0021 that generator#183
covered for integers only, which keeps the wiretype sweep report-only. When it lands: re-pull corelibs,
verify its sweep axis goes green, then promote it into the blocking sweep set + the regression gate.
F-0018 (embedded U+0000 in a
`string`) is **by-design**: a NUL-terminated C-string profile projects `A\0B` → `A` on re-encode;
valid on the wire, preserved by the other 10 profiles, sanctioned in `oracle/policy.yaml` (§8).
All three Crucible-authored MESSAGE_SPEC clauses are adopted (documentation#17/#18/#20); §7.3/§7.4
adopted in documentation#23. Five green suites (seeds / cross-encode / union / limit /
**regression**, the last at **73 inputs**) run in CI, plus the **structural sweep gate** (six axes,
`scripts/sweep.sh`; five blocking-green, one report-only for the residual F-0025 above).
`./scripts/bootstrap.sh` keeps sofabgen at the latest release and the corelibs at `origin/main`.

---

## Open — engine & oracles

- [ ] **Finer reject-class taxonomy** (`oracle/canonical.md` + drivers + comparator + `policy.yaml`).
      Investigated 2026-07-17: the corelibs collapse *all* malformed-wire reasons into one
      `InvalidMessage` (spec §6.3), so a *semantic* taxonomy (truncated / bad-varint / depth /
      …) is **not** available from return codes. The achievable, valuable version is a
      **two-tier grade**: normalise the class mapping across all 12 drivers, then distinguish
      `invalid_msg` (a clean wire-reject) from `usage`/`argument`/`other` (a generated-layer /
      API error). Make the **cross-tier** case hard — an impl whose generated layer errors
      where the family cleanly rejects is a codegen smell (the F-0003/F-0008 class) — and keep
      within-tier differences soft. Also de-noises the fuzzer clusters (a big share of residual
      "divergences" are reject_class-only, verdict-agreeing).
- [ ] **Element-access / materialized-value probe.** The round-trip oracle is blind to one
      class of bug: two decoders holding *different* in-memory values that re-encode to the
      *same* canonical wire look identical. F-0010's managed camp was exactly this — it keeps
      `M` elements instead of filling to `N`, but the wire is canonical either way, so the
      round-trip can't see it. A probe that dumps the fully-materialised value (all `N`
      elements explicit; length + element access) would catch it. Needs generic value traversal
      per driver — cheapest where the corelib already has a visitor/descriptor.
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
- [ ] **F-0025 / generator#193** — §7.3, a **scalar fp field** (`nested.f32`/`f64`) receiving an fp
      **fixlen array** stores the element instead of skipping — rust-std/rust-nostd/java/csharp/zig.
      The **fp analogue of F-0021**, which generator#183 covered for integers only: (1) `arrayBegin`
      arms `askip` only for `Unsigned`|`Signed`, never `Fixlen`; (2) the `fp32()`/`fp64()` callbacks
      lack the `askip` guard `unsigned()`/`signed()` carry. Generator-only, same fix shape as #183/#188.
      Written up (`findings/F-0025-scalar-fp-field-receives-fp-array/`) + filed. When it lands: re-pull
      corelibs, `python3 engine/structured/sweep_run.py wiretype_sweep` → expect green, promote the axis
      from report-only to blocking in `scripts/sweep.sh` + its isolates into `corpus/regression/`.
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
- [ ] **F-0026 / [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) (open)** — the C object API's §7.4 `blob_array` wrapper
      **re-open** keeps a stale zeroed element: `sofab_object_init` (`object.c:242-254`) zeros a
      sized blob's buffer but not its companion length at `offset - nested_idx` (the one function of
      four that omits the sized-blob branch). Corelib-only, `c` driver alone; write-up +
      2 reproducers in `findings/F-0026-c-blob-wrapper-reopen-stale-element/`. When fixed:
      re-pull corelibs, drop the `elem == "blob"` skip in `sweep_repeated_id.py`, verify the axis
      goes green, promote `blob_reopen_empty.bin` into `corpus/regression/`.

## Open — CI / infra

- [ ] **`image.yml`**: confirm the GHCR toolchain image is seeded and the live runs are green
      (authored + run once; verify it's actually driving `replay`/`nightly`).
- [ ] **Build-reuse in `replay.yml`**: each of the five gates rebuilds all 12 drivers, so CI
      pays the build 5×. Cache/reuse the built drivers across gates.
- [ ] **Devcontainer image**: verify it builds and every driver builds *inside* it (so far
      spot-verified in the bare workspace + hand-installed clang).
- [ ] **OSS-Fuzz** onboarding for continuous fuzzing (eventual).

## Done — key harness milestones (finding history is in `../results/FINDINGS.md` + `SOFABGEN.md`)

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
