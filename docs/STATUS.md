# Crucible — status & running notes

Durable snapshot of where the project stands (mirrors the working agent's memory,
so a fresh session or another contributor is oriented immediately). Authoritative
design is [`PLAN.md`](PLAN.md); as-built detail + deviations are in
[`ARCHITECTURE.md`](ARCHITECTURE.md); this file is the *current-state* summary.

## What Crucible is
A differential fuzzer for the SofaBuffers wire format: it feeds identical bytes to
every corelib and fails when they **disagree** (oracle = divergence, not crash).
Sibling of `arena` — copies arena's structure (vendor/, per-language driver
contract, one schema, one runner) but builds the corelibs **instrumented**
(sanitizers + coverage) rather than optimized.

## How it runs
- `./scripts/run.sh` — build all drivers, differential-compare over `corpus/seeds`
  (the green regression gate). `CORPUS=<dir> ./scripts/run.sh` to use another corpus.
- `./scripts/fuzz.sh` — the **C pacemaker** (libFuzzer, clang): grows
  `corpus/interesting/`. Then `CORPUS=corpus/interesting ./scripts/run.sh` runs the
  differential over what it found.
- `CLUSTER=1 ./scripts/run.sh` — reduce divergences to root-cause clusters
  (`oracle/cluster.py`); inventory in `results/CLUSTERS.md`.
- `./scripts/cross-encode.sh` — the 3rd oracle: generate valid, value-rich `probe`
  messages (`corpus/structured/`) and run the round-trip + decode-agreement oracle.
- `./scripts/run-union.sh` — the **union suite**: points the oracles at
  `schema/probe-union.sofab.yaml` (a `probe` carrying a 4-variant union), the one
  wire feature the main `probe` lacks. 11 seeds × 12 drivers, 0 divergences.
- `CORPUS=corpus/regression ./scripts/run.sh` — the **resolved-findings gate**: the
  reproducer of every fixed finding (59 inputs × 12 drivers, 0 divergences). A
  divergence here = a resolved bug came back. See `corpus/regression/README.md` for
  what it admits, and the exclusions (a reproducer that also trips an open axis stays
  in `findings/`).

## Current state
- **Phases 1–3 largely done:** 12 drivers / 10 corelibs green across all five suites on
  **sofabgen 0.19.4** (c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython, py-pure,
  java, typescript, csharp, zig). `./scripts/bootstrap.sh` keeps sofabgen at the **latest
  release** (sha256-verified) and the corelibs at `origin/main`.
- **Structural sweep framework** (`engine/structured/sweep_*.py`, PLAN §6): a sweep enumerates
  one normative rule across **every** schema position and checks two oracles (agreement +
  conformance). **Six axes** wired via `sweep_run.py` / `scripts/sweep.sh` — repeated-id (§7.4),
  over-bound (§7.1), reserved-subtype (§4.6), truncation (§7), malform×truncation (§5.2)
  **blocking + green** (five); only wiretype (§7.3) is **report-only** (it carries the one open
  finding below). This is what found F-0020–F-0024 — "isolate-green ≠ axis-green".
