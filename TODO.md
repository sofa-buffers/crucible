# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible
found are **not** here — they live in the owning repos (see `findings/` +
`results/FINDINGS.md` + `docs/SOFABGEN.md`; issues generator#78–#86,
corelib-c-cpp#69, corelib-cpp#22). Crucible's job is to catalog and **verify** them.

## Phase 3 — finish the engine & oracles
- [x] **Structure-aware mutator** (TLV/varint grammar) for the pacemaker —
      `engine/mutator/sofab_mutator.{h,c}`, wired via `LLVMFuzzerCustomMutator`
      (`drivers/c/driver.c`) + `scripts/fuzz.sh`. Verified safe/deterministic
      (336k-mutation ASan soak) + clean 231k-run campaign. See engine/mutator/DESIGN.md
      "As built". Follow-ups below.
  - [ ] **Comparator per-input timeout** (harness gap the mutator surfaced):
        `oracle/comparator.py` / `cluster.py` have no per-input wall-clock cap, so an
        adversarial corpus (maxed array counts, deep nesting) stalls the replay drivers.
        Add a timeout; a hanging driver is itself a finding (DoS). The libFuzzer
        pacemaker is unaffected (it has `-timeout`).
  - [ ] **Differential-cluster A/B** of the grammar vs byte-level corpora (the real
        "done when" — coverage saturates at cov:533 on `probe` so it can't discriminate;
        DESIGN.md). Do it once the comparator timeout lands, ideally in the nightly.
  - [ ] **Structured track** (DESIGN §"Two corpus tracks"): seed valid-ish frames from
        the schema to hunt semantic value divergence, not just malformed-input crashes.
- [ ] **Cross-encode oracle** (the 3rd oracle): encode a value in impl A, decode in
      impl B, compare. (Decode-agreement and round-trip idempotence already run.)
- [ ] **Union corpus / schema**: add a schema definition containing a `union` — the
      one wire feature the full-scale `probe` message lacks (§4.2).
- [ ] **Finer reject-class taxonomy** in `oracle/canonical.md` + the drivers +
      comparator. The coarse `invalid_msg` hid *why* impls rejected (the F-0004
      lesson). Distinguish e.g. truncated / bad-varint / bad-tag / depth / bad-utf8,
      then make `reject_class` a hard axis in `policy.yaml`.

## Verify fixes as they land (Crucible = acceptance test)
- [ ] For each merged fix (issues above): re-run the reproducer / differential loop,
      flip the finding's status in `results/FINDINGS.md`, and promote the reproducer
      into the committed regression corpus.
- [ ] **§8 / #85:** once corelibs expose `SOFAB_STRICT_UTF8`, build all drivers with
      it **on** + add invalid-UTF-8 seeds → confirm **F-0004 green** family-wide.
- [ ] **§7 / #86:** once feed+finish lands, add truncated/incomplete seeds → confirm
      **F-0001 green** family-wide.

## Phase 4 — continuous
- [ ] **CI**: `replay` workflow (fast, blocking, every push — regression corpus +
      known crashes) and `nightly` (long, non-blocking, continuous fuzz that grows
      the corpus). See PLAN §10/§12.
- [ ] **Corpus hygiene**: minimize with libFuzzer `-merge`; commit a minimized
      regression corpus; keep `corpus/interesting`/`crashes` gitignored.
- [ ] **Structural crash minimization** (e.g. F-0003 via cargo-fuzz `-minimize` once a
      Rust fuzz target exists; the current greedy minimizer got it to 145 B).
- [ ] **OSS-Fuzz** onboarding for continuous fuzzing (eventual).

## Housekeeping
- [ ] Verify the **devcontainer image** builds and every driver builds inside it
      (so far only spot-verified in the bare workspace + hand-installed clang).
- [ ] Pacemaker is **decode-only**; consider also exercising encode (round-trip) under
      libFuzzer so encoder UB like F-0002 is reachable via coverage, not just the
      replay path.
- [ ] Add **more corner-case schemas** beyond the single full-scale `probe` (the
      generator's `tests/matrix/corpus/defs` are ready-made candidates).
- [ ] Once generator#84 (G-0006) lands, **remove the `bytes`-import workaround** in
      `drivers/go/build.sh`.
