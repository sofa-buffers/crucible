# Crucible

**Differential fuzzing for the SofaBuffers wire format.** Crucible feeds the same
bytes to every corelib implementation and fails when they **disagree** — one
accepts what another rejects, or two decode the same bytes to different values.
The oracle is *disagreement between implementations*, not a crash; sanitizers are
a second net.

Sibling to [`arena`](../arena) (which measures speed/size). Crucible reuses
arena's proven shape — vendor every corelib, one uniform per-language driver
contract, one schema, one runner — but builds the corelibs **instrumented**
(sanitizers + coverage) instead of optimized, which is why it lives in its own
repo. See [`docs/PLAN.md`](docs/PLAN.md) for the full design and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for what is actually built.

## Quick start

```sh
./scripts/bootstrap.sh     # vendor corelibs + sofabgen (idempotent)
./scripts/run.sh           # build every driver, run the differential over the seed corpus
```

`run.sh` builds each `drivers/<lang>/` replay driver, feeds a corpus through all
of them, and reports any divergence (the green regression gate on
`corpus/seeds`). It is **crash-isolating**: a driver that dies mid-stream is
reported as `[CRASH] driver X on input N` and the run keeps comparing the
survivors.

```sh
./scripts/fuzz.sh                              # C pacemaker (libFuzzer/clang): grow corpus/interesting
CORPUS=corpus/interesting ./scripts/run.sh     # replay what the pacemaker found through all drivers
CLUSTER=1 ./scripts/run.sh                      # reduce divergences to root-cause clusters
```

One coverage **pacemaker** (C, libFuzzer + ASan/UBSan) drives exploration; every
interesting input is replayed through all N drivers and compared. C is the motor,
**not** a privileged oracle — its output is diffed like everyone else's. The
pacemaker needs clang (in `.devcontainer/`); the replay drivers build with gcc.

## Status

**Phases 1–2 complete, Phase 3 in progress.** The differential loop runs green
across **12 drivers / 10 corelibs** — C (pacemaker), Go, Rust-std, Rust-no-std,
C++, C++/c-cpp, Python-Cython, Python-pure, Java, TypeScript, C#, and Zig — over
the **full-scale `probe` schema** (8 scalar widths, fp32/fp64, string, blob,
numeric + nested-fp + string arrays).

Phase 3 highlights:

- **Canonical form v1 = round-trip re-encoding.** Each driver emits
  `A <hex(encode(decode(input)))>` on accept, `R <class>` on reject. This makes
  drivers **schema-agnostic** (no per-field code — scaling the schema needs zero
  driver edits) and folds in the round-trip oracle for free.
- **C pacemaker active** (~41k exec/s, libFuzzer) with **auto-clustering** of the
  divergence firehose into root causes (`oracle/cluster.py`).

Remaining Phase 3 / Phase 4 work (structure-aware mutator selection, cross-encode
oracle, finer reject-class taxonomy, CI) is tracked in [`TODO.md`](TODO.md);
roadmap in [`docs/PLAN.md`](docs/PLAN.md) §12.

## Findings

The oracle has already caught real disagreements — reproducers in `findings/`,
catalog in [`results/FINDINGS.md`](results/FINDINGS.md), codegen defects in
[`docs/SOFABGEN.md`](docs/SOFABGEN.md). Fixes live in the **owning repos**;
Crucible is the catalog + acceptance test.

| finding | what |
|---|---|
| F-0001 | truncated input: lenient camp (C/C++/Rust/Java/C#) vs strict camp (Go/Py/TS/Zig) — spec §7 |
| F-0004 | invalid UTF-8 in a string: four behaviors driven by the string type — spec §8 |
| F-0002 | `corelib-c-cpp` encoder left-shifts a negative value (UB) |
| F-0003 | Rust array-fill OOB → panic (crash/DoS) — fixed upstream |
| F-0005 | `corelib-cpp` accepts malformed messages the rest of the family rejects |

## Layout

| path | what |
|---|---|
| `docs/PLAN.md` | the master plan — everything is built from here |
| `docs/STATUS.md` | current-state snapshot — start here for orientation |
| `docs/ARCHITECTURE.md` | living as-built architecture + deviations from PLAN |
| `schema/` | the fuzzed message (single source of truth) |
| `drivers/<lang>/` | per-language replay driver + coverage front-end (12 drivers) |
| `drivers/common/` | the driver contract |
| `oracle/` | canonical form, comparator, allowed-divergence policy, clustering |
| `engine/` | structure-aware mutator design (TLV/varint grammar) |
| `corpus/` | seeds, accumulated inputs, minimized crashes |
| `findings/` | minimized, reproducible divergences (F-0001 … F-0005) |
| `results/` | findings catalog + cluster inventory |
| `scripts/` | bootstrap, differential run, fuzz pacemaker |
| `.devcontainer/` | fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, …) |