- **25 findings catalogued** (`results/FINDINGS.md`); **23 resolved, 1 by-design, 1 open upstream.**
  **F-0022** (§7.3 array-field←scalar, generator#188), **F-0023** (§7.3 wrapper-element,
  generator#189), and **F-0024** (§5.2 Rust `try_decode` INCOMPLETE-over-INVALID, generator#190 /
  G-0016) were all **resolved in sofabgen 0.19.4** (2026-07-21) — re-verified, isolates promoted into
  the regression gate (`F0022_*` / `F0023_*` / `F0024_*`, gate 59 → 73), and the malform×truncation
  sweep axis promoted from report-only to blocking. **The one open finding, F-0025** (§7.3 fp
  scalar←array, generator#193), keeps the wiretype (§7.3) sweep report-only — a **scalar fp field
  receiving an fp array** (`nested.f32`/`fp64` ← ArrayFixlen), the fp analogue of F-0021 that
  generator#183 covered for integers only (the `askip` guard sits in `unsigned()`/`signed()` but not
  `fp32()`/`fp64()`, and `array_begin` arms `askip` only for `Unsigned`|`Signed` kinds). Generator-only,
  filed 2026-07-21. When it lands: re-pull corelibs, verify the report-only sweep axis goes green,
  promote it into the blocking set + the regression gate. **F-0018** (embedded U+0000
  in a `string`) is classified **by-design** — a
  NUL-terminated C-string profile projects `A\0B` → `A` on re-encode; valid on the wire,
  preserved by the other 10 profiles, sanctioned as an allowed divergence in
  `oracle/policy.yaml` (§8). **F-0004** (strict UTF-8) and **F-0017** (TS header wire type)
  were both resolved by **sofabgen 0.18.0** — see the 2026-07-18 entries below. Three
  Crucible-authored MESSAGE_SPEC clauses adopted (documentation#17/#18/#20).
- **Phase 3 (built):** canonical form v2 = **round-trip re-encoding** with a
  **three-valued verdict** (`A` complete / `I` incomplete / `R` reject, per
  MESSAGE_SPEC §7 — comparator + `canonical.md` updated, drivers emit `I` as each
  corelib gains INCOMPLETE; crucible#8); drivers are schema-agnostic, folds in the
  round-trip oracle; schema scaled to the **full-scale** message; **C pacemaker
  active** (~41k exec/s); comparator is **crash-isolating**; **auto-clustering**.
- **Union feature covered** (2026-07-16): `schema/probe-union.sofab.yaml` +
  `corpus/union/` (11 seeds) + `scripts/run-union.sh`. All 12 backends generate the
  union and agree on every variant, the one-of encoding, and the two malformed-union
  edge cases (two members set → all re-encode both in id order; unknown member id →
  all skip → empty union). Green, no finding — the last untested wire feature.
- Remaining Phase 3 / Phase 4: see [`TODO.md`](TODO.md).

## Key design points
- One coverage **pacemaker** (C, libFuzzer+ASan/UBSan) drives exploration; every
  interesting input is replayed through all N drivers and compared. C is the motor,
  **not** a privileged oracle.
- Drivers run **persistent** (length-prefixed stdin), emit the canonical form; they
  are generated from `schema/` via `sofabgen`. Not the generator's process-per-input
  `encode`/`decode` CLI.
- Corelib **variant pairs** share one driver source: rust-std/rust-nostd
  (`drivers/rust`), cpp/cpp-c-cpp (`drivers/cpp`), py-cython/py-pure (`drivers/python`,
  `SOFAB_PUREPYTHON`).

## Findings & tracking
Reproducers in `findings/<id>/`; catalog in `results/FINDINGS.md`; codegen-bug log
in `docs/SOFABGEN.md`. Fixes live in the **owning repos** (done in fresh contexts);
Crucible is the catalog + verifier.

**Re-verification 2026-07-08** — after bumping **sofabgen → 0.15.1** and all 10
corelibs to latest `main`, drivers rebuilt clean and the seed corpus is green (0
divergences). Replaying the finding reproducers: **F-0002 and F-0005 are fixed**
(upstream PRs merged); **F-0003's crash is fixed but morphed** into a verdict
divergence, now tracked as generator#100 (see below); **F-0001 and F-0004 still
diverge** — expected,
they wait on the still-open epics generator#86 / #85 (the "2 issues still open").

**Toolchain + corelib bump 2026-07-15 — re-verified** — bumped
**sofabgen → 0.16.1** (`tools/sofabgen` rebuilt from generator `v0.16.1`, commit
`3bd1b37`; the vendored binary had been a stale 0.15.2) and re-cloned all 10
corelibs to their `origin/main` tips (real clones now replace the previously
broken vendor symlinks): c-cpp `4274ed6`, cpp `021902c`, cs `532c2f7`, go
`7e32c8c`, java `0a9ea4c`, py `e14e4ba`, rs `b46c1cd`, rs-no-std `84bc895`, ts
`09c1298`, zig `f5f40e6`. All **12 drivers rebuilt clean** on 0.16.1 (one snag: the
Python venv is cached across runs, so it had to be wiped — `rm -rf
drivers/python/build/venv` — to pick up the new corelib-py; the other drivers
regenerate every run). Full re-run results:

- **Seed corpus green** (12 drivers, 0 divergences); **limit mode green** all three
  dimensions.
- ✅ **generator#100 fixed** (commit `ca0fda7`; the F-0003 residual): a clean
  non-truncated over-count (8>5) scalar array now → **all 12 reject** (`R`);
  rust-std/nostd reject with the family (were the lone accepters). F-0003 **fully
  resolved**.
- ✅ **G-0009 / generator#112 fixed** (commit `7899c4b`): the C++ unbounded array is
  now `std::vector`; cpp matches the family on the arr limit vectors and on the old
  repro `03 03 07 08 09` → `[7,8,9]`. **cpp rejoins the `arr` dimension** —
  `scripts/run-limits.sh` updated (the `NO_CPP` hold-out removed) and re-run green.
- ✅ F-0001 still green (all `I`); F-0002 still clean (no left-shift UBSan).
- ⏳ F-0004 still 4-way (raw/empty/U+FFFD/reject) — expected, the
  `SOFAB_STRICT_UTF8` epic generator#85 is still open.
- 🆕 **F-0006 (new):** the corelib-py `main`@`e14e4ba` (un-eager array allocation)
  made corelib-py return `I` instead of `R` on a **truncated fixlen fp32/fp64 with a
  wrong declared length** (e.g. `56 0a 59`) — the sole `I`-vs-`R` outlier vs 10
  impls. Root-caused (fp width check deferred until payload read) and filed
  **[corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)**.
  (Also in the bump: generator#113/#103/#104 — no new divergence from those on the
  current corpus.)

**Second re-pull + re-run 2026-07-15 (newer `main` tips)** — pulled all corelibs
again; the tips advanced to: c-cpp `d01f109`, cpp `a3d0717`, cs `0c619e8`, go
`f28d2ee`, java `4f73558`, py `0e15785`, rs `03b44f6`, rs-no-std `67e1632`, ts
`8a6210c`, **zig `0f861e4`**. Re-ran the box (wiping the Python venv + Java jar to
pick up the moved corelibs):

- ✅ **F-0006 FIXED** — corelib-py `main` now validates fp32/fp64 fixed width at the
  FIXLEN header (decoder.py L338-341), before the payload read, so a truncated
  wrong-width fp is `R` (INVALID), not `I`. Re-verified: `56 0a 59` / `56 02 38` →
  **all drivers `R`**. **[corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)
  closed.** F-0007's py slice collapsed; the precedence family now narrows to the
  **C corelib only** (c + cpp-c-cpp still `I` on `56 0a 09` at small declared lengths).
- ✅ Seed differential green (11 drivers); limit mode green all dimensions (cpp in
  arr); F-0001 all `I`; generator#100 all `R`; F-0002 clean; F-0004 unchanged 4-way
  (#85).
- ⚠️ **zig held out — build broken.** corelib-zig `0f861e4` adopted the finish-less
  `decode → Error!Status` API (INCOMPLETE is a `Status`, not `error.Incomplete`).
  sofabgen 0.16.1's zig backend still generates `try sofab.decode(data,&v)` (discards
  the `Status`) and `drivers/zig/driver.zig` still switches on `error.Incomplete` →
  compile error. This is the **zig analogue of G-0008** (status surfacing): the
  corelib moved correctly to §7, the generator + Crucible driver must catch up.
  Tracked as **G-0010** ([generator#120](https://github.com/sofa-buffers/generator/issues/120)) + a driver TODO. Until fixed, `run.sh`
  aborts at the zig build; the box was run over the other 11 drivers.

**Third re-run 2026-07-15 — sofabgen 0.16.2, zig restored, full 12/12 green.**
Bumped **sofabgen 0.16.1 → 0.16.2** (`tools/sofabgen` rebuilt from generator
`v0.16.2` = commit `976e06e`; 0.16.2 is a focused release — **only** the zig fix
`26f1f4c` "zig: bind feed(chunk)→Status in generated decode()", closing G-0010 /
[generator#120](https://github.com/sofa-buffers/generator/issues/120), plus the
version bump). Corelib tips unchanged from the second re-run. The generated
`message.zig` `decode` now surfaces the terminal `Status`, mapping `.incomplete` →
`error.IncompleteMessage`; the Crucible **`drivers/zig/driver.zig`** was updated to
match (`error.Incomplete` → `error.IncompleteMessage`, two sites — the driver half
of G-0010). Full re-run:

- ✅ **zig builds and rejoins the box.** Seed differential **12/12 green**; limit
  mode green all dimensions (9 heap drivers incl zig, cpp in arr).
- ✅ **F-0001 all 12 `I`** (zig now emits `I` on `80`, confirming the finish-less
  §7 model end-to-end); **F-0006 all 12 `R`**; **generator#100 all 12 `R`**; G-0009
  holds. **F-0004** unchanged 4-way (#85). **F-0007** — `56 0a 09` (fp64) / `56 02 10`
  (fp32) → only **c + cpp-c-cpp** emit `I` (zig correctly `R`); the C corelib is the
  sole precedence outlier. **Root-caused and filed
  [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82)**: the
  C istream validates a fixlen fp's declared length against the destination buffer
  (`length > target_len`), not the exact width (4/8), so a wrong-width *truncated* fp
  is `I` not `R` — the direct analogue of the closed corelib-py#38.
- **G-0010 resolved** (generator side in 0.16.2 + the Crucible driver.zig fix).

**Fourth re-run 2026-07-15 — sofabgen 0.17.0, corelibs@main, full 12/12 green.**
Bumped **sofabgen 0.16.2 → 0.17.0** (`eef4d6a`; a cosmetic release — only #123
"render metadata as clean doc comments", no wire behavior) and re-pulled all
corelibs to their `main` tips. Wiped the Python venv + Java jar (corelib-java moved)
so the caches picked up the new corelibs. Results:

- **Seed 12/12 green**; **limit mode green** all dimensions.
- ✅ **F-0007 RESOLVED** — corelib-c-cpp `635966d` "reject wrong-width fixlen
  fp32/fp64 as INVALID (#82)(#83)"; `56 0a 09` / `56 02 10` → **all 12 `R`**;
  [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82)
  **closed**. The whole INVALID-vs-INCOMPLETE precedence family is now convergent
  (F-0006 + F-0007 both fixed).
- ✅ F-0001 all `I`; F-0002 clean; F-0006 all `R`; generator#100 all `R`; G-0009
  holds. ⏳ F-0004 unchanged 4-way (#85).
- 🆕 **F-0008 (new): a generated fixed-capacity C++ DoS hang** — a 4-byte input
  `c6 0c c6 07` (a nested `SEQUENCE_START` inside the `string_array` field) makes the
  generated `_FixedStrSeq` fill **loop forever**; `c`/`cpp`/`go`/`rust` all return `I`
  instantly. Found by the **structure-aware mutator** and localized by the new
  comparator **per-driver timeout** (the whole pipeline working end to end).
  **Correction:** first mis-filed against corelib-c-cpp (the differential symptom was
  `cpp-c-cpp`-only); the corelib maintainer showed `sofab_istream_feed` terminates
  ([corelib-c-cpp#84](https://github.com/sofa-buffers/corelib-c-cpp/issues/84) closed,
  [crucible#16](https://github.com/sofa-buffers/crucible/issues/16)). Tracing the
  generated code found the real bug: `_FixedStrSeq`/`_FixedBlobSeq` do
  `while (out->size() <= id) out->emplace_back()`, but the fixed-capacity
  `InlineVector::emplace_back` no-ops when full, so `id ≥ N` spins. Re-targeted to
  **codegen: [generator#126](https://github.com/sofa-buffers/generator/issues/126)**
  (G-0011).

Net open items: **F-0004** (spec §8 / gen#85) and **F-0008** (generator#126 / G-0011).

**Fifth re-run 2026-07-16 — sofabgen 0.17.1: F-0008 + F-0009 verified FIXED.**
Bumped `tools/sofabgen` to **0.17.1** (`fa909c7`), which lands both codegen fixes the
mutator + cross-encode oracle found this session: **generator#126** (F-0008, commit
`483c281` — bounded the fixed-capacity string/blob-seq fill loop) and **generator#128**
(F-0009, commit `25d5853` — sized blob descriptor). Rebuilt + re-ran the full box:
- ✅ **F-0008 fixed** — `c6 0c c6 07` → `I` (terminates, no hang) on `cpp-c-cpp`.
- ✅ **F-0009 fixed** — short blobs round-trip in `c`, matching the family; the
  sub-`maxlen` vectors rejoined the green cross-encode gate (`corpus/structured/`, now
  **52 inputs, 0 divergences**).
- ✅ Seed + limit-mode gates green. **crucible#16** (the F-0008 dispute) closed.

Net open now: **F-0004** only (spec §8 / gen#85). All Crucible-found codegen bugs
(G-0001…G-0012) are resolved.

**Sixth re-run 2026-07-16 — corelib bump (`main` tips), full box green, no regression.**
Pulled all 10 corelibs from origin/main; four advanced — **corelib-c-cpp** `635966d→98ab841`
(docs), **corelib-cpp** `9fd4f78→24ee297` (docs), **corelib-rs** `03b44f6→7b453d8` (docs),
**corelib-rs-no-std** `3e4a69f→29ddf42` (one real change: `perf(size)` varint push
outlining, #44). sofabgen unchanged (0.17.1). Full box:
- ✅ **Differential** (seeds) 6×12, **cross-encode** 69×12, **union** 11×12, **limit
  mode** (arr/str/blb) 9-driver roster — **all 0 divergences**.
- ✅ Resolved reproducers (F-0002/05/06/07/09) still all-agree.
- The two reproducer-level splits that appear — F-0003 `array_overflow` (rust `I` vs
  family `R`) and F-0008 `hang_min`/`hang_orig` (py `R usage` vs family `I`) — are the
  **INVALID-vs-INCOMPLETE precedence** spec-hole (documentation#15) on the *original*
  crash/hang reproducers, **not regressions**: proven by reverting corelib-rs/-rs-no-std
  to pre-pull commits (identical `I`), and corelib-py was untouched by the pull. Recorded
  as residual notes in the F-0003/F-0008 NOTES.
- F-0001/F-0004/F-0010 reproducers show their documented spec-hole behavior unchanged.

**Seventh re-run 2026-07-16 — sofabgen 0.17.2: F-0010 fixed for 11/12, NEW go regression (F-0011).**
Built sofabgen from generator `v0.17.2` (`d8d35c2`) and pulled corelibs — only
**corelib-c-cpp** advanced (`98ab841→390f237`, carries corelib-c-cpp#87, the C-path
half of the F-0010 fix). 0.17.2 lands **generator#136** (my F-0010 issue, PR #137):
- ✅ **F-0010 resolved for the trim/pad question, all 12 backends** — R1/R2 reproducers
  (`u32_count3`, `i16_count1`) now round-trip to the canonical **count 3 / count 1**; the
  systems camp trims the trailing default run (C via corelib-c-cpp#87).
- ✅ **Union** (11×12) and **limit mode** (dynamic arrays, 9-driver roster) **green**.
- ❌ **Seed gate (5/6) + entire cross-encode corpus RED — go only.** The same 0.17.2 go
  changeset (`684656d`) over-corrected: an **all-default `count:N` array field is emitted
  explicitly** (`<hdr> 00`) instead of omitted (§2). New finding **F-0011**, filed
  **[generator#139](https://github.com/sofa-buffers/generator/issues/139)**. go-only,
  `count:N`-array-specific (union + dynamic-array limit mode stay green; go's under-count
  *trim* is itself correct). **Staying on 0.17.2** (F-0010 value) with the gates red-on-go
  until generator#139 lands.

**Eighth re-run 2026-07-16 — sofabgen 0.17.3: F-0011 fixed, FULL BOX GREEN.**
Built sofabgen from generator `v0.17.3` (`0bc18e1`); corelibs unchanged (pure go codegen
fix). 0.17.3 lands **generator#139** (commit `0713b94`, "fix(go): omit an all-default
count:N array instead of emitting it"):
- ✅ **F-0011 resolved** — `empty_arrays` → all 12 omit the all-default arrays
  (`A 5607a606560707c60c07`); `undercount_siblings` → all 12 agree.
- ✅ **Full box green:** differential (seeds) 6×12, cross-encode 69×12, union 11×12, limit
  mode (arr/str/blb) 9-driver roster — **all 0 divergences**.
- ✅ **F-0010 stays canonical** (count 3 / count 1 on all 12); compliance spot-checks
  (Clause A fp-precedence, §7 over-count) all `R`.
The 0.17.2→0.17.3 round-trip (F-0010 fix → go regression → go fix) closed within the day.

**Fuzzer round 2026-07-16 (sofabgen 0.17.3) — 1 new finding, no crash.** Ran the C
pacemaker (`scripts/fuzz.sh`, `FUZZ_TIME=180`: 2.49M execs @ 13.7k/s, **no crashes**,
coverage saturated, +306 corpus units → 43.3k `corpus/interesting`). Clustered a 1-in-10
sample (4326 inputs → 70 clusters). Dominant class (~66%): **F-0012** — corelib-ts's
unknown-field **skip path** reports `INCOMPLETE` where the family reports `INVALID` for a
malformed fixlen word + truncation (§5.2 precedence), filed **[corelib-ts#49](https://github.com/sofa-buffers/corelib-ts/issues/49)**.
The rest is the precedence family (other impls' skip paths lenient/eager — the C family
shows the same gap in cluster 5, follow-up) + **F-0004** (UTF-8) + soft reject_class /
incomplete_value. Green gates unaffected (all malformed-input edge cases). See CLUSTERS.md.

**Ninth change 2026-07-16 — regression corpus committed + CI wired; F-0013 found while
building it.** Built `corpus/regression/` (the standing TODO): the reproducers of all
nine resolved findings, **18 inputs × 12 drivers, 0 divergences**, wired into
`replay.yml` on every push/PR — so a bump that reintroduces a fixed bug fails CI rather
than waiting to be spotted in a manual re-run (F-0011 was caught only because someone was
looking). Also wired the **union suite** into `replay.yml`.

- **The gate admits a reproducer only when it is green *for the reason the finding is
  about*.** F-0003's `array_overflow.bin` and F-0008's `hang_min.bin` are fixed but
  **contaminated** — each tests its own axis *and* truncation, so both still split the
  family on the open precedence hole (documentation#15). They stay in `findings/`; the
  gate gets **clean isolates** instead (`engine/structured/isolates.py`, built on
  `gen.py`'s primitives).
- 🆕 **F-0013 (new): an over-index `string_array` element is kept (heap) vs dropped
  (fixed-capacity)** — found by writing the *clean* F-0008 isolate (over-index **without**
  truncation), which the contaminated original could not express. `c6 0c c2 07 0a 78 07`
  (7 B, element index 120 ≥ the schema's `count: 5`): all 12 **accept**, but c /
  cpp-c-cpp / rust-nostd drop the element while the 9 heap profiles keep it — a pure
  value split, invisible to any accept/reject oracle. Root cause **codegen G-0013**: the
  heap backends emit an unbounded container + `while (len <= id) push(default)` fill, so
  the schema `count` is enforced nowhere. Same fill is a **memory-amplification DoS**:
  9 B at index 2,000,000 → cpp **226 MB** / go **122 MB** vs ~8 MB fixed. **The half of
  F-0008 that generator#126 left unfixed.** Filed [generator#142](https://github.com/sofa-buffers/generator/issues/142) (2026-07-17; spec target = reject per §7).
- Harness fix: `comparator.py`'s `read_corpus` now skips `*.md` + dotfiles, so a corpus
  dir can carry a README (previously *every* file was an input, incl. a `.gitkeep`).

**Tenth change 2026-07-17 — corelib bump: F-0012 (ts-skip) FIXED.** Pulled corelibs;
`corelib-ts` advanced to `0279378` ("fix(decode): validate fixlen word in the cursor skip
path (§5.2 precedence)") — the corelib-ts#49 fix for the fuzzer's F-0012. **Re-verified:**
`aa7e79` / `5df35d07` → TS now `R invalid_msg` (was `I`), aligned with the family; the
valid-skip controls stay `A`/`I`. (cs/go moved on docs/deps/test only.) PR #39 (the F-0012
write-up) had already merged; the overindex finding it collided with was renumbered
**F-0012 → F-0013**.

**Eleventh change 2026-07-17 — full box green; 1 h fuzzer round; F-0001 closed, F-0014 opened.**
Box (all 5 suites incl. the new regression gate) **green** on current tips. Ran the pacemaker
for **1 hour** (143 M execs @ 39.9k/s): **no new crash**, coverage saturated (cov 566, all
REDUCE), corpus → 44.1k. Results:
- ✅ **corelib-ts#49's effect measured:** the sample divergence rate fell **86% → 32%** and the
  dominant cluster (TS skip-path precedence, 66%) is **gone**.
- ✅ **F-0001 marked resolved** — its target ("every impl emits `I`") has been met since
  2026-07-13; re-verified. Its NOTES had been badly stale ("still diverging, 7 vs 5",
  2026-07-08). The residual java `incomplete_value` on `I` is the **soft** axis, not F-0001.
- ✅ **F-0004 config audit contributed upstream** ([gen#85 comment](https://github.com/sofa-buffers/generator/issues/85#issuecomment-5000859662)):
  **no corelib exposes the §6.4 opt-in toggle** — go+py validate unconditionally, the other 8
  never do, so 8 of 10 **cannot reach the conformance-ON configuration** §8 requires. That is
  the blocking half of that epic.
- 🆕 **F-0014 (new):** with #49's cluster gone, the residual precedence clusters (149 py / 97
  c-family / 94 ts) turned out to be **one class on the array path** — the `ARRAY_FIXLEN`
  element word isn't (fully) validated at the header. Three minimal isolates, each pinning one
  impl; filed **[corelib-c-cpp#89](https://github.com/sofa-buffers/corelib-c-cpp/issues/89)**,
  **[corelib-py#41](https://github.com/sofa-buffers/corelib-py/issues/41)**,
  **[corelib-ts#51](https://github.com/sofa-buffers/corelib-ts/issues/51)**. The array analogue
  of the fixed F-0006/F-0007/F-0012.
- **F-0013 did not surface** in fuzzing — as expected: it needs a *well-formed* over-index,
  which byte mutation practically never produces (it was found via a structured isolate).

**Twelfth change 2026-07-17 — F-0015 + spec Proposal 3 ADOPTED (ahead of the codegen bump).**
Preparing the regression for an announced sofabgen update reworking array/string/blob
`count`/`maxlen`, the audit asked which of those axes we actually cover — and found the
**`maxlen` axis untested and already divergent**:
- 🆕 **F-0015:** a `string`/`blob` over its schema `maxlen` splits **9-vs-2-vs-1** (9 heap
  profiles accept and keep the over-long value; c/cpp-c-cpp → `invalid_msg`; rust-nostd →
  `buffer_full`). Within `maxlen`: all 12 agree. The three "enforcers" enforce only because
  their fixed buffer cannot hold more — an artifact of the memory model, the F-0010/F-0013
  shape.
- **The spec never defined it.** §7's enforced-bounds enumeration listed only `M > N` and
  element id `≥ N`; MESSAGE_SPEC mentioned `maxlen` 5× but never normatively (§2 filed it
  next to docs/tooling hints; §5.1 used it as a pre-sizing hint "on heap-less profiles");
  CORELIB_PLAN mentioned it **0×**. Two adjacent holes rode along: the unbounded-field
  obligation, and the receiver-side `max_dyn_*` limits — which the generator ships
  (generator#102) and Crucible tests via the `L` verdict, while §6.2 listed only
  format-wide ceilings (`policy.yaml` has flagged that since Phase 1).
- ✅ **Proposal 3 filed *and* adopted the same day** — documentation#19 → **PR
  [documentation#20](https://github.com/sofa-buffers/documentation/pull/20) merged**
  (`49cdee9`; spec now at `85bb0be`). MESSAGE_SPEC §2/§7/**§7.1**/**§7.2** + CORELIB_PLAN
  §6.2/**§6.2.1**/§6.3 (+ the new `LimitExceeded` code). §7.1 is the crux: a declared
  `count`/`maxlen` binds **every target regardless of allocation strategy** — *"MUST NOT
  accept an over-bound value merely because its storage happens to be able to hold it"*.
  Writing the PR also surfaced that §6.3 had **no code** for a limit rejection, making the
  draft's "MUST NOT report as `InvalidMessage`" unimplementable; the PR adds
  `LimitExceeded` and raises (rather than decides) the API-shape question — fourth outcome
  vs error channel. **All three Crucible spec proposals are now adopted** (#15→#17,
  #16→#18, #19→#20).
- **Timing was the point:** the clause landed **before** the codegen bump, so the update
  implements a *defined* rule — the F-0010 order (hole → clause → adoption → codegen) that
  made that one land uniformly. F-0015's four vectors are the **pre-bump baseline**, so the
  update's effect is measurable rather than guessed.

**Thirteenth change 2026-07-17 — sofabgen 0.17.4 + 0.17.5 + corelib fixes: F-0014 & F-0015
RESOLVED, F-0013 half. Regression gate 18 → 25.** Box green throughout.
- ✅ **F-0015 fully resolved** — **0.17.5** (`b0b2832`, "reject over-maxlen strings/blobs as
  INVALID on decode (Option B)"). Measured against this morning's baseline: **9 accept / 2
  `invalid_msg` / 1 `buffer_full` → all 12 `R invalid_msg`**, on all three over-`maxlen`
  vectors; the within-`maxlen` control still accepts on all 12. Both halves landed — the 9
  heap backends enforce `maxlen`, *and* rust-nostd's `buffer_full` became `invalid_msg` (the
  class correction §7.1 implies). **The whole arc closed in one day:** hole found while
  preparing the regression → clause filed (documentation#19) → spec PR authored & merged
  (#20) → codegen (0.17.5) → verified against the baseline. Without the baseline, "fixed"
  and "never tested" would have been indistinguishable.
- ✅ **F-0014 resolved** — all three corelib issues fixed & closed the same day:
  corelib-c-cpp#89 (`ab062e3`), corelib-py#41 (`d4fe94f`), corelib-ts#51 (`7a9033f` —
  "validate fixlen element word *before truncation guard*", the exact ordering diagnosis).
  All three isolates → all 12 `R invalid_msg`.
- ⚠️ **F-0013 half fixed** — **0.17.4** (generator#142, now closed) killed the **DoS** (cpp
  **226 MB → 10 MB**) and made the 9 heap backends reject. But `c`/`cpp-c-cpp`/`rust-nostd`
  still **accept + silently drop**, so the split **flipped** from a value split to a verdict
  split (9 `R` vs 3 `A`). Traced: `b6da1ed`'s "never taken" holds for `_MsgSeq`, but
  string/blob over-index goes through `_FixedStrSeq`, still carrying #126's silent `return;`
  (c-cpp has **0** `invalidate()` calls vs cpp's **13**). Violates §7 + §7.1. Filed
  **[generator#149](https://github.com/sofa-buffers/generator/issues/149)**.
- **Regression gate 18 → 25 inputs**, still 0 divergences: promoted F-0014's 3 isolates +
  F-0015's 3 over-bound vectors + its within-bound **control** (which guards the
  counter-direction — that we don't start over-rejecting).
- ✅ No regression from `4e78b0a` (java array omit-default hoisted to a static) — F-0011's
  vectors stay green.

**Fourteenth change 2026-07-17 — sofabgen 0.17.6: F-0013 FULLY RESOLVED; regression gate 25→26.**
Installed via the reworked `bootstrap.sh` (latest release, sha256-verified). 0.17.6 lands
generator#149 → #151 (fixed-capacity C family) + #150 (rust no_std): the 3 profiles that were
still silently dropping an over-index element now **reject** it. Box green throughout.
- ✅ **F-0013 done** — `overindex_clean` + `overindex_amplify` → **all 12 `R invalid_msg`**;
  in-range elements still accepted by all 12; DoS gone. Closed over four releases in the
  right order: DoS + heap half first (0.17.4, security-critical), fixed-capacity verdict half
  last (0.17.6). Promoted `overindex_clean.bin` into the gate (now **26 inputs**).

Net open now: **F-0004** (§8 UTF-8, gen#85) — and the *unfiled* **F-0016** (overlong >64-bit
varint accepted by 8 impls, found in the 2nd 1 h fuzz round; corelib-side, not yet written up).
F-0001 + F-0010 + F-0011 + F-0012 + F-0013 + F-0014 + F-0015 resolved.

**Fifteenth change 2026-07-17 — F-0016 written up + RESOLVED; F-0017 opened; regression gate 26 → 29.**
- ✅ **F-0016 filed and resolved.** The overlong-varint divergence was written up and filed
  per-impl against the seven lenient corelibs (the varint reader caps the byte count at 10 but
  never checks the 10th byte's overflow bits): corelib-cpp#39, corelib-go#48, corelib-rs-no-std#45,
  corelib-py#43, corelib-ts#53, corelib-java#41, corelib-cs#37. All seven fixed & closed;
  **re-measured all 12 `R invalid_msg`** on both over-64-bit vectors (baseline 8A/4R), control
  still `A`. Promoted the two vectors + the control into the **regression gate (26 → 29 inputs)**.
  Also hardened `drivers/java/build.sh` to rebuild the corelib jar when the source is newer — a
  cached jar had masked this fix.
- 🆕 **F-0017 (new, open):** the generated **TypeScript** decode dispatches on the field id alone
  and calls the schema-typed reader **without checking the header wire type**, so a type-mismatched
  header desyncs it from the wire framing (isolate `05 00 01`: 11 → `R`, ts → `I`). Codegen defect
  **G-0014**, filed **generator#160** — distinct from (and upstream of) the resolved corelib-ts
  precedence family. Found by the 3 h fuzz on 0.17.7.

Net open now: **F-0004** (§8 UTF-8, gen#85) and **F-0017** (generator#160 / G-0014).

**Sixteenth change 2026-07-18 — sofabgen 0.18.0: F-0004 + F-0017 RESOLVED (crucible#55); F-0018
opened; regression gate 29 → 44; full box green.** Polled for the announced 0.18.0 release, then
integrated it via `SOFABGEN_VERSION=v0.18.0 ./scripts/bootstrap.sh` (sha256-verified) with the
corelibs at their `origin/main` tips. 0.18.0 lands two fixes Crucible had open:
- ✅ **F-0004 RESOLVED (issue #55) — strict UTF-8 ON family-wide.** 0.18.0 ships the codegen call
  sites for rust/java/cs/zig ([generator#162](https://github.com/sofa-buffers/generator/pull/162));
  c/cpp/go/py/ts enforce it corelib-internally; the Unicode-typed corelibs are always strict. Only
  the C corelib defaults OFF (footprint), so **`drivers/c/build.sh` + `drivers/cpp/build.sh` (c-cpp)
  opt in** with `-DSOFAB_ENABLE_STRICT_UTF8` and compile `corelib-c-cpp/src/utf8.c`; the **zig
  driver** now supplies the `build_options.strict_utf8=true` module its bare `zig build-exe` needs.
  New generator `engine/structured/utf8_seeds.py` embeds each malformed form (11 vectors from
  corelib-c-cpp's `invalid_utf8` group) as the `nested.str` of a valid `probe`, plus 3 valid
  controls. **Verified:** the old 4-way raw/U+FFFD/empty/reject split is gone — every malformed
  vector → **all 12 `R invalid_msg`**, every valid control → **all 12 `A`** and round-trips. 14
  seeds promoted into the gate.
- ✅ **F-0017 RESOLVED** — [generator#160](https://github.com/sofa-buffers/generator/issues/160)
  fixed in 0.18.0 ([PR #161](https://github.com/sofa-buffers/generator/pull/161), "frame each
  decoded field by header wire type"). Isolate `05 00 01` → **all 12 `R invalid_msg`** (ts was
  `I`); promoted `F0017_ts_wiretype_iso.bin` into the gate.
- 🆕 **F-0018 (new):** adding F-0004's embedded-U+0000 control surfaced that on `c` + `cpp-c-cpp`
  a `string` with an embedded NUL re-encodes `A\0B` → `A`, while the other 10 preserve it; all 12
  *accept*, so it is a pure **value** split. Initially filed as a codegen defect (G-0015);
  **reclassified same day as by-design — see the Seventeenth change below.**
- ✅ **Full box green on 0.18.0:** seeds 6×12, **regression 44×12**, cross-encode 69×12, union
  11×12, limit mode (arr/str/blb) 9-driver roster — **all 0 divergences** (3 expected soft
  `incomplete_value` warnings on the F-0001/F-0006 truncation reproducers).

Net open now: **F-0018** only.

**Seventeenth change 2026-07-18 — F-0018 reclassified: by-design, not a bug (allowed divergence).**
On review, F-0018 is **not** a codegen defect. The C object API deliberately models a `string` as a
NUL-terminated `char[]`, and a C string's length *is* `strlen` — `sofab_ostream_write_string`'s
`strlen` (`ostream.h:302`) is correct, not defective. The corelib *receives the value in full*
(istream copies all bytes + terminator, `istream.c:779`; the strict-UTF-8 check validates all of
them, `istream.c:886`); the projection to first-NUL happens only when the value is read back as a
C string. So embedded U+0000 is a **type-representation projection**, not a decode loss:
- **not INVALID** (rejecting a fully-received value would be wrong), **not a family-wide ban**
  (U+0000 is legal on the wire and the other 10 profiles preserve it), **not a codegen change**
  (that would de-idiomatize C strings for a pathological input);
- the **lossless path** is the byte/length (visitor) API, which hands the raw `{ptr,len}`.

Recorded as an **allowed divergence** in `oracle/policy.yaml` (axis `accept_value`, spec basis
MESSAGE_SPEC §8 — preservation of embedded U+0000 is implementation-defined for a NUL-terminated
profile). SOFABGEN **G-0015 withdrawn**. F-0018 stays in `findings/` as a documented by-design
record. **No open bug remains** — all 18 findings are resolved or by-design.

**Eighteenth change 2026-07-19 — sofabgen 0.18.0 → 0.19.2; corelibs re-pulled; full box green, no regression.**
Refreshed all corelibs to `origin/main` first, then polled for the announced 0.19.2 release and
integrated it via `SOFABGEN_VERSION=v0.19.2 ./scripts/bootstrap.sh` (sha256-verified). No Crucible
finding targeted this bump — installed to keep the toolchain current (the user's deliberate pin, was
0.18.0).
- **Corelib tips that advanced:** `corelib-c-cpp` 57dba4a → 56c88fa (`feat(cpp): expose delivered
  wire type on IStreamImpl`, §7.3), `corelib-cpp` bc0cb05 → 2be6fe2 (`build: --parallel job count`,
  build-only), `corelib-ts` 7bbc499 → e307a64 (`chore(devcontainer): drop CI=true`, env-only). The
  other seven corelibs + `documentation` were already at their `origin/main` tips, unchanged. Only
  the c-cpp change is wire-adjacent; py/java did not move, so their venv/jar caches needed no wipe.
- ✅ **Full box green on 0.19.2:** seeds 6×12, **regression 44×12**, cross-encode 69×12, union
  11×12, limit mode (arr/str/blb) 9-driver heap roster — **all 0 divergences** (3 expected soft
  `incomplete_value` warnings on the regression corpus). The c-cpp "delivered wire type" change did
  **not** perturb **F-0017** — its reproducer (`F0017_ts_wiretype_iso.bin`) is in the gate and stayed
  at 0 divergence.

Net open: still **F-0018** (by-design) only — no change.

**Nineteenth change 2026-07-19/20 — structural sweep framework + 8 h fuzz round; F-0019–F-0021 resolved (0.19.3), F-0022–F-0024 opened; regression gate 44 → 59.**
- **Structural sweep framework** landed (`engine/structured/sweep_*.py`, `scripts/sweep.sh`, CI gate
  in `replay.yml`): a shared schema-position model + a two-oracle runner (**agreement** — all 12 same
  line; **conformance** — accept-vs-reject matches spec, catching a family-wide-wrong answer that is
  agreement-green but conformance-red). The runner is **axis-aware** (hard verdict/accept_value splits
  vs soft incomplete_value/reject_class, per `policy.yaml`). **Six axes:** repeated-id (§7.4),
  over-bound (§7.1), reserved-subtype (§4.6), truncation (§7) — **blocking + green**; wiretype (§7.3)
  and malform×truncation (§5.2) — **report-only** (they carry the three open findings). Central lesson:
  **isolate-green ≠ axis-green** — a fixed vector can still leave the rule broken at a position it never
  tested.
- **F-0019 / F-0020 / F-0021 resolved in sofabgen 0.19.3** (2026-07-19/20): §7.4 duplicate-id
  (documentation#23 + generator#175), §7.3 mis-typed field skip (the struct-field and array-into-scalar
  positions). Verified all-12-agree, promoted into the gate.
- **F-0022 / F-0023 opened** by the wiretype sweep — the §7.3 guard still missing at the **array-fill
  arm** (F-0022, generator#188) and the **wrapper-element loop** (F-0023, generator#189). Both
  generator-only.
- **8 h C-pacemaker round** (2026-07-20, sofabgen 0.19.3): **2.24 G executions**, **0 sanitizer
  crashes, 0 timeouts, no memory leak**, seed suite green throughout. Three `slow-unit-*` artifacts
  investigated → **benign** (≤ 0.03 s isolated; transient timer flags under 3-worker load, not
  algorithmic DoS). The full differential over the divergence-enriched `corpus/interesting` surfaced one
  dominant class (63 % of sampled verdict-splits) → **F-0024** (generator#190 / G-0016): the generated
  Rust `try_decode` discards a detected INVALID (`v.inv`) via `?` when the input is also truncated,
  returning `I` where §5.2 requires `R`. Delta-debugged 146 B → 11 B; the malform×truncation sweep axis
  generalizes it (6 malformation kinds reproduce, reserved-subtype path stays green — separating the two
  malformation paths). Filed with a four-vector control set (crucible#66/#68).
- **Regression gate 44 → 59** (the §7.3 + §4.6 resolved isolates promoted); the three open findings kept
  **out** of the gate until their codegen fixes land.

Net open: **F-0022 / F-0023 / F-0024** — all **generator-only codegen**, filed generator#188/#189/#190;
each waits on a sofabgen release, then re-pull + verify its report-only sweep axis goes green + promote.
Plus **F-0018** (by-design).

**Twentieth change 2026-07-21 — sofabgen 0.19.3 → 0.19.4; corelibs re-pulled; F-0022 + F-0023 resolved; regression gate 59 → 69; full box green.**
Polled for the announced 0.19.4 release; it published as a **non-latest** asset (download live while
`/releases/latest` still pointed at 0.19.3), so integrated it via `SOFABGEN_VERSION=v0.19.4
./scripts/bootstrap.sh` (sha256-verified) rather than the plain `latest` path. Corelibs reset to
`origin/main` first: **corelib-go** 057354a → 8dd7ddb and **corelib-rs-no-std** a55d92c → 5ff6921
advanced; the other eight were already at their tips.
- ✅ **F-0022 resolved** ([generator#188](https://github.com/sofa-buffers/generator/issues/188)): the
  generated array-fill arm now carries the §7.3 guard (`if self.afill == 0 { return; }`, rust
  `message.rs:281`) and `array_begin` arms `afill` only at a real array position — a bare scalar at an
  array id falls through and is skipped, symmetric to the F-0021 `askip` fix; no corelib change. All 5
  isolates → 0 divergences across 12; **the array-field←scalar half of the wiretype sweep is now clean.**
- ✅ **F-0023 resolved** ([generator#189](https://github.com/sofa-buffers/generator/issues/189)): the
  `string_array` wrapper-element loop now emits the same §7.3 guard the struct-field dispatch had —
  TS `message.ts:372`, Py `message.py:446`, C++ `_StrSeq` — so a mis-typed element (blob / fp32 / signed
  / sequence) is skipped instead of read as the declared type. All 5 isolates → 0 divergences across 12.
- **Regression gate 59 → 69:** the F-0022 (3 mismatch + 2 control) and F-0023 (4 mismatch + 1 control)
  isolates promoted (`F0022_*` / `F0023_*`); `CORPUS=corpus/regression ./scripts/run.sh` → 69×12,
  0 divergences (3 expected soft `incomplete_value` warnings unchanged).
- ⚠️ **The wiretype (§7.3) sweep is NOT yet green — one residual remains.** After #188/#189 it drops from
  the fuller F-0022/F-0023 set to **exactly 2 vectors**: a **scalar fp field receiving an fp array**
  (`arrays.nested.fp32`/`fp64` declared `FIX_fp32`/`fp64`, fed an `ArrayFloat` of `[1.5]`). This is the
  **fp analogue of F-0021** (scalar←array), which generator#183 covered for **integers only** — the
  `askip` guard sits in `unsigned()`/`signed()` (rust `message.rs:275`/`:289`) but **not** in `fp32()`/
  `fp64()` (`:304`/`:311`), and `array_begin` arms `askip` only for `Unsigned`|`Signed` array kinds
  (`:368`), never `Float`. 7 backends skip; rust-std/rust-nostd/java/csharp/zig store the element into
  the scalar. **New finding, to be catalogued as F-0025** (generator-only, same fix shape as #183/#188).
  Kept **out** of the blocking set + the gate until it lands. `sweep.sh` comment updated to point at it
  instead of the now-resolved F-0022/F-0023.
- ✅ **Full box green on 0.19.4:** seeds 6×12, **regression 69×12**, cross-encode 69×12, union 11×12,
  limit mode (arr/str/blb) 9-driver heap roster, structural sweep blocking axes — **all 0 divergences**.

Net open: **F-0024** (generator-only, generator#190 / G-0016) + the newly-isolated **F-0025** (fp §7.3
scalar←array, pending write-up + generator issue). Plus **F-0018** (by-design). F-0022/F-0023 closed.

**Twenty-first change 2026-07-21 — F-0024 verified resolved on 0.19.4; malform×truncation sweep promoted to blocking; regression gate 69 → 73.**
Re-checking the open findings on the same 0.19.4 build (drivers already rebuilt) showed **F-0024 is
also fixed** — generator#190 landed in 0.19.4 alongside #188/#189.
- ✅ **F-0024 resolved** ([generator#190](https://github.com/sofa-buffers/generator/issues/190) /
  G-0016): the generated `try_decode` now captures `feed`'s result without `?`, reads `v.inv`, and
  returns `InvalidMsg` **before** surfacing the Incomplete — `fed = is.feed(data, &mut v); … if invalid
  { return Err(InvalidMsg); } fed?;` (rust `message.rs:235/242/246`). INVALID dominates a truncated
  tail per §5.2. 0.19.3 had `is.feed(data, &mut v)?;` (`:234`), whose `?` discarded `v.inv` under
  truncation — a pure ordering bug, now correctly ordered.
- **Verified three ways:** (1) code inspection (the exact generator#190 fix); (2) the 4 isolates → 0
  divergences across all 12; (3) the **malform×truncation sweep (§5.2)** — 20 vectors, 0 divergences,
  **0 conformance failures**, all 18 malformed×{complete,trunc} → `R` (the `_trunc` vectors that flipped
  rust to `I` on 0.19.3 are now `R`).
- **malform×truncation sweep promoted report-only → blocking** in `scripts/sweep.sh` — five blocking
  axes now, only wiretype (§7.3) remains report-only (residual F-0025). The 4 F-0024 vectors promoted
  into the gate (`F0024_*`, 69 → 73); `CORPUS=corpus/regression ./scripts/run.sh` → 73×12, 0 divergences
  (4 expected soft `incomplete_value` warnings).

Net open: only the newly-isolated **F-0025** (fp §7.3 scalar←array, pending write-up + generator issue).
Plus **F-0018** (by-design). **All 24 catalogued findings are now resolved or by-design.**

**Twenty-second change 2026-07-21 — F-0025 written up + filed (generator#193); catalog 24 → 25.**
Deep-verified the wiretype sweep's last residual before filing (the F-0022/23/24 lesson: don't trust
the label, check the build): confirmed the 2 divergences persist on the fresh 0.19.4 build, decoded
the reproducer to an ArrayFixlen at a scalar-Fixlen fp id (§7.3 mismatch → skip is correct), and traced
the identical **double gap** in all five storing backends — `arrayBegin` arms `askip` only for
`Unsigned`|`Signed` (never `Fixlen`/fp), **and** the `fp32()`/`fp64()` callbacks lack the `askip` guard
`unsigned()`/`signed()` carry. generator#183's own arrayBegin comment (*"an integer array…"*) is the
documentary proof the fp corner was out of its scope.
- **F-0025 catalogued** in `findings/F-0025-scalar-fp-field-receives-fp-array/` (NOTES + 2 reproducers +
  2 controls) and `results/FINDINGS.md`; the 4 isolates via `run.sh` → the 2 reproducers diverge
  (accept_value), the 2 controls agree.
- **Filed [generator#193](https://github.com/sofa-buffers/generator/issues/193)** (generator-only,
  rust-std/rust-nostd/csharp/java/zig; fix mirrors #183/#188 — arm `askip` for `Fixlen` in `arrayBegin`
  + add the guard to `fp32()`/`fp64()`). Kept **out** of the green gate; the wiretype sweep stays
  report-only until it lands. When it does: re-pull corelibs → sweep goes green → promote axis +
  isolates.

Net open: **F-0025** (generator-only, generator#193) + **F-0018** (by-design). **All other 23 findings
resolved.**

| finding | what | tracked in / status |
|---|---|---|
| F-0001 | truncated input: lenient (C/C++/Rust/Java/C#) vs strict (Go/Py/TS/Zig) | spec §7 (finish-less); all 10 corelibs + all 12 drivers implement `I`. **✅ verified green 2026-07-13** — every driver emits `I` on the F-0001 seeds (0 divergences). Was 7-accept/5-reject. |
| F-0004 | invalid UTF-8 in a string: 4 behaviors, driven by the string type | spec §8 → epic **generator#85** — ✅ **RESOLVED 2026-07-18** (sofabgen 0.18.0 / crucible#55): strict UTF-8 ON family-wide, all 12 `R invalid_msg` on malformed, all 12 `A` on valid; 14 seeds in the regression gate |
| F-0002 | corelib-c-cpp encoder left-shifts a negative value (UB) | **corelib-c-cpp#70** merged — ✅ **resolved** |
| F-0003 | Rust array-fill OOB → panic (crash/DoS) | ✅ **fully resolved.** Crash fixed by **generator#87**; the residual over-count *accept* divergence (**generator#100**) is fixed in **sofabgen 0.16.1** (commit `ca0fda7`, "reject over-count scalar arrays in every backend"). **Re-verified 2026-07-15** with a *clean non-truncated* over-count(8>5) array (`a6 06 03 08 01..08 07`): **all 12 drivers reject** (`R`) — rust-std/nostd now reject with the family. (The old 145-byte reproducer is contaminated — over-count *and* truncated — so rust/zig report `I` there; the clean isolate is the correct test.) |
| F-0005 | corelib-cpp accepts malformed msgs the family rejects | **corelib-cpp#22** closed — ✅ **resolved** |
| G-0001,3,4,5,6 | codegen weaknesses (infallible Rust/C++ decode, no-std string handling, Go bytes import) | **all fixed in sofabgen 0.15.1** (PRs #88/#92/#93/#89/#90) — see docs/SOFABGEN.md |
| G-0002 | Rust std vs no_std UTF-8 (intra-Rust) | generator#80/#91 — ✅ **fixed** (both empty on invalid); family-wide UTF-8 is F-0004 / #85 |
| G-0008 | generated one-shot decode discards the INCOMPLETE status (C#, Java) | ✅ **fixed** — sofabgen 0.15.3 ([generator#106](https://github.com/sofa-buffers/generator/pull/106) closes #105): status-surfacing `TryDecode`/`tryDecode`. Crucible C#/Java drivers now **single-pass** on it — two-pass workaround **removed** (crucible#10, 0.16.0 bump). See docs/SOFABGEN.md |
| G-0009 | generated C++ emits a schema-*unbounded* array as `std::array<T, 0>` (not `std::vector<T>`) | ✅ **fixed in sofabgen 0.16.1** ([generator#112](https://github.com/sofa-buffers/generator/issues/112), commit `7899c4b` → `std::vector`). **Re-verified 2026-07-15:** repro `03 03 07 08 09` → cpp now decodes `[7,8,9]` (was `[]`), matching the family; cpp agrees on the arr limit vectors (under/at/over-cap → `L`). **cpp rejoined the `arr` dimension** of limit mode (`scripts/run-limits.sh`, `NO_CPP` hold-out removed); limit mode green with cpp in all three dimensions. See docs/SOFABGEN.md |

**New divergences surfaced 2026-07-13 while wiring the `I` verdict — ✅ both fixed (pre-existing corelib leniency, unrelated to truncation):**
- **corelib-cpp** classified an unterminated over-long varint (>64 bits) as `I` (INCOMPLETE) where the rest say `R` (INVALID) — the measure phase treated the over-long-but-unterminated varint as a truncated tail. **Fixed** (corelib-cpp#29, in PR #28): getVarint/skipVarint report the >64-bit overflow so the measure phase rejects it.
- **corelib-ts** accepted a top-level stray sequence-end (`0x07`) as `A`, and also accepted a truncated *known* nested sequence as `A` (COMPLETE) — the pull/Cursor decoder tracked no depth. **Fixed** (corelib-ts#42, in PR #41): a `depth` counter → stray end at root = `R` (INVALID), unclosed sequence at EOF = `I` (INCOMPLETE), matching the fast path.

Both verified: full differential over the two reproducers + the F-0001 seeds across all 12 drivers = **0 divergences**.

## Spec decisions (documentation repo, MESSAGE_SPEC.md)
- **§7** (finish-less, documentation PR #12) — decode is three-valued
  COMPLETE/INCOMPLETE/INVALID, returned identically by one-shot `decode` and every
  streaming `feed`. **There is no `finish`/`finalize`/`end`**, and **INCOMPLETE is
  an explicit non-error outcome** — whether a trailing INCOMPLETE is a truncation
  error is the caller's decision (its own framing: length prefix, datagram, EOF).
  A truncated message (e.g. a lone `0x80`) is INCOMPLETE, not INVALID. Family
  implementation: epic **generator#86** + 10 per-corelib issues; Crucible-side
  verification (third verdict `I`): **crucible#8**.
- **§8** — `string` is UTF-8, `blob` is opaque bytes; strict-reject is conformant but
  gated behind a corelib flag (`SOFAB_STRICT_UTF8`) that may default OFF; conformance
  + the fuzzer run it ON.

## Gotchas / lessons
- **clang** isn't in the bare workspace (only the devcontainer): the pacemaker needs
  `apt-get install clang libclang-rt-dev llvm` there. Replay drivers build with gcc.
- **corelib-c-cpp** `sofab_istream_feed` asserts `datalen>0` (debug precondition);
  drivers guard `len==0` as the valid empty message.
- **G-0006 is fixed** (sofabgen 0.15.1, generator#84): the old `drivers/go/build.sh`
  workaround that injected a missing `bytes` import into the generated `types.go` has
  been removed — the generator now emits the import.
- **Characterize a divergence with a minimal isolate**, not a raw fuzzer input — the
  coarse `invalid_msg` reject class conflated reasons (F-0004 was mischaracterized
  until isolated).
