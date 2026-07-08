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
./scripts/run.sh           # build C + Go drivers, run the differential loop
```

`run.sh` builds each `drivers/<lang>/` replay driver, feeds the seed corpus
through all of them, and reports any divergence.

## Status

**Phase 1** — a working two-language differential loop (C pacemaker + Go) over a
minimal `probe` schema, proving end-to-end divergence detection. Next: fill out
the remaining language drivers, then the structure-aware coverage engine. Roadmap
in [`docs/PLAN.md`](docs/PLAN.md) §12.

## Layout

| path | what |
|---|---|
| `docs/PLAN.md` | the master plan — everything is built from here |
| `docs/ARCHITECTURE.md` | living as-built architecture + deviations from PLAN |
| `schema/` | the fuzzed message (single source of truth) |
| `drivers/<lang>/` | per-language replay driver + coverage front-end |
| `drivers/common/` | the driver contract |
| `oracle/` | canonical form, comparator, allowed-divergence policy |
| `corpus/` | seeds, accumulated inputs, minimized crashes |
| `scripts/` | bootstrap + run |
| `.devcontainer/` | fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, …) |
