# Crucible — status log (chronological journal)

The **changelog + decision log**: dated, session-by-session history of what changed,
which decisions were taken and why, and where the build deviates from PLAN. This is
**history**, not the authoritative current state:

- The current as-built state is [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Per-finding truth (root cause, resolution, links) and codegen defects (G-00NN) are
  in [`../results/FINDINGS.md`](../results/FINDINGS.md).
- Root-cause clusters are in [`../results/CLUSTERS.md`](../results/CLUSTERS.md).

Entries below are append-only and may contain running totals that were later
superseded; trust `FINDINGS.md` for the current tally.

---

## Findings & tracking
Reproducers in `findings/<id>/`; catalog in `results/FINDINGS.md`; codegen-bug log
in `results/FINDINGS.md`. Fixes live in the **owning repos** (done in fresh contexts);
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

**Twenty-third change 2026-07-21 — blob_array added to `probe` (F-0013 blob-path follow-up); §7.1 blob path green; F-0026 opened; catalog 25 → 26.**
Added a `blob_array` (id 201, the blob analogue of `string_array` id 200) to `schema/probe.sofab.yaml` and
wired it through **all six sweep axes** (`sweep_positions.py` position + the overbound/wiretype/repeated-id
element handling), `engine/structured/gen.py` (6 value-rich blob vectors + the always-emitted wrapper), and
the truncation rich message. The 12 drivers rebuilt schema-agnostically under the round-trip canonical form —
**no driver change**. Two results:
- ✅ **The over-bound §7.1 blob path is GREEN** — blob-array over-index (id ≥ count) and over-maxlen elements
  → **all 12 reject**. This answers F-0013's long-open blob question: the 0.17.6 fixed-capacity fix hardened
  `_BlobSeq` too, not just the string path. The `docs/TODO.md` "F-0013 blob path" + "blob array schema" items
  are now done.
- 🆕 **F-0026 (new, open):** the §7.4 `blob_array` wrapper **re-open** (replace-whole) keeps a stale zeroed
  element on the **C object API** — `c` alone re-encodes `blob_array{id0=0000}` where the other 11 drop it.
  Minimal isolate `ce0c0213dead07ce0c07` (10 B). Root cause **corelib-c-cpp**, not codegen:
  `sofab_object_init` (`object.c:242-254`) zeros a sized blob's buffer via a generic `memset(offset,size)`
  but never its companion length at `offset - nested_idx` — the one function of four (`_field_is_default` /
  encode / decode all honour it) that omits the sized-blob branch, so the stale `len != 0` keeps the "cleared"
  element live. `string_array` (id 200) has no separate length → replaces correctly, so the split is
  blob-specific; `cpp-c-cpp` (C++ `FixedBytes` over the same corelib) agrees, confirming the pure-C
  `object.c` path only. Written up in `findings/F-0026-c-blob-wrapper-reopen-stale-element/` (NOTES +
  2 reproducers + 2 controls) + `results/FINDINGS.md`; filed [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106). Carved out of the blocking
  repeated-id sweep axis (`sweep_repeated_id.py`, `elem == "blob"` skip) and kept **out** of the gate until
  the corelib fix lands — mirroring how F-0025 keeps the wiretype axis report-only.
- ✅ **Box green:** seeds 6×12, cross-encode **75×12** (incl. the 6 new blob vectors + the +2-byte trailing
  empty `blob_array` on the existing 69), regression 73×12, all five blocking sweep axes. wiretype stays
  report-only (F-0025); repeated-id blocking-green with the blob-reopen carve-out.

Net open: **F-0025** (generator#193) + **F-0026** (corelib-c-cpp#106). Plus **F-0018** (by-design).

**Twenty-fourth change 2026-07-21/22 — the materialized-value (element-access) oracle: a second canonical form, all 12 drivers, CI-gated, schema-agnostic. Merged to `main` (PR #75), `main` CI green.**
Added a **second canonical form** (`oracle/materialized.md`) beside the round-trip re-encode, targeting the
round-trip form's *recorded* blind spot (`oracle/canonical.md` §Tradeoff — two decoders that hold different
in-memory values but re-encode to the same sparse-canonical bytes are masked, F-0010's class). Under
`SOFAB_MATERIALIZE=1` each driver emits `A <dump(decode(input))>` — a full walk of the **decoded value** (every
field + array element explicit, floats as raw bit patterns, `len:hex` strings/blobs) — reusing the comparator's
`accept_value` axis unchanged; `scripts/materialize.sh` runs it over `corpus/structured`.
- **All 12 drivers** implement it: **75×12 → 0 divergences**, each matching the `engine/structured/materialize.py`
  reference (ground truth) byte-for-byte; the default round-trip path is unchanged.
- **Wired into CI** (`replay.yml`) as a standing gate — agreement (the 12-way differential) **+** conformance
  (the schema-agnostic C anchor vs the reference, so a *family-wide-wrong* dump — agreement-green — is caught).
- **Generated schema-type table** (`engine/structured/schema.py` → `oracle/materialized-schema.json`): the
  typed field tree (kinds/ids/counts/nesting) a value walk needs is derived from the schema, not hardcoded, and
  drives the reference (schema-agnostic ground truth); `cmp`-checked each run so it can't drift.
- **All 12 walkers are schema-agnostic:** C via sofabgen's object descriptor; go/ts/java/cs/python consume the
  descriptor at runtime (reflection); rust/cpp/zig **generate their walker source** from it at build time
  (`drivers/<lang>/materialize_gen.py`, unrolled straight-line — a compile-only stub for the non-`probe`
  union/limit schemas). A schema change reflows to every walker with **zero hand-editing**.
- **Measured design note:** numeric arrays are already materialized to N in memory family-wide, so this form's
  live signal is the **wrapper arrays** + **element-level fidelity** + **regression-proofing**, not F-0010's
  exact shape (resolved). The build broke the union/limit suites once (the static generators emitted a
  default-`probe` walker for a mismatched Probe); fixed with the per-schema stub, verified across the full
  `replay.yml` sequence before merge.

Net open unchanged: **F-0025** (generator#193) + **F-0026** (corelib-c-cpp#106); **F-0018** by-design.

**Twenty-fifth change 2026-07-22 — corelib-dart integrated into every suite; roster 12→13 drivers / 10→11 corelibs (branch `dart-integration`).**
Wired sofabgen's 10th language target (crucible#77 / generator#211) into the whole harness on the
latest green sofabgen CI build (`0.0.0-20260722065611-f61a29b31c01`). New `drivers/dart/`
(`driver.dart` + `build.sh` + `meta` + `materialize_gen.py` + `fuzz.dart`), **AOT** end-to-end
(`dart compile exe`, native ELF — never `dart run`/JIT). Registered in `run.sh` (seeds/regression/
cross-encode/union), `run-limits.sh` (heap roster), `sweep_run.py` (structural sweep), `materialize.sh`
(element-access). The generated `Probe.tryDecode → DecodeStatus` maps 1:1 to `A`/`I`/`R`/`L` (sticky
`_Dec.inv` folds schema-bound violations into INVALID, the Rust/Zig model), so the schema-agnostic
round-trip form needed **zero per-field Dart code**.
- ✅ **Every suite green with 13 drivers:** seeds 6×13, regression 73×13, cross-encode 75×13, union
  11×13, limit mode (arr/str/blb) 10-heap-driver roster, structural sweep (5 blocking axes),
  materialized 75×13 + C-anchor conformance 0/75. Dart is byte-identical to Go on every seed.
- **Dart-specific care (all verified):** u64 printed unsigned via `BigInt` (`02_full` → `u18446744073709551615`,
  matches C), fp32 repacked to the 32-bit pattern, fp64 as two uint32 halves; heap profile → bakes
  `max_dyn_*` into `DecoderLimits` and emits `L` on over-cap (`over_arr → L`); §7.3/§7.4 dispatch-by-type
  skip matches the family (no desync). No Dart-attributable finding.
- 🐞 One **Crucible-side** walker bug found + fixed in Stage 4 (the `u`/`s` materialize leaves lacked
  their type-tag prefix — `0:0` vs C's `0:u0`), caught by the C-anchor conformance gate. Not a
  corelib/generator finding.
- 🔎 **Side-result (toolchain, not Dart): F-0025 is resolved on this CI build.** The wiretype (§7.3)
  sweep axis went **green** (was report-only); both F-0025 reproducers now show all 13 drivers agreeing
  (the fp array at a scalar-fp id is skipped, including the formerly-storing rust/java/csharp/zig) —
  generator#193 landed in the CI build post-0.19.4. **Promoted in the Twenty-sixth change below** (this
  branch includes the F-0025 cleanup): the wiretype axis is now blocking, F-0025 is marked resolved, and
  its isolates are in `corpus/regression/`.
- **CI:** the gates invoke the scripts (which now carry Dart), so no per-gate edit; the CI image's
  Dockerfile already installs the Dart SDK — it needs the standing one-time `image.yml` rebuild.
**Twenty-sixth change 2026-07-22 — F-0025 verified resolved; wiretype (§7.3) sweep promoted report-only → blocking; regression gate 73 → 77 (branch `f0025-cleanup`, rebased on `dart-integration`).**
Re-checking the open findings on the latest green sofabgen CI build
(`0.0.0-20260722065611-f61a29b31c01`, which carries generator#193 post-0.19.4) showed **F-0025
is fixed** — [generator#193](https://github.com/sofa-buffers/generator/issues/193) closed.
- ✅ **F-0025 resolved:** the generated `arrayBegin` now arms the discard counter (`askip`) for the
  **fp** array kinds (not only `Unsigned`/`Signed`), and the `fp32()`/`fp64()` callbacks carry the same
  `askip` guard `unsigned()`/`signed()` had — so a scalar fp field fed an fp fixlen array **skips** it
  per §7.3 instead of storing the element. Generator-only, no corelib change (mirrors #183/#188).
- **Verified two ways:** (1) the 2 reproducers → **all 13 skip** (re-encode to `5607a606560707c60c07ce0c07`),
  the 2 controls agree; (2) the **wiretype (§7.3) sweep is green** — 319 vectors, 0 divergences,
  0 conformance failures.
- **Sweep axis promoted report-only → blocking** in `scripts/sweep.sh` — **all six axes now blocking**;
  no report-only residual remains (F-0026 stays carved out of the repeated-id axis until its corelib fix).
- **Regression gate 73 → 77:** the 2 F-0025 reproducers + 2 controls promoted (`F0025_*`);
  `CORPUS=corpus/regression ./scripts/run.sh` → 77×13, 0 divergences.

Net open: only **F-0026** (corelib-c-cpp#106). Plus **F-0018** (by-design). **All 25 other catalogued
findings are resolved or by-design.**

**Twenty-seventh change 2026-07-22 — F-0026 verified resolved; last sweep carve-out dropped; regression gate 77 → 81 (branch `f0026-cleanup`). Zero open findings.**
Verifying "F-0026 is the only open finding" surfaced that it, too, is **already fixed**:
[corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) is closed and its fix
(`2416a2b`, "reset sized-blob used-length in `sofab_object_init` (§7.4 re-open)") has been on
`origin/main` — so it landed silently during the Dart session, masked because F-0026's sweep axis was
carved out and its reproducer kept out of the gate.
- ✅ **F-0026 resolved:** the C object API's `sofab_object_init` now resets a sized blob's companion
  length on a §7.4 wrapper replace-init, so a re-opened `blob_array` no longer keeps a stale zeroed
  element. Corelib-only, no codegen change.
- **Verified two ways:** (1) all 4 isolates (`blob_reopen_empty`, `blob_reopen_two` + 2 controls) →
  **all 13 drivers agree** (`c` now drops the re-opened element); (2) the `elem=="blob"` carve-out was
  removed from `sweep_repeated_id.py` and the **repeated-id (§7.4) sweep is green with the blob wrapper
  included** — 16 vectors, 0 divergences.
- **Last carve-out gone:** all six sweep axes are now blocking **with no exclusions**.
- **Regression gate 77 → 81:** the 2 F-0026 reproducers + 2 controls promoted (`F0026_*`);
  `CORPUS=corpus/regression ./scripts/run.sh` → 81×13, 0 divergences.

Net open: **none.** Plus **F-0018** (by-design). **All 25 catalogued findings are resolved; 1 by-design.**

| finding | what | tracked in / status |
|---|---|---|
| F-0001 | truncated input: lenient (C/C++/Rust/Java/C#) vs strict (Go/Py/TS/Zig) | spec §7 (finish-less); all 10 corelibs + all 12 drivers implement `I`. **✅ verified green 2026-07-13** — every driver emits `I` on the F-0001 seeds (0 divergences). Was 7-accept/5-reject. |
| F-0004 | invalid UTF-8 in a string: 4 behaviors, driven by the string type | spec §8 → epic **generator#85** — ✅ **RESOLVED 2026-07-18** (sofabgen 0.18.0 / crucible#55): strict UTF-8 ON family-wide, all 12 `R invalid_msg` on malformed, all 12 `A` on valid; 14 seeds in the regression gate |
| F-0002 | corelib-c-cpp encoder left-shifts a negative value (UB) | **corelib-c-cpp#70** merged — ✅ **resolved** |
| F-0003 | Rust array-fill OOB → panic (crash/DoS) | ✅ **fully resolved.** Crash fixed by **generator#87**; the residual over-count *accept* divergence (**generator#100**) is fixed in **sofabgen 0.16.1** (commit `ca0fda7`, "reject over-count scalar arrays in every backend"). **Re-verified 2026-07-15** with a *clean non-truncated* over-count(8>5) array (`a6 06 03 08 01..08 07`): **all 12 drivers reject** (`R`) — rust-std/nostd now reject with the family. (The old 145-byte reproducer is contaminated — over-count *and* truncated — so rust/zig report `I` there; the clean isolate is the correct test.) |
| F-0005 | corelib-cpp accepts malformed msgs the family rejects | **corelib-cpp#22** closed — ✅ **resolved** |
| G-0001,3,4,5,6 | codegen weaknesses (infallible Rust/C++ decode, no-std string handling, Go bytes import) | **all fixed in sofabgen 0.15.1** (PRs #88/#92/#93/#89/#90) — see results/FINDINGS.md |
| G-0002 | Rust std vs no_std UTF-8 (intra-Rust) | generator#80/#91 — ✅ **fixed** (both empty on invalid); family-wide UTF-8 is F-0004 / #85 |
| G-0008 | generated one-shot decode discards the INCOMPLETE status (C#, Java) | ✅ **fixed** — sofabgen 0.15.3 ([generator#106](https://github.com/sofa-buffers/generator/pull/106) closes #105): status-surfacing `TryDecode`/`tryDecode`. Crucible C#/Java drivers now **single-pass** on it — two-pass workaround **removed** (crucible#10, 0.16.0 bump). See results/FINDINGS.md |
| G-0009 | generated C++ emits a schema-*unbounded* array as `std::array<T, 0>` (not `std::vector<T>`) | ✅ **fixed in sofabgen 0.16.1** ([generator#112](https://github.com/sofa-buffers/generator/issues/112), commit `7899c4b` → `std::vector`). **Re-verified 2026-07-15:** repro `03 03 07 08 09` → cpp now decodes `[7,8,9]` (was `[]`), matching the family; cpp agrees on the arr limit vectors (under/at/over-cap → `L`). **cpp rejoined the `arr` dimension** of limit mode (`scripts/run-limits.sh`, `NO_CPP` hold-out removed); limit mode green with cpp in all three dimensions. See results/FINDINGS.md |

**New divergences surfaced 2026-07-13 while wiring the `I` verdict — ✅ both fixed (pre-existing corelib leniency, unrelated to truncation):**
- **corelib-cpp** classified an unterminated over-long varint (>64 bits) as `I` (INCOMPLETE) where the rest say `R` (INVALID) — the measure phase treated the over-long-but-unterminated varint as a truncated tail. **Fixed** (corelib-cpp#29, in PR #28): getVarint/skipVarint report the >64-bit overflow so the measure phase rejects it.
- **corelib-ts** accepted a top-level stray sequence-end (`0x07`) as `A`, and also accepted a truncated *known* nested sequence as `A` (COMPLETE) — the pull/Cursor decoder tracked no depth. **Fixed** (corelib-ts#42, in PR #41): a `depth` counter → stray end at root = `R` (INVALID), unclosed sequence at EOF = `I` (INCOMPLETE), matching the fast path.

Both verified: full differential over the two reproducers + the F-0001 seeds across all 12 drivers = **0 divergences**.

**Twenty-eighth change 2026-07-22 — WP-01: union under the structural sweeps; F-0027 opened; catalog 26 → 27, open 0 → 1.**
`docs/improvements.md` WP-01 (the biggest untested-feature gap): the `union` wire feature lived entirely
outside the generated sweep pipeline (`engine/structured/schema.py` raised `ValueError` on `union`), so
none of the six axes, cross-encode, or the materialized oracle ever saw it — union coverage was 11 static
seeds run as a plain differential with zero conformance assertions.
- **Schema pipeline learned `union`:** `schema.py` now emits a `union` descriptor node (`default_id` +
  typed `options`, string/blob options carrying `maxlen`); `descriptor('probe-union')` succeeds. The
  `probe` descriptor and committed `oracle/materialized-schema.json` are **byte-identical** (union branch
  only fires on a union field).
- **Schema-derived union position model:** `sweep_positions.UNION_POSITIONS` is *derived from the
  descriptor* (not a hand-maintained parallel literal — the drift `sweep_positions` exists to prevent):
  7 positions (tag, the `choice` union sequence, its 4 members, trailer). A union is a sequence carrying
  at most one child (§4.2); members are ordinary positions inside the union scope, `seq_union` marks the
  sequence itself.
- **Five axes gained a union pass** (`emit_union`): wiretype §7.3, repeated-id §7.4 (last-wins, merge,
  seq re-open, and the §7.4 "a §7.3-skipped occurrence doesn't count" cross vector), over-bound §7.1
  (as_text maxlen16 / as_blob maxlen8), reserved-subtype §4.6, truncation §7. Driven by
  `sweep_run.py --union`; **130 vectors**.
- **Report-only in `scripts/sweep.sh`** (ground rule 4 — a new axis is report-only until green or every
  divergence is catalogued): a labeled pass rebuilds the 13 drivers to `probe-union`, runs the union axes
  (non-blocking `|| echo`), then **rebuilds back to `probe`** so binaries are never left mixed
  (ground rule 3).
- **Result:** repeated-id, over-bound, reserved-subtype, truncation → **green across all 13**. The
  **wiretype** union pass surfaced **F-0027** (35 vectors): `rust-nostd` rejects a §7.3-skippable array
  or fp64 field that `probe-union` never declares. Root cause established (not inferred): sofabgen emits
  the no-std corelib's cargo features from the schema's *used* wire types (`["fixlen","sequence"]` vs
  `probe`'s `["array","fixlen","fp64","sequence","value64"]`), and corelib-rs-no-std gates wire-type
  *parsing/skip* — not just field storage — behind those features. Minimal isolate `0300` (2 B). The
  probe wiretype axis stays green (319×13), and `rust-std` (same generated code) agrees with the family —
  the two-way sibling split pinning it to the feature config, i.e. codegen. **Generator-primary → G-0017**,
  corelib-rs-no-std implicated (F-0010 "occasionally both"). Filed `results/FINDINGS.md` F-0027 +
  `results/FINDINGS.md` G-0017 with reproducers under `findings/F-0027-*`.
- **Not yet promoted / not in the gate** until the fix lands — per the F-0025/F-0026 arc.

**Twenty-ninth change 2026-07-23 — WP-11: harness hygiene (one position model, schema-derived bounds); no finding.**
(`docs/improvements.md` WP-11 — parallel ordinal, reconcile at merge.) Removes three silent-desync risks
in the sweep harness before WP-05's schema growth lands:
- **One position model.** `wiretype_sweep.py`'s private 29-entry position list (which uniquely carried the
  wrapper-**element** positions) is gone; the wrapper elements (`welem_str`/`welem_blob`) now live in
  `sweep_positions.POSITIONS` (27→29) and `wiretype_sweep` consumes it via a new `CAT_TO_CONSTRUCT` map.
  **Gap closed:** reserved-subtype (§4.6) now sweeps the wrapper elements too — 110→**118** vectors; all
  +8 reject uniformly (green). wiretype stays 319; every other axis unchanged — **no count dropped** (the
  WP-11 hard-fail guard).
- **Schema-derived bounds.** `count`/`maxlen` come from `schema/probe.sofab.yaml` (`_BOUNDS`), not literals
  `5`/`64`/`32`/`4`; `materialize.py`'s `ARR_COUNT` is derived from the descriptor + a uniform-count
  assertion. Committed `oracle/materialized-schema.json` unchanged.
- **`STRUCT_CHILDREN`** for id 100 now lists all eight arrays (was two); the §7.4 merge test still samples
  the first two (documented as sufficient). Doc drift "all 12"→"all 13" swept across `engine/structured/*.py`.
- **Verified:** all six blocking axes green; derived bounds byte-match the old literals; materialize
  reference byte-identical (ARR_COUNT still 5). Pure hygiene — no behavior change beyond the one gap closed.

**Thirtieth change 2026-07-22 — WP-03: non-minimal varint axis added (blocking, agreement-only); documentation#24 filed.**
(`docs/improvements.md` WP-03. Ordinal parallel to the WP-01 branch's own "Twenty-eighth" — reconcile at merge.)
A varint admits **non-minimal** forms — redundant `0x80` continuation bytes that add only zero high bits
(`5` = `05` = `85 00` = `85 80 00` …). `gen.varint` only emits minimal encodings, so no corpus contained
one; F-0016 covered only the **>64-bit overflow**. Whether the 13 decoders agree on a non-minimal-but-
≤64-bit varint was untested — a classic silent-divergence class.
- **New axis `engine/structured/sweep_varint.py`** places a non-minimal varint at every varint **role** —
  field-id header, fixlen length word, array element-count, array element value, and inside a skipped
  (unknown-id) field — padded +1/+3 bytes and up to the 10-byte ≤64-bit maximum, with minimal-accept
  controls and an 11-byte >64-bit overflow-reject contrast. 23 vectors. `gen.varint` left untouched (it is
  the canonical reference encoder).
- **Result: green — all 13 accept every non-minimal varint and re-encode to the identical minimal
  canonical form** (the round-trip normalizes it), and all 13 reject the overflow. Zero divergences.
- **Spec is silent** (CORELIB_PLAN §4.1 guards only overflow; MESSAGE_SPEC §2 constrains the encoder, not
  the decoder), so per ground rule 6 the axis is **blocking but agreement-only**: the 18 non-minimal
  vectors carry `expect="agree"` (only agreement + round-trip normalization asserted, not accept-vs-reject
  conformance) until the clause lands. Filed **[documentation#24](https://github.com/sofa-buffers/documentation/issues/24)**
  proposing the observed consensus as the rule; on adoption the
  vectors tighten to `expect="accept"`. **No finding** (green). Promoted to blocking + wired into
  `replay.yml` (via `sweep.sh`); the sweep gate is now **seven axes**.

**Thirty-first change 2026-07-23 — WP-04: framing & format-ceiling axis added (report-only); F-0028 + F-0029 opened.**
(`docs/improvements.md` WP-04. Ordinal parallel to the WP-01/WP-03 branches — reconcile at merge; finding
numbers skip F-0027, reserved by the WP-01 PR.) Two malformation classes had **no dedicated coverage**:
stray/unbalanced `sequence-end` (§5.2 — `sweep_truncation` only ever produces *open* sequences) and the
format-wide ceilings ID_MAX / FIXLEN_MAX / ARRAY_MAX / MAX_DEPTH (§6.2, reachable only by fuzzer luck).
- **New axis `engine/structured/sweep_framing.py`** (14 vectors): stray end at top level / after a scalar /
  as a surplus close / inside a wrapper; field id at ID_MAX (accept control) and over (reject); fixlen
  length over FIXLEN_MAX and array count over ARRAY_MAX at **unknown ids** (so the *format* ceiling is
  tested, not the schema `count`/`maxlen` nor the open documentation#15 over-schema-count corner), with
  **huge declared size but no payload** (a conformant decoder rejects at the word and never allocates —
  the F-0013 amplification guard); nesting past MAX_DEPTH. Report-only in `scripts/sweep.sh`.
- **Green:** stray-end (all forms), FIXLEN_MAX, ARRAY_MAX → all 13 reject; controls accept. **Two
  divergences → findings:**
  - **F-0028** — `cpp` + `dart` **accept** a field id > ID_MAX (skip it as unknown) where 11 reject.
    Both check ID_MAX only on **encode** (`corelib-cpp sofab.hpp:475`; `corelib-dart encoder.dart:140`);
    their **decoders** (`sofab.hpp:1410`; `decoder.dart:221`) omit it. corelib-c-cpp checks it in the
    decoder (`istream.c:485`), so `cpp-c-cpp` rejects — pinning it to the two pure decoders. Corelib, not
    codegen (ID_MAX is a format constant). → [corelib-cpp#47](https://github.com/sofa-buffers/corelib-cpp/issues/47)
    + [corelib-dart#14](https://github.com/sofa-buffers/corelib-dart/issues/14).
  - **F-0029** — `typescript` reports `I` for nesting past MAX_DEPTH where 12 reject. The `cursor` decode
    path tracks `depth` only for balancing; `fast.ts`/`state.ts` enforce MAX_DEPTH but `cursor.ts` does
    not — an internal inconsistency. → [corelib-ts#65](https://github.com/sofa-buffers/corelib-ts/issues/65).
- Both are **corelib** (wire/format checks, schema-independent), reproducers under `findings/F-0028-*`,
  `findings/F-0029-*`. Axis kept report-only; promote + gate on resolution (F-0025/F-0026 arc).

**Thirty-second change 2026-07-23 — WP-02 Part A: union cross-encode (green); Part B (materialized) scoped.**
(`docs/improvements.md` WP-02.) The union value space was never cross-encoded. `gen.py` gained
`encode_union` + `union_vectors` (18 value-rich vectors: each member at boundary values, default_id, and
tag+member+trailer combos) → `corpus/structured-union/` via `gen.py --union`; `scripts/cross-encode.sh`
runs a second **union pass** (rebuild → probe-union → differential → restore probe). **18 × 13 → 0
divergences** — the union value space round-trips identically. Blocking, gated by `replay.yml`. **Part B**
(the materialized/element-access dimension for unions) is a scoped follow-up: the C anchor materializes a
union out-of-the-box (target form `{opt_id:value}` for every member), but the other 12 walkers (6 runtime
+ 6 generated) don't yet handle the `union` descriptor node — a ~12-walker sub-project across 10 languages
+ a `materialize.py` union reference. No finding.

**Thirty-third change 2026-07-23 — WP-06: float specials + integer gaps in the cross-encode/materialized corpus; F-0031 opened.**
(`docs/improvements.md` WP-06.) `gen.py` covered only min-*normal* floats and one quiet NaN; the value
space missed subnormals, the signaling/payload/negative NaN variants, and unsigned mid values. Added (with
raw-byte fp support so exact bit patterns survive Python's float canonicalization): min/max subnormal
f32+f64, quiet-payload NaN, negative NaN, fp64 sNaN, explicit +0.0, and unsigned mid values; `materialize.py`
gained raw-bytes fp handling (element-access compares raw bits). `gen.py` now also **clears stale corpus
files** before regenerating (vector indices shift when the set grows). Corpus 75 → **90** vectors.
- **Green:** subnormals / qNaN-payload / negative-NaN / fp64-sNaN / +0.0 / int-mid all round-trip **and**
  materialize identically across 13 (cross-encode 90×13, materialized 90×13, 0 divergences).
- **F-0031** (the one split): an fp32 **signaling** NaN (`0x7F800001`) is **quieted** to `0x7FC00001` by
  `py-cython`, `typescript`, `dart` (double-backed fp32) where the other 10 — incl. `py-pure` — preserve
  it, violating §4.6 (bit-for-bit, no normalization). Corelib; →
  [corelib-py#49](https://github.com/sofa-buffers/corelib-py/issues/49) +
  [corelib-ts#66](https://github.com/sofa-buffers/corelib-ts/issues/66) +
  [corelib-dart#15](https://github.com/sofa-buffers/corelib-dart/issues/15). The `f32_snan` vector is
  carved out of the green gate (reproducer `findings/F-0031-*`) until fixed; the quiet-payload/negative/f64
  NaN variants stay in the gate (all preserve).

**Thirty-fourth change 2026-07-23 — WP-07: over-bound magnitude (mid + large) added to the §7.1 sweep.**
(`docs/improvements.md` WP-07.) `sweep_overbound` tested only bound+1 / id==count. Added per bounded
position a **mid** over (2×bound) and a **large** over-INDEX (element id 100_000 — declared, well-formed,
small input): F-0013's memory-amplification bug is the large-index class, and a decoder must reject at the
header word without sizing a container to the index. Axis **30 → 46 vectors, green, sub-second** (no
allocation/DoS). The large *over-maxlen* case (declared-huge length + short payload) is inherently
over-maxlen AND truncated — the §5.2 over-length-vs-INCOMPLETE precedence corner (it split R-vs-I in
testing) — so it is deferred to the malform×truncation axis (WP-09), not this clean-magnitude axis. No
finding.

**Thirty-fifth change 2026-07-23 — WP-08: §2/§3 canonicality conformance seeds (a)+(b); (c) blocked on WP-05.**
(`docs/improvements.md` WP-08.) New `corpus/conformance/` gate (wired into `replay.yml`) pinning two §2/§3
rules that were only incidentally covered: (a) §2:77-86 — an all-default nested struct is still framed as
an empty sequence, never dropped; (b) §3:185-195 — a decoder accepts a non-canonical trailing-default
array run and re-encodes it canonically (trailing run trimmed, the F-0010 rule). 3 seeds × 13 → green;
(b) verified re-encodes to count 3 `[1,2,3]` = the canonical control. **(c)** (explicit `[]` overrides a
non-empty field default, §2:112-121) is **blocked on WP-05** — no `probe` field has a non-zero `default:`
yet; lands when `struct_array` folds in (corelib-c-cpp#109). No finding.

**Thirty-sixth change 2026-07-23 — WP-09: broadened malform×truncation; F-0032 opened (§5.2 schema-bound precedence).**
(`docs/improvements.md` WP-09.) `sweep_malform_truncate` sampled 9 malformations × one tail byte. Added
malformations (blob_array over-id, array fixlen element-word/F-0014, reserved-subtype in each wrapper) and
broadened truncation to **every offset from each malformation's INVALID-point**. **Structural**
malformations (reserved subtype, bad array element-word — INVALID at the word) → all 13 `R` at every
truncation (blocking, green). **Schema-bound** malformations (over-maxlen/count/index) checked after
reading → **F-0032**: go/cpp/ts/dart (and more, varying by bound) report `I` where §5.2 requires `R`
(documentation#15 adopted; the F-0024 class still open for schema-bound checks). Codegen →
[generator#216](https://github.com/sofa-buffers/generator/issues/216) / **G-0018**. Their into-payload
truncations are carved out (the axis `STRUCTURAL` set); `_complete` controls + structural truncations stay
blocking (axis 20 → 43 vectors, green). Finding count 31 → 32, open 5 → 6.

**Thirty-seventh change 2026-07-23 — WP-10: UTF-8 at more positions (Part A); STRICT_UTF8=OFF audit (phase 1); phase 2 deferred.**
(`docs/improvements.md` WP-10.) **Part A:** `utf8_seeds.py` now emits each malformed-UTF-8 vector at BOTH
`nested.str` (id 2) and a `string_array` element (id 200.0) via a shared `_probe(...)` framer — the strict
reject is now proven at the wrapper element too; also fixed stale framing (the old framer predated
`blob_array`, so its gen.encode self-check would fail). 28 F0004 seeds (14×2), regression gate green
(95×13). **Part B phase-1 audit:** the byte-container profiles (c, cpp-c-cpp, cpp, zig) have explicit
strict flags → OFF reachable (raw bytes); the Unicode-string profiles validate inside corelib/codegen
(OFF-reachability unclear). Table in `docs/improvements.md` WP-10. **Phase 2** (opt-in strict-OFF suite)
**deferred** — a substantial env-gated build variant + per-profile-class policy for a non-default config,
needing the gen#85 Unicode audit first; the ON path is fully covered (F-0004 / Part A). No finding.

**Thirty-eighth change 2026-07-23 — C pacemaker fuzzing round (34 M execs); F-0033 opened (scalar over-width, spec hole).**
First fuzzing round this session (`scripts/fuzz.sh`, FUZZ_TIME=1500, ~22.6k exec/s, **0 ASan/UBSan hits** —
the C corelib stays clean). Corpus grew 388 → 439; the differential replay + `oracle/cluster.py` reduced
294 diverging inputs to 13 root-cause clusters. 12 mapped to **known** classes (java `incomplete_value`
soft; F-0028/F-0029; the F-0032 §5.2 schema-bound-vs-truncation family — incl. an old 2026-07-08
`crash-java-array-oom` artifact, now non-crashing = the F-0032 over-count facet; the 2 other old crash
artifacts no longer crash). **One new:** **F-0033** — a scalar wire value exceeding its declared width
(u8 > 255) splits 3 ways (reject / mask-to-width / keep-full-value); the spec is silent (§1 "storage hint,
wire carries the integer regardless"; §7 "value-range outside the wire clause"; §7.1 omits scalar
over-width). Spec hole → [documentation#26](https://github.com/sofa-buffers/documentation/issues/26). The
hand-built value corpus never emits an over-width scalar — only fuzzing reached it.

**Thirty-ninth change 2026-07-23 — toolchain + corelib bump re-verified; F-0034 opened (dart fixlen `maxlen`
guard ignores subtype, codegen).** Re-bootstrapped: sofabgen → CI build `0.0.0-20260723154129-241dc8f44efb`;
6 corelibs advanced to `origin/main` (c-cpp `aaba509`, cpp `3cee07f`, dart `f9e64ec`, go `05fe6c2`, py
`a20a96a`, ts `92a6e21`), 5 unchanged. Full re-run: **seeds green** (0 div), **regression green** (95, 0 div,
4 known `incomplete_value` soft), all blocking sweep axes green **except one new wiretype (§7.3) divergence**.
**F-0034 / G-0019** — the corelib-dart bump (`f9e64ec`, "INVALID dominates INCOMPLETE via header callbacks")
added `onFixlenHeader(id, subtype, length)`; the generated dart `ProbeNested.onFixlenHeader` enforces the
blob field's `maxlen 4` against an fp64 mismatch's 8-byte payload **without gating on subtype**, so it
rejects a §7.3-skippable field (12 skip → `A`, dart → `R`). **Attribution: codegen** (subtype/maxlen are
schema facts; corelib faithfully reports the header and is not implicated). Filed
[generator#224](https://github.com/sofa-buffers/generator/issues/224). **Decision:** carved the one divergent
cell (`10_id3_FIX_fp64`) out of the blocking wiretype axis via `KNOWN_OPEN` in `wiretype_sweep.py` (the
F-0032 `STRUCTURAL` carve-out precedent) — axis green-except-known (318 vectors) until fixed; isolate +
control kept **out** of the green `corpus/regression/` gate while open. (The `interesting` fuzz corpus, 439,
shows its usual raw divergences — exploration fodder, not a gate; unchanged.)

**Also this session — F-0027 / G-0017 RESOLVED by the same bump.** [generator#215](https://github.com/sofa-buffers/generator/issues/215)
(no-std Cargo features derived from the schema's used wire types → decoder can't §7.3-skip an array/fp64
field) was **closed 2026-07-23**; the CI build `0.0.0-20260723154129-241dc8f44efb` carries the fix (sofabgen
now provisions the full wire-type decoder feature set regardless of schema). **Re-verified in Crucible:** the
wiretype (§7.3) **union** pass — 13 drivers built against `probe-union`, the schema that omits the
array/fp64 features — is now **green (77 vectors, 0 divergences)** across two sweep runs, where rust-nostd
previously rejected. FINDINGS.md F-0027/G-0017 moved to resolved.

**One-hour fuzz round (C pacemaker, post-bump) — 0 new signal.** 38.55 M execs, ~10.7k exec/s, **0 ASan/UBSan
hits**, no new crash artifact (`corpus/crashes/` unchanged — its files pre-date this run). Corpus grew
439 → 546 (coverage only). Differential + `oracle/cluster.py` over 546 inputs → 12 root-cause clusters, the
**same set as before the round** (matching representative inputs), all mapping to catalogued classes (the
F-0032 §5.2 family, F-0033 scalar over-width, F-0029 ts MAX_DEPTH, java `incomplete_value` soft) — **no new
finding**. Confirms the corelib bump introduced nothing beyond F-0034; the well-formed-wrong-subtype needle
F-0034 sits on is reached by the structured sweep, not byte-mutation fuzzing (wiretype_sweep.py docstring).

---

# Decision log & deviations (moved from ARCHITECTURE.md)

These dated decisions, PLAN-deviations, and the first-finding narrative used to live
in `ARCHITECTURE.md`. Per the SSOT split (ARCHITECTURE describes only the current as-built state),
the *when/why* history belongs here with the rest of the chronological log; the
resulting *what-is* stays in ARCHITECTURE.

## Key decisions (decision log)

- **2026-07-22 — `SOFABGEN.md` moved `docs/` → `results/`.** The G-00NN codegen-defect
  log is the generator-side sibling of `results/FINDINGS.md` (corelib bugs); Crucible's
  triage splits every finding into exactly those two catalogs by owning repo, so they now
  live together under `results/` (the "what the fuzzer surfaced" tree), leaving `docs/` for
  harness design/plan/status. All references rewritten in the same change (README, CLAUDE.md
  incl. the triage table, ARCHITECTURE/STATUS/TODO, FINDINGS, and the `findings/*/NOTES.md`
  that cite G-numbers).
- **2026-07-18 — drivers build with strict UTF-8 ON (F-0004 / crucible#55).** The
  fuzzer runs the §8 `SOFAB_STRICT_UTF8` check ON so an invalid-UTF-8 `string` is
  rejected family-uniformly. Most drivers are strict by default (go/zig/cpp default
  ON; py/ts/java/cs/rs Unicode types always strict); the **C corelib defaults OFF**
  for footprint, so the two corelib-c-cpp-based drivers opt in: `drivers/c/build.sh`
  and `drivers/cpp/build.sh` (`c-cpp`) add `-DSOFAB_ENABLE_STRICT_UTF8` and compile
  `corelib-c-cpp/src/utf8.c` (defines `sofab_utf8_valid`). The **zig** driver builds
  the corelib as a bare module with `zig build-exe` (no `build.zig`), so it
  synthesizes the `build_options` module corelib-zig's `utf8.zig` imports
  (`strict_utf8 = true`). Seeds: `engine/structured/utf8_seeds.py`.
- **Separate repo, arena-cloned structure.** Instrumented (sanitizer+coverage)
  vs arena's optimized builds; opposite configs → own repo. See PLAN §2, §11.
- **One coverage pacemaker (C), N differential oracles.** PLAN §3.
- **Purpose-built driver ABI, not the generator CLI.** Persistent + canonical
  diff form, not process-per-input JSON. PLAN §7.
- **The oracle is disagreement, not the crash.** PLAN §1, §6.
- **Name:** `crucible` (`corelib-*` is reserved).
- **2026-07-08 — comparator has no driver registry.** Drivers are passed to
  `comparator.py` as `name:path`; adding a language needs no central edit, only a
  `--driver` flag in `run.sh` (mirrors arena's "impls discovered from output").
- **2026-07-08 — bring up on a minimal schema, not full-scale.** Fastest path to
  a proven loop, canonical form, and comparator. See Deviation 2026-07-08a.
- **2026-07-08 — Rust: capture the corelib's verdict, not the generated API's.**
  The generated Rust `decode` was infallible; testing it verbatim would make Rust
  ACCEPT everything and flood the comparator with codegen-artifact divergences.
  The driver originally read the corelib's true `feed` result via a two-pass
  (null-visitor verdict + `decode` value), isolating wire semantics from the
  codegen's error-handling gap (results/FINDINGS.md G-0001). **Superseded
  2026-07-14 (crucible#10):** G-0001 is fixed — the driver is now single-pass on
  the fallible `try_decode`, which surfaces the verdict directly *and* runs the
  real generated per-field checks the null-visitor pass had skipped (e.g. the
  over-count-array check; F-0003 / generator#100 — **fixed in sofabgen 0.16.1**,
  re-verified 2026-07-15: clean over-count array → rust `R`).
- **2026-07-08 — generated-code weaknesses go to results/FINDINGS.md.** Building the
  Rust drivers surfaced four (G-0001 infallible decode; G-0002 std/no-std invalid
  UTF-8; G-0003 std/no-std chunked strings; G-0004 no-std silent capacity drop);
  the C++ drivers a fifth (G-0005 infallible C++ decode). Crucible tests corelibs,
  but codegen ships to users, so codegen defects are tracked as generator changes,
  not worked around silently. (Python's generated `decode` *raises* — the
  fallible model G-0001/G-0005 propose for Rust/C++.)
- **2026-07-08 — comparator is crash-isolating.** A driver that dies mid-stream
  (fewer output lines than inputs) is reported as `[CRASH] driver X on input N`
  and the run continues comparing the survivors, instead of aborting the whole
  differential. Necessary once the pacemaker feeds adversarial inputs — a
  crashing implementation (F-0003) is itself a finding, not a harness failure.
- **2026-07-15 — comparator is hang-isolating (per-driver timeout).** Companion to
  crash isolation: a per-driver wall-clock budget (`--timeout`, default
  `max(30s, 0.25s × corpus size)`; `TIMEOUT=` env through `run.sh`/`run-limits.sh`).
  `run_driver` sends the driver's stdout/stderr to temp files (not pipes) so that on
  a `subprocess` timeout — which on POSIX does *not* carry the killed process's
  partial output — the flushed lines are still recovered; the culprit is the input
  at index `len(lines)`, reported `[TIMEOUT] driver X hung … culprit ≈ input N`.
  `cluster.py` recovers past it exactly like a crash. A driver that takes unbounded
  time on a small malformed input is a **DoS finding**, not a wedged run (the
  gap the structure-aware mutator surfaced: maxed array counts / deep nesting made
  the replay loop crawl). Precision note: exact for flush-per-line drivers; a
  slurp-then-emit driver (ts) yields 0 partial lines, so it reports "hung, produced
  0/N" without a precise index — bisection to localize those is a follow-up.
- **2026-07-08 — canonical form v1: round-trip re-encoding.** Replaced the v0
  per-field text form with `A <hex(encode(decode(input)))>`. Reason: the full-scale
  message (arrays, nested structs, unions) makes per-field walking in 12 languages
  intractable and error-prone; re-encoding the decoded value is schema-agnostic
  (drivers reference no fields) and identical across the family because the
  encoders are sparse-canonical (the arena reference-wire invariant). Also gives
  the round-trip oracle for free. Tradeoff (benign masking of encode-equivalent
  differences) recorded in `oracle/canonical.md`. This is what surfaced F-0002.
- **2026-07-13 — canonical form v2: three-valued verdict (`A`/`I`/`R`).** Added a
  third verdict line `I` (INCOMPLETE) alongside `A`/`R`, tracking the finish-less
  MESSAGE_SPEC §7 decode model (documentation PR #12). Truncated input is
  INCOMPLETE — a distinct, non-error outcome — not accept and not reject. Touched
  the canonical-form triad together (the CLAUDE.md invariant): the grammar +
  three-verdict table in `oracle/canonical.md`, the `parse()`/compare logic in
  `oracle/comparator.py` (new `incomplete_value` axis, soft), and the driver
  contract in `drivers/common/CONTRACT.md`. `policy.yaml` gains
  `incomplete_value: soft` and resolves the PLAN §8 truncated-input question
  (SPECIFIED as INCOMPLETE). Drivers emit `I` only once their corelib exposes the
  state (generator#86 + per-corelib issues); until then F-0001 stays red — the
  correct signal. Verification tracked in crucible#8. See Deviation 2026-07-13a.
- **2026-07-08 — Python: build the Cython extension per interpreter.** The
  prebuilt `_speedups.so` is version-specific; a mismatched CPython silently falls
  back to pure, so "cython" mode would be a false label. build.sh compiles the
  extension for the venv's interpreter and asserts `sofab.IMPL` matches the
  requested mode.
- **2026-07-16 — the regression corpus admits an input only when it is green *for
  the reason the finding is about*.** The tempting rule is "a finding is fixed →
  its reproducer joins the gate." That is wrong here, because several reproducers
  are raw fuzzer inputs that trip **two** axes: F-0003's `array_overflow.bin` is
  over-count *and* truncated, F-0008's `hang_min.bin` is over-index *and*
  truncated. Both findings are fixed, yet both inputs still split the family on the
  *open* INVALID-vs-INCOMPLETE precedence hole (documentation#15). Admitting them
  would force a choice between a red gate and a policy exception that mutes a real
  open divergence. So a contaminated reproducer stays in `findings/` and the gate
  gets a **clean isolate** (`engine/structured/isolates.py`) testing the one axis —
  the F-0004 lesson ("characterize with a minimal isolate, not a raw fuzzer input")
  applied to the gate. Corollary: **never weaken the gate to admit an input.** The
  exclusions and their reasons are listed in `corpus/regression/README.md`, so an
  excluded reproducer is visibly deferred rather than silently forgotten.

## Deviations from PLAN

### 2026-07-23d — float bit-pattern specials + integer gaps in the value corpus (WP-06)
- **PLAN says:** the cross-encode + materialized oracles run valid, value-rich messages so encoders and
  decoders are cross-checked on the value space wire-mutation misses (PLAN §6).
- **Change (docs/improvements.md WP-06):** `gen.py` gained **raw-byte fp support** (`fp32`/`fp64` accept
  bytes; `f32b`/`f64b` pin an exact 32/64-bit pattern — a Python float round-trip would canonicalize a NaN)
  and vectors for the previously-missing value corners: min/max **subnormal** f32+f64, **quiet-payload**
  NaN, **negative** NaN, **fp64 sNaN**, explicit **+0.0**, and unsigned **mid** values. `materialize.py`
  handles raw-byte fp (the element-access oracle already compares floats by raw bits). `gen.py` now clears
  stale `*.bin` before regenerating (vector indices shift as the set grows, and the committed corpus is
  replayed with `REGEN=0`). Corpus 75 → **90** vectors; cross-encode + materialized green (90×13 each).
- **F-0031 carved out:** an fp32 *signaling* NaN (`0x7F800001`) is quieted to `0x7FC00001` by
  `py-cython`/`typescript`/`dart` (double-backed fp32) where the other 10 (incl. `py-pure`) preserve it —
  §4.6 requires bit-for-bit, no normalization. Filed corelib-py#49 / corelib-ts#66 / corelib-dart#15; the
  `f32_snan` vector is held out of the green gate (`findings/F-0031`) until fixed.


### 2026-07-23c — union value space cross-encoded (WP-02 Part A)
- **PLAN says:** the cross-encode oracle (PLAN §6) runs valid, value-rich messages through the
  round-trip + decode-agreement oracle; `schema/` is the single source of the fuzzed message.
- **Change (docs/improvements.md WP-02 Part A):** `gen.py` gained `encode_union` + `union_vectors`
  (18 value-rich union vectors — each member at boundary values, `default_id`, tag+member+trailer
  combos) written to `corpus/structured-union/` via `gen.py --union`. `scripts/cross-encode.sh` runs a
  second **union pass** over `schema/probe-union.sofab.yaml` (rebuild the roster → probe-union →
  differential → restore probe binaries, the SCHEMA-switch discipline), gated by `replay.yml` (which runs
  `cross-encode.sh`). **18 × 13 → 0 divergences** — the union value space round-trips identically; blocking.
- **Part B deferred:** the union *materialized* (element-access) oracle is a scoped follow-up — the C anchor
  materializes a union out-of-the-box (form `{opt_id:value}` for every member), but the 6 runtime walkers
  (go/py×2/java/ts/cs) and 6 generated walkers (rust×2/cpp/cpp-c-cpp/zig/dart) plus `materialize.py` need
  `union`-node support (a ~12-walker sub-project). `oracle/materialized.md` gets the union form then.


### 2026-07-23b — harness hygiene: one position model, schema-derived bounds (WP-11)
- **PLAN says:** `schema/` is the single source of the fuzzed message; the sweep family
  enumerates a rule across every position of it.
- **Change (docs/improvements.md WP-11):** removes three silent-desync risks in the
  sweep harness — no coverage change beyond one gap closed:
  - **One position model.** `wiretype_sweep.py` carried its own parallel position list
    (29 entries, including the wrapper-**element** positions the shared
    `sweep_positions.POSITIONS` lacked — so wrapper elements were swept for §7.3 but not
    §4.6). The wrapper-element positions (`welem_str`/`welem_blob`) now live in
    `sweep_positions.POSITIONS` (27→29), and `wiretype_sweep` consumes it via a new
    `CAT_TO_CONSTRUCT` map. A schema change is mirrored **once**. Consequence:
    reserved-subtype (§4.6) now also sweeps the wrapper elements — its vector count rose
    110→**118** (+2 positions × 4 reserved subtypes), a **gap closed**; wiretype stays 319,
    every other axis unchanged (no count dropped — the WP-11 hard-fail guard).
  - **Schema-derived bounds.** `sweep_positions` read `count`/`maxlen` from bare literals
    (`5`/`64`/`32`/`4`); they now come from `_BOUNDS`, read from `schema/probe.sofab.yaml`
    (the single source). `materialize.py`'s `ARR_COUNT = 5` is now derived from the schema
    descriptor with a uniform-count assertion (fails loudly on a non-uniform schema
    instead of silently mis-padding). Committed `oracle/materialized-schema.json` unchanged.
  - **`STRUCT_CHILDREN`** for the `arrays` (id 100) scope now lists all eight numeric
    arrays (was two); the §7.4 merge-vs-replace test still samples the first two (two
    distinct child ids suffice to distinguish merge from replace — documented, not left
    ambiguous), the rest available for wider reopen tests.
  - **Doc drift:** the "all 12"/"12 drivers" mentions across `engine/structured/*.py`
    (13 since Dart) are swept.
- **Verified:** all six blocking sweep axes green post-refactor (reserved-subtype's +8
  wrapper-element vectors reject uniformly); emit counts identical or higher than before;
  derived bounds byte-match the old literals. Lands **before** WP-05's schema growth so
  the new composite-array field enters one position model, not two.

### 2026-07-23a — framing & format-ceiling sweep axis added (WP-04, report-only)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  schema position; a divergence is a finding.
- **Change (docs/improvements.md WP-04):** a seventh axis
  `engine/structured/sweep_framing.py` covering two malformation classes with no
  dedicated coverage — stray/unbalanced `sequence-end` (§5.2; `sweep_truncation` only
  emits *open* sequences) and the format ceilings ID_MAX / FIXLEN_MAX / ARRAY_MAX /
  MAX_DEPTH (§6.2). Over-ceiling values sit at **unknown field ids** and use **2³¹**
  (over the ceiling on every profile), and declare a huge size with **no payload** so a
  conformant decoder rejects at the header word and never allocates (the F-0013
  amplification discipline). Registered via `scripts/sweep.sh` **report-only** (the axis
  is not green — see below); `gen.varint`/`gen.py` primitives only, hand-built vectors.
- **Report-only, not blocking:** the axis found two divergences (ground rule 4 keeps a
  non-green axis report-only until every divergence is a catalogued finding):
  - **F-0028** — `cpp` + `dart` decoders accept a field id > ID_MAX (skip it) where 11
    reject; both check ID_MAX only on encode. → corelib-cpp#47 + corelib-dart#14.
  - **F-0029** — `typescript`'s `cursor` decode path reports INCOMPLETE for nesting past
    MAX_DEPTH (its `fast.ts`/`state.ts` paths enforce it; `cursor.ts` does not).
    → corelib-ts#65.
  Both corelib (format ceilings are schema-independent wire checks), not codegen. The
  stray-end, FIXLEN_MAX and ARRAY_MAX vectors are green across all 13. Promote the axis
  to blocking + gate the reproducers once the findings resolve (the F-0025/F-0026 arc).

### 2026-07-22d — non-minimal varint sweep axis added (WP-03; sweep gate 6→7 axes)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  schema position; a divergence is a finding, a spec-silent case is a spec hole (§8).
- **Change (docs/improvements.md WP-03):** a seventh sweep axis
  `engine/structured/sweep_varint.py` (§2 varint canonicality). A varint admits
  non-minimal forms (redundant continuation bytes adding zero high bits); `gen.varint`
  emits only minimal ones, so no corpus reached this class (F-0016 covered only the
  >64-bit overflow). The axis places a non-minimal varint at every varint **role**
  (field-id header, fixlen length word, array count, array element, and inside a skipped
  field) with minimal-accept controls and an overflow-reject contrast. Registered in
  `sweep_run.py` `AXES`, blocking in `scripts/sweep.sh`, gated by `replay.yml` (which runs
  `sweep.sh`). `gen.varint` is left untouched — it is the canonical reference encoder;
  the non-minimal forms are hand-built in the axis.
- **Blocking but agreement-only:** the spec is **silent** on a non-minimal-but-≤64-bit
  varint (CORELIB_PLAN §4.1 guards only overflow; MESSAGE_SPEC §2 constrains the encoder,
  not the decoder). Per ground rule 6 the 18 non-minimal vectors carry `expect="agree"` —
  the runner asserts only that all 13 agree (and, for free, that the round-trip normalizes
  them to the one canonical form), **not** accept-vs-reject conformance — until a clause
  lands. Filed [documentation#24](https://github.com/sofa-buffers/documentation/issues/24)
  proposing the observed consensus (accept + normalize; reject
  overflow). On adoption the vectors tighten to `expect="accept"` and the axis becomes a
  conformance gate.
- **Result:** green — all 13 accept every non-minimal varint and re-encode identically to
  the minimal canonical form; all 13 reject the overflow. 23 vectors, 0 divergences. No
  finding.

### 2026-07-22c — union pulled under the structural sweeps (WP-01)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  position of the fuzzed message; `schema/` is the single source of the fuzzed message.
  Union coverage was a separate differential suite (`run-union.sh`) over 11 static seeds.
- **Change (docs/improvements.md WP-01):** the `union` wire feature — previously invisible
  to the generated pipeline (`engine/structured/schema.py` raised `ValueError` on `union`) —
  is now swept. `schema.py` learned the `union` kind; `sweep_positions.UNION_POSITIONS` is
  **derived from that descriptor** (not a second hand-maintained position literal); five axes
  (wiretype §7.3, repeated-id §7.4, over-bound §7.1, reserved-subtype §4.6, truncation §7)
  gained an `emit_union` pass; `sweep_run.py` gained `--union`; `scripts/sweep.sh` runs a
  **report-only** union pass that rebuilds the 13 drivers to `probe-union`, runs the axes, and
  rebuilds back to `probe` (the SCHEMA-switch discipline, so binaries are never left mixed).
- **Why a second schema, not folded into `probe`:** `probe` is byte-canonical and stable;
  a union member selected by id does not fit the fixed-shape `probe` cleanly, so the union
  lives in its own `probe-union` schema (the same reasoning `run-union.sh` already used). The
  sweep now parameterizes the position model *by schema* to reach it — a step toward WP-11's
  one-position-model goal, taken here rather than adding a third parallel literal.
- **Report-only, not blocking:** ground rule 4 (a new axis is report-only until green or every
  divergence is catalogued). 4 of 5 axes are green over 13; the wiretype pass surfaced
  **F-0027** (`rust-nostd` cannot §7.3-skip an array/fp64 field `probe-union` never declares —
  sofabgen provisions the no-std corelib's cargo features from the schema's *used* wire types).
  Primary attribution **generator (G-0017)**, corelib-rs-no-std implicated. The pass is not
  promoted to blocking and its vectors are not in `corpus/regression/` until the fix lands.
- **Result:** 130 union vectors; `probe` sweeps unchanged (still six blocking axes, green).
  `replay.yml` unchanged (the union pass is report-only, wired only into `sweep.sh`).

### 2026-07-22b — Dart added as the 11th corelib / 13th driver (roster 12→13)
- **PLAN says:** `drivers/` lists c/rust/go/java/python + cpp/cs/ts/zig (PLAN §11);
  onboarding a new language follows the §13 checklist.
- **Change:** `drivers/dart/` added (crucible#77 / generator#211, sofabgen's 10th
  language target). Roster is now **13 drivers / 11 corelibs**. Registered in every
  suite: `run.sh` (seeds/regression/cross-encode/union), `run-limits.sh` (heap
  roster), `engine/structured/sweep_run.py` (structural sweep), `materialize.sh`
  (element-access). No PLAN revision — this is the §13 checklist executed; PLAN's
  "N drivers" abstraction is unchanged.
- **Why it slots in cleanly:** the schema-agnostic round-trip form means the replay
  driver needs zero per-field code; the generated `Probe.tryDecode → DecodeStatus`
  maps 1:1 to `A`/`I`/`R`/`L`. Only the materialized oracle needs schema knowledge,
  supplied by a build-time-generated walker (AOT Dart has no `dart:mirrors`).
- **AOT, never JIT** — the suite runs the native `dart compile exe` binary, not
  `dart run`/VM (operator constraint).
- **CI:** the gates invoke the scripts (which carry Dart), so **no per-gate edit**;
  the CI image already installs the Dart SDK (`.devcontainer/Dockerfile`), so it only
  needs the standing one-time `image.yml` rebuild to carry it into `replay`/`nightly`.
- **Result:** all suites green — seeds 6×13, regression 73×13, cross-encode 75×13,
  union 11×13, limit mode (arr/str/blb) 10-heap-driver roster, structural sweep
  (5 blocking axes), materialized 75×13. No
  Dart-attributable finding. (One Crucible-side walker bug found+fixed during
  Stage 4; one toolchain-bump side-result: F-0025 now resolved on the CI build.)

### 2026-07-22a — bootstrap installs the latest sofabgen *CI build*, not the latest *release*
- **PLAN/prior as-built:** `scripts/bootstrap.sh` installed the latest published
  sofabgen **release** binary (checksum-verified) — see the `bootstrap.sh` row above
  as it was before this entry.
- **Change:** bootstrap now installs the binary the generator's `ci.yml` attaches to
  its latest **green run on `main`** (still sha256-verified, via the `.sha256` shipped
  in the same artifact). The tagged-release path is preserved but demoted to an
  explicit opt-in (`SOFABGEN_VERSION=vX.Y.Z`); it is also the **loud fallback** when no
  cross-repo token is present or the artifact is missing, so the tree never wedges and
  every run says which build it used.
- **Why:** the release cadence lagged behind merged generator work. The trigger was
  **Dart** (crucible#77): `corelib-dart` + the `dart` backend (generator#211) landed on
  generator `main` and CI began attaching a `dart`-capable `sofabgen` (target list now
  `…|dart|…`) and a `generated-dart` artifact — but no *release* carried it yet. Pulling
  the CI build lets Crucible exercise the newest family members as they merge, which is
  the whole point of a conformance fuzzer, without pinning to an *unmerged* PR (rejected
  — that would violate the "never lie about what it compiled" invariant).
- **Cost / caveat:** workflow-run artifacts are not anonymously downloadable, so CI needs
  a PAT secret (`SOFABGEN_TOKEN`, `actions:read` on `sofa-buffers/generator`) — wired into
  `replay.yml`/`nightly.yml`; absent it, CI degrades loudly to the latest release. CI
  builds carry a pseudo-version (`0.0.0-<ts>-<sha>`) rather than a semver tag.

### 2026-07-08a — Phase 1 used a minimal `probe` schema (RESOLVED in Phase 3)
- **PLAN says:** the fuzzed message is the "full scale" message (every width,
  arrays, nested structs, unions, unicode) — PLAN §13/§14.
- **Phase 1–2:** shipped a 4-field `probe` (u32/i32/fp32/string) to prove the
  loop, driver ABI, canonical form, and comparator without the full canonical-form
  surface area.
- **Resolved (Phase 3):** `schema/probe.sofab.yaml` is now the full-scale message
  (8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays,
  string array). The switch to the round-trip canonical form (decision
  2026-07-08) made this a **schema+seeds-only change with zero driver edits** —
  the drivers reference no fields. Loop green across all 12 drivers on 6
  full-scale seeds. Kept the message key `probe` so generated type names are
  stable. Unions are the one full-scale feature not in this message (the family's
  full-scale example has none) — **covered separately** via
  `schema/probe-union.sofab.yaml` + `scripts/run-union.sh` rather than folded into
  `probe` (keeping the main message's type names stable). The schema-agnostic
  round-trip form pays off again: pointing the oracles at the union schema needs
  only a rebuild, no driver edits. All 12 backends generate + agree on every
  variant and the one-of/unknown-member edge cases — green, no finding.

### 2026-07-08b — absent/default/value collapsed to two states
- **PLAN says:** canonical form distinguishes *absent* / *present-but-default* /
  *value* (PLAN §7).
- **Reality:** the C object API and Go visitor API both materialize values with
  the schema default for omitted fields; on the sparse-canonical wire
  `absent == default`, so the two are equal and indistinguishable. Canonical form
  emits the value (default when absent).
- **Why:** both Phase-1 decoders are value-materializing; neither tracks presence.
- **Impact:** documented in `oracle/canonical.md`. When a presence-tracking
  decoder joins, the canonical form gains a presence marker and the comparator
  learns cross-model compatibility. No PLAN revision — PLAN §7's three-way
  distinction remains the target for models that support it.

### 2026-07-08c — C libFuzzer pacemaker not built in the bare workspace
- **PLAN says:** C pacemaker built with libFuzzer + sanitizers (PLAN §3, §12).
- **Reality:** the bare workspace has gcc but no clang, so only the gcc replay
  driver (with ASan/UBSan) is built/verified here. The libFuzzer front-end exists
  in `driver.c` behind `CRUCIBLE_LIBFUZZER` and builds in the devcontainer.
- **Why:** libFuzzer is a clang/LLVM feature; the devcontainer ships clang.
- **Impact:** none to the differential loop (which runs on the replay drivers).
  Coverage-guided pacemaker runs live in the devcontainer/CI.

### 2026-07-13a — canonical verdict is three-valued (`A`/`I`/`R`), not binary
- **PLAN says:** the canonical form's verdict axis is accept-vs-reject (PLAN §6/§7
  frame decode as a binary outcome).
- **Reality:** MESSAGE_SPEC §7 (finish-less, documentation PR #12) makes decode
  three-valued — COMPLETE / **INCOMPLETE** / INVALID — where INCOMPLETE (truncated
  but well-formed-so-far) is an explicit non-error outcome. The canonical form
  gained a third line `I` (`oracle/canonical.md` v2), the comparator a third
  verdict + a soft `incomplete_value` axis, and the driver contract an `I`
  mapping.
- **Why:** collapsing INCOMPLETE into accept (`A`) or reject (`R`) is exactly the
  F-0001 bug; the loop cannot verify the family's convergence on INCOMPLETE
  without a distinct verdict for it.
- **Impact:** verdict comparison now ranges over `A`/`I`/`R` (all hard). Drivers
  emit `I` only after their corelib exposes INCOMPLETE (generator#86 +
  per-corelib issues); until then their `A`/`R` on a truncated seed is a real
  verdict divergence. No PLAN revision needed — this refines §7's outcome model to
  match the now-settled spec. Verification: crucible#8.

### Pacemaker (as built)

`scripts/fuzz.sh` builds the C driver's `CRUCIBLE_LIBFUZZER` entry with clang
(`-fsanitize=fuzzer,address,undefined`) and runs it, seeded from `corpus/seeds` +
`corpus/interesting` + the findings reproducers; new coverage-increasing inputs
grow `corpus/interesting/`, crashes land in `corpus/crashes/`. Measured ~41k
exec/s, ~1M runs in 26s. It only decodes (coverage over the C decoder); the
discovered inputs then go through the differential loop
(`CORPUS=corpus/interesting ./scripts/run.sh`) where decode+re-encode across all
12 drivers finds the divergences. On its **first** run over 309 discovered inputs
it produced F-0003 (2 crashes) and a large divergence cluster dominated by F-0004
(string UTF-8) and F-0001 (truncated input) — findings 8 hand-seeds never reached.

Needs clang + `libclang-rt-dev` (in the devcontainer image); the comparator
(`oracle/comparator.py`) is **crash-isolating** — a driver that dies mid-stream is
reported as `[CRASH] driver X on input N`, not a bare harness abort, so the
pipeline survives a crashing implementation.

### Clustering (as built)

`oracle/cluster.py` (`CLUSTER=1 ./scripts/run.sh`) reduces the divergence firehose
to root causes: for each divergent input it partitions the drivers into
equivalence classes by identical output, drops the exact bytes, and keys the
cluster by the *shape* (which driver-set landed in each class, with its verdict).
Inputs sharing a shape share a root cause; clusters rank by size with a minimal
representative. It recovers past crashes (re-runs a crashed driver on the
remaining inputs). First run: 256 divergences → 47 clusters, top 12 ≈ 208, mapping
to F-0001/F-0004/F-0005 (+ the F-0003 crash cluster). Snapshot +
finding-mapping in `results/CLUSTERS.md`.

## First finding

The Phase-1 loop found **F-0001** on its first run: a truncated trailing varint
(`80`, `ff ff ff`). Phase 2 grew it to a **7-accept vs 5-reject camp split** — the
C/C++/Rust/Java/C# camp (c-cpp, cpp, c-cpp wrapper, rs, rs-no-std, java, cs)
accepts it as the all-defaults message; **four independent lineages — Go, Python
(cython and pure), TypeScript, and Zig — reject it**. Real, hand-verified against
all twelve drivers. Notably Zig (a systems language) rejects while C/C++/Rust
accept, so the split is per-decoder-design, not systems-vs-managed. Four
unrelated implementations rejecting is strong evidence the lenient camp is wrong —
exactly the pressure the PLAN §8 spec decision needs.
See `results/FINDINGS.md` and `findings/F-0001-truncated-trailing-varint/`.

## Spec decisions (adopted MESSAGE_SPEC clauses)
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
