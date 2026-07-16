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

## Current state
- **Phase 1–2 done:** 12 drivers / 10 corelibs green (c, go, rust-std, rust-nostd,
  cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig) — **all 12 green
  again as of 2026-07-15 on sofabgen 0.16.2** (the zig build break G-0010 is fixed;
  see the re-run notes below).
- **Phase 3 in progress:** canonical form v2 = **round-trip re-encoding** with a
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
- Remaining Phase 3 / Phase 4: see [`../TODO.md`](../TODO.md).

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

Net open now: **F-0004** only (§8 UTF-8, gen#85). F-0010 + F-0011 resolved.
| finding | what | tracked in / status |
|---|---|---|
| F-0001 | truncated input: lenient (C/C++/Rust/Java/C#) vs strict (Go/Py/TS/Zig) | spec §7 (finish-less); all 10 corelibs + all 12 drivers implement `I`. **✅ verified green 2026-07-13** — every driver emits `I` on the F-0001 seeds (0 divergences). Was 7-accept/5-reject. |
| F-0004 | invalid UTF-8 in a string: 4 behaviors, driven by the string type | spec §8 → epic **generator#85** — **still diverges (open)** |
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
- **G-0006 workaround** in `drivers/go/build.sh` injects a missing `bytes` import
  (remove once generator#84 lands).
- **Characterize a divergence with a minimal isolate**, not a raw fuzzer input — the
  coarse `invalid_msg` reject class conflated reasons (F-0004 was mischaracterized
  until isolated).
