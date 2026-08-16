# CI — continuous differential fuzzing (Phase 4)

Three GitHub Actions workflows (`.github/workflows/`) turn Crucible from
"a differential fuzzer someone runs by hand" into one that **keeps** catching drift
as the corelibs churn. See PLAN §10/§12.

| workflow | trigger | blocking? | what it does |
|---|---|---|---|
| [`image.yml`](../.github/workflows/image.yml) | `.devcontainer/Dockerfile` change · manual | — | build the 13-toolchain image (incl. the Dart SDK), push to GHCR |
| [`replay.yml`](../.github/workflows/replay.yml) | every push to `main` · every PR | **yes** | build all drivers, run the eight **green** gates + the two opt-in streaming gates |
| [`nightly.yml`](../.github/workflows/nightly.yml) | 03:00 UTC daily · manual | no | fuzz → grow corpus → cluster → upload artifacts |

## The image (`image.yml`) — the linchpin

A full run needs every language toolchain **and** its fuzzing framework
(clang/libFuzzer, cargo-fuzz, go, dotnet+SharpFuzz, zig, node+Jazzer.js, jdk+maven,
python+atheris/cython) — that is `.devcontainer/Dockerfile`, ~15 min to build. We
build it **once** here and push `ghcr.io/<owner>/crucible-ci:latest`; the replay and
nightly jobs then start in that prebuilt container in seconds instead of
re-installing toolchains every run. The image rebuilds only when the Dockerfile
changes (or on manual dispatch), with layer caching via `type=gha`.

### One-time setup

1. **Seed the image:** Actions → **image** → *Run workflow* (on `main`). This
   publishes `crucible-ci:latest` to the org's GHCR.
2. **Package visibility:** leave it private (the jobs authenticate with the built-in
   `GITHUB_TOKEN` via `packages: read`) or make it public. If private, ensure the
   package is *linked* to this repo so the token can pull it.
3. After that, `replay` runs on every push/PR and `nightly` runs on its schedule.

## The replay gate (`replay.yml`) — blocking

Two jobs. **`catalog`** runs first and needs no drivers at all — it asserts that
`results/FINDINGS.md` and its write-ups declare the same state:

```sh
python3 scripts/check-catalog.py   # catalog row <-> findings/<id>/NOTES.md, and the G-00NN table <-> its sections
```

`findings/<id>/NOTES.md` **owns** everything about a finding; `results/FINDINGS.md` is a
pure index. The check asserts the state token (✅ / 🔴 / ⚪) matches between the two and
that index and folders cover the same set. Added 2026-08-03 after all three non-owning
representations were found stale at once — it exists because intending to keep them in
sync demonstrably did not.

**`differential`** bootstraps the corelibs (their `main` tips) + sofabgen, builds every
replay driver, and runs the **green** oracles in sequence; any divergence fails the
job. All ten, in the order the workflow runs them:

```sh
./scripts/bootstrap.sh   # always: latest sofabgen CI build (checksum-verified) + corelibs, both @ FAMILY_BRANCH
./scripts/run.sh                            # seed differential            (corpus/seeds)
CORPUS=corpus/regression ./scripts/run.sh   # resolved-findings gate       (corpus/regression)
CORPUS=corpus/conformance ./scripts/run.sh  # §2/§3 canonicality seeds     (corpus/conformance)
REGEN=0 ./scripts/cross-encode.sh           # cross-encode / structured    (corpus/structured)
./scripts/run-union.sh                      # union suite                  (corpus/union)
./scripts/run-limits.sh                     # limit mode                   (corpus/limits)
./scripts/sweep.sh                          # structural sweep, 12 blocking axes
./scripts/materialize.sh                    # materialized-value oracle    (corpus/structured)
./scripts/run-chunked.sh                    # chunk invariance   (opt-in roster; skips loudly)
./scripts/run-encode.sh                     # encode invariance  (opt-in roster; skips loudly)
```

- **Corelibs pinned to `main`** on purpose: Crucible is a *conformance* fuzzer, so a
  red gate on an upstream regression is exactly the signal we want — it's how we
  work by hand.
- **Open findings diverge by design** (F-0004, F-0017) and are kept OUT of
  these green corpora — they live in `findings/` until fixed. When a fix lands, its
  reproducer converges and can be promoted into a green gate (as F-0008/F-0009 and
  the rest of the resolved findings already were — see `corpus/regression/`).
- The comparator's **per-driver timeout** keeps a hanging driver from wedging the
  job (reported as a `[TIMEOUT]` finding, so a regressed DoS still fails the gate).

## The nightly (`nightly.yml`) — continuous discovery, non-blocking

The C pacemaker (libFuzzer + the structure-aware mutator, `engine/mutator/`) grows
`corpus/interesting`; that grown corpus is replayed through the whole roster and
auto-clustered by root cause. Crashes, the interesting corpus, and
`results/CLUSTERS.md` are uploaded as artifacts. The corpus is `actions/cache`d so
coverage **compounds** night over night.

Non-blocking by design: a fresh divergence is expected signal, not a build break —
triage stays human (the corelibs are other repos; cross-repo auto-filing is a later
step). `FUZZ_TIME` (default 1800s) is overridable via manual dispatch.

## Follow-ups

- **Build reuse:** `replay` runs its gates (seeds / regression / conformance /
  structured via `cross-encode.sh` / union / limits / structural sweep / materialized)
  as separate steps, rebuilding the whole roster each time — so the gate pays the build
  once per step. A build-once → compare-many-corpora mode would cut it to one build.
  The two streaming gates (`run-chunked.sh`, `run-encode.sh`) do not add to that today:
  they exit before building while their opt-in roster is empty, and will pay one build
  each once the first driver lands.
- **Cross-repo auto-annotation:** have `nightly` open/annotate issues on the owning
  corelib/generator repos (needs a PAT with `issues:write`), instead of only
  uploading artifacts.
- **OSS-Fuzz:** the eventual home for continuous fuzzing (PLAN §12).
