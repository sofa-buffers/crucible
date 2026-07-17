# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible found are
**not** here — they live in the owning repos (catalog: [`../results/FINDINGS.md`](../results/FINDINGS.md),
codegen defects: [`SOFABGEN.md`](SOFABGEN.md), spec proposals: [`spec-proposals.md`](spec-proposals.md)).
Crucible's job is to catalog, attribute, and **verify** them.

**As of 2026-07-17:** 17 findings catalogued, **15 resolved**; the net-open findings are
**F-0004** (§8 UTF-8 opt-in, generator#85) and **F-0017** (generated TypeScript decode ignores
the header wire type, generator#160 / G-0014). All three Crucible-authored MESSAGE_SPEC clauses
are adopted (documentation#17/#18/#20). Five green suites (seeds / cross-encode / union /
limit / **regression**, the last at 29 inputs) run in CI. `./scripts/bootstrap.sh` keeps
sofabgen at the latest release and the corelibs at `origin/main`.

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

- [ ] **More corner-case schemas** beyond the single full-scale `probe`:
  - a **blob array** — the C++ heap `_BlobSeq` has the same unguarded shape as the (now-fixed)
    string-array path, but `probe` has no blob array, so the over-index / `maxlen` blob paths
    are untested (flagged in F-0013);
  - **recursive types** (`$ref`, trees) to exercise `MAX_DEPTH`, and a **map** (`array of
    struct{k,v}`) — the last format features `probe` doesn't cover.
- [ ] **Corpus hygiene**: minimize `corpus/interesting/` (~44k files, never merged) with
      libFuzzer `-merge` — only ~320 are coverage-distinct, so every full differential over it
      pays for the redundancy.

## Open — waiting on upstream, then verify

- [ ] **F-0004 / generator#85** — the only net-open finding. Once the corelibs expose the §6.4
      opt-in strict-UTF-8 toggle (the config audit at gen#85 shows *none* do today), build all
      drivers with it **on**, add invalid-UTF-8 seeds, and confirm F-0004 goes green
      family-wide. Then promote the reproducer into the regression gate.
- [ ] **F-0013 blob path** — once a blob-array schema exists (above), re-check the over-index
      blob path on the fixed 0.17.6 codegen (the string path is fixed + gated; blob was
      untested for lack of a field).

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
