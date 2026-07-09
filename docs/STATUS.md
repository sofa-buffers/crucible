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

## Current state
- **Phase 1–2 done:** 12 drivers / 10 corelibs green (c, go, rust-std, rust-nostd,
  cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig).
- **Phase 3 in progress:** canonical form v1 = **round-trip re-encoding**
  (`A <hex(encode(decode(input)))>` — drivers are schema-agnostic, folds in the
  round-trip oracle); schema scaled to the **full-scale** message; **C pacemaker
  active** (~41k exec/s); comparator is **crash-isolating**; **auto-clustering**.
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
(upstream PRs merged); **F-0003's crash is fixed but morphed** into an untracked
verdict divergence (see below); **F-0001 and F-0004 still diverge** — expected,
they wait on the still-open epics generator#86 / #85 (the "2 issues still open").

| finding | what | tracked in / status |
|---|---|---|
| F-0001 | truncated input: lenient (C/C++/Rust/Java/C#) vs strict (Go/Py/TS/Zig) | spec §7 → epic **generator#86** — **still diverges (open)** |
| F-0004 | invalid UTF-8 in a string: 4 behaviors, driven by the string type | spec §8 → epic **generator#85** — **still diverges (open)** |
| F-0002 | corelib-c-cpp encoder left-shifts a negative value (UB) | **corelib-c-cpp#70** merged — ✅ **resolved** |
| F-0003 | Rust array-fill OOB → panic (crash/DoS) | **generator#87** merged — ✅ crash fixed; ⚠️ but rust-std/nostd now *accept* an over-long array 10 others reject (verdict divergence, untracked) |
| F-0005 | corelib-cpp accepts malformed msgs the family rejects | **corelib-cpp#22** closed — ✅ **resolved** |
| G-0001,3,4,5,6 | codegen weaknesses (infallible Rust/C++ decode, no-std string handling, Go bytes import) | **all fixed in sofabgen 0.15.1** (PRs #88/#92/#93/#89/#90) — see docs/SOFABGEN.md |
| G-0002 | Rust std vs no_std UTF-8 (intra-Rust) | generator#80/#91 — ✅ **fixed** (both empty on invalid); family-wide UTF-8 is F-0004 / #85 |

## Spec decisions (documentation repo, MESSAGE_SPEC.md)
- **§7** — decode is incremental; `feed` is three-valued COMPLETE/INCOMPLETE/INVALID;
  a `finish` turns still-INCOMPLETE → INVALID; a valid message is consumed exactly.
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
