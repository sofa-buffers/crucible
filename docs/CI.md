# CI — continuous differential fuzzing (Phase 4)

Three GitHub Actions workflows (`.github/workflows/`) turn Crucible from
"a differential fuzzer someone runs by hand" into one that **keeps** catching drift
as the corelibs churn. See PLAN §10/§12.

| workflow | trigger | blocking? | what it does |
|---|---|---|---|
| [`image.yml`](../.github/workflows/image.yml) | `.devcontainer/Dockerfile` change · manual | — | build the 14-toolchain image (incl. the Dart SDK and the Kotlin toolchain — Gradle, kotlinc and Kotlin/Native), push to GHCR |
| [`replay.yml`](../.github/workflows/replay.yml) | every push to `main` · every PR | **yes** | the catalog + participation checks; one `prepare` job (bootstrap + the prerequisite checks), then six parallel jobs that build the drivers and run every **green** gate |
| [`nightly.yml`](../.github/workflows/nightly.yml) | 02:42 UTC daily (dispatched late; see below) · manual | no | two jobs: `fuzz` (grow the corpus, upload it) → `cluster` (cluster it against the baselines, upload the report) |

## The image (`image.yml`) — the linchpin

A full run needs every language toolchain **and** its fuzzing framework
(clang/libFuzzer, cargo-fuzz, go, dotnet+SharpFuzz, zig, node+Jazzer.js, jdk+maven,
jdk+gradle/kotlinc/kotlin-native, python+atheris/cython) — that is `.devcontainer/Dockerfile`, ~15 min to build. We
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

Eight jobs. **`catalog`** needs no drivers at all and runs beside the others. It carries these checks: `scripts/driver-audit.sh`, the per-driver participation ledger (every roster entry must declare what the gates need to place it), the static half of `scripts/check-family-copies.py` (every copy of family logic listed with a verdict, every materialized walker naming every schema kind), the offline sofabgen-pick rule (`check-sofabgen-pick.py`), `check-nightly-steps.py --lint` (every `continue-on-error` step of the nightly carries an `id`, see below), and `check-catalog.py`, which asserts that
`results/FINDINGS.md` and its write-ups declare the same state:

```sh
python3 scripts/check-catalog.py   # index is current + every closed finding declares its guard
python3 scripts/gen-findings.py     # ... and this is what regenerates it
```

`findings/<id>/NOTES.md` **owns** everything about a finding, and since 2026-08-16
`results/FINDINGS.md` is **generated** from those write-ups — so the index cannot disagree
with them about a state, a pairing or a ticket, only be stale. The check regenerates and
compares, and additionally asserts that every closed finding declares the gate that
re-checks it. Added 2026-08-03 after all three non-owning
representations were found stale at once — it exists because intending to keep them in
sync demonstrably did not.

**`prepare`** bootstraps the corelibs (their `main` tips) + sofabgen **once**, runs the
checks without which every other job's result would mean nothing, and hands `vendor/` +
`tools/sofabgen` to the other jobs as an artifact (a tarball: an artifact drops file modes;
`.github/actions/prepared-workspace` unpacks it). One bootstrap for all jobs is a correctness
rule, not a saving: bootstrapping per job would let a push to a corelib or the generator
between two job starts give two jobs two different families.

```sh
./scripts/bootstrap.sh   # always: latest sofabgen CI build (checksum-verified) + corelibs, both @ FAMILY_BRANCH
python3 scripts/check-oracle-verdicts.py    # the comparator against stub drivers: each canonical verdict still
                                            #   does what oracle/canonical.md says (incl. the per-line `E`)
python3 scripts/check-kotlin-version.py     # the image's kotlinc vs the corelib's klibs (crucible#244) — the one silent mismatch
python3 scripts/check-family-copies.py      # C anchor tags (needs vendor/): the materialized gates' anchor
```

Then six jobs run **in parallel**, each in the same image, each building the roster it needs;
any divergence fails its job:

| job | gates |
|---|---|
| `codegen` | `python3 scripts/check-ref-codegen.py` — `$ref` codegen equivalence, schema/ref-forms x 11 targets (sofabgen only, no driver build; cells checked in parallel) |
| `roundtrip` | seed differential (`run.sh`, and inside it `check-encode-bounds.py`: no encode-bound opt-out in any build recipe, #656); `CORPUS=corpus/regression` and `CORPUS=corpus/conformance` `run.sh`; `REGEN=0 cross-encode.sh`; `sweep.sh` (12 blocking axes + the union pass) |
| `streams` | `run-chunked.sh` and `--modes chunk` over corpus/regression; `run-encode-fail.sh` (the `E` verdict, for real); `run-encode.sh`; `run-reuse.sh`; `materialize.sh` over corpus/structured and corpus/regression |
| `schemas` | `run-union.sh`; `materialize.sh` over probe-union; `run-union-deep.sh` (differential + conformance + chunk + encode); `materialize.sh` over probe-union-deep; `run-limits.sh` |
| `ref-roundtrip` | `run-ref.sh --part 1` — probe-ref vs its inline twin: differential + conformance + same answers |
| `ref-values` | `run-ref.sh --part 2` — the same pair: materialized values, chunk + encode invariance |

The same commands, run locally in one go:

```sh
./scripts/run.sh                            # seed differential            (corpus/seeds)
CORPUS=corpus/regression ./scripts/run.sh   # resolved-findings gate       (corpus/regression)
CORPUS=corpus/conformance ./scripts/run.sh  # §2/§3 canonicality seeds     (corpus/conformance)
REGEN=0 ./scripts/cross-encode.sh           # cross-encode / structured    (corpus/structured)
./scripts/sweep.sh                          # structural sweep, 12 blocking axes
./scripts/run-union.sh                      # union suite                  (corpus/union)
./scripts/run-union-deep.sh                 # deep union suite: differential + conformance + chunk + encode (corpus/union-deep)
python3 scripts/check-ref-codegen.py        # $ref codegen equivalence: schema/ref-forms x 11 targets (sofabgen only, no build)
./scripts/run-ref.sh                        # $ref suite: probe-ref vs its inline twin — differential + conformance + same answers, materialized values, chunk + encode (corpus/ref)
./scripts/run-limits.sh                     # limit mode                   (corpus/limits)
./scripts/materialize.sh                    # materialized-value oracle    (corpus/structured)
CORPUS=corpus/regression ./scripts/materialize.sh   # ...and over the findings corpus (values the round trip cannot see)
SCHEMA=schema/probe-union.sofab.yaml ./scripts/materialize.sh   # ...and over a union schema (the HELD option, read through the API)
SCHEMA=schema/probe-union-deep.sofab.yaml CORPUS=corpus/union-deep ./scripts/materialize.sh   # ...and the deep one (238 inputs)
./scripts/run-chunked.sh                    # chunk invariance   (roster derived from meta)
CORPUS=corpus/regression ./scripts/run-chunked.sh --modes chunk   # ...and over the findings corpus
./scripts/run-encode.sh                     # encode invariance  (roster derived from meta)
./scripts/run-reuse.sh                      # reuse invariance   (roster derived from meta; corpus/regression primed by corpus/structured)
./scripts/run-encode-fail.sh                # destination failure: the `E` verdict, for real
```

- **`SKIP_BUILD=1` and `RESTORE=0` in every driver job.** `scripts/roster.sh build` reuses
  the previous roster build when nothing it depends on changed — every variable a
  `build.sh` / `materialize_gen.py` reads, the content of the schema (+ its `*.defs.yaml`)
  and of the materialized table, the checkout, sofabgen and each corelib's commit — so
  consecutive steps on one schema stop rebuilding twenty drivers; a schema switch changes
  the stamp and always rebuilds, so a stale binary is never reused. `RESTORE=0` drops the
  "rebuild back to probe" that `cross-encode.sh`, `sweep.sh`, `run-union-deep.sh` and
  `run-ref.sh` end with: in a separate job nothing runs on those binaries afterwards.
  Locally both stay off unless set.
- **No gate waits for another driver job.** A seed differential as a "smoke test" in front
  would add a full roster build to the critical path while proving nothing the jobs do not
  prove themselves (each builds and fails fast). `catalog` stays independent too: a stale
  index does not make a differential result wrong.
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

A **union engine** (block path and, separately, the feed/finish streaming target) runs the same pacemaker on `schema/probe-union-deep.sofab.yaml`
(`FUZZ_SCHEMA` / `FUZZ_CORPUS` / `FUZZ_SEEDS` of `scripts/fuzz.sh`), seeded from
`corpus/union-deep`, into its **own** corpus `corpus/interesting-union`. Every other engine fuzzes
`probe`, which has no union, so without it the union code of every backend was reached only by
hand-written vectors. That corpus has its own cache (its key deliberately does **not** start with
`crucible-corpus-`, which would match the probe corpus's restore prefix), is clustered against a
roster built for the union schema, and has its own baseline, `results/known-clusters-union.txt`.

Non-blocking by design: a fresh divergence is expected signal, not a build break —
triage stays human (the corelibs are other repos; cross-repo auto-filing is a later
step). `FUZZ_TIME` (default 1800s) is overridable via manual dispatch.

**A non-blocking step that fails turns the run red at the end.** The fuzz engines and both
cluster steps are `continue-on-error` — a Go panic is a finding to upload, not a reason to stop
the job — and GitHub then reports a failed one as a success, in the UI and in the jobs API. So
each of them carries an `id`, and the last step (`scripts/check-nightly-steps.py`, after the
artifact upload) reads `steps.<id>.outcome`: every failure becomes an error annotation, a row in
the job summary, and a red run. The red run is the signal; it still blocks nothing. A new
`continue-on-error` step without an `id` fails the `catalog` job of `replay.yml`.

**`nightly.yml` is two jobs, and the second one is the oracle.** `fuzz` runs the eight
engines and uploads the grown corpus as `nightly-<run_id>`; `cluster` downloads that
artifact and runs both cluster steps, uploading its report as `nightly-clusters-<run_id>`.
They are separate jobs because they were one until 2026-10-13 and the fuzzing grew into the
whole ceiling: 38231657547 was cancelled at 2h0m45s with the probe cluster step 2 min in and
the union step not started, so that night produced a corpus and no verdict. Two consequences
worth knowing. **The corpus is uploaded before any oracle runs**, so a failure in `cluster`
cannot cost the night's fuzzing — and `cluster` takes it from the artifact rather than the
cache, so a missing upload fails it loudly instead of quietly clustering an empty checkout.
**Two artifacts, and the second one existing is the signal that the oracle ran** — `fuzz`
deliberately does not ship `results/CLUSTERS.md`, because shipping the checked-out copy made
a dead cluster step look like a report.

**A cancelled job reports nothing.** `check-nightly-steps.py` runs as the last step of each
job and turns a failed non-blocking step red, but a cancellation kills that step too, so the
run reads as `cancelled` rather than red — the 10-12 failure was invisible twice over. The
`timeout-minutes` are set with headroom against the measured wall clock for that reason
(`fuzz` 150 against ~117 min measured, `cluster` 120), but the gap is not a monitor: nothing
currently notices a cancellation. That is still open (`TODO.md`, CI / infra).

**The cron time is a request, not a promise.** Scheduled runs queue on GitHub's
shared scheduler and are dispatched under load, so "nightly" regularly arrives in the
morning: on an unchanged `0 3 * * *` the job started between +0.5 h and +4.5 h late
depending on the week, with two outliers past +10 h. The cron therefore sits at `:42`
rather than the top of the hour, which is the most contended slot — a mitigation, not
a fix. Two consequences when reading a run: its wall-clock start says nothing about
the fuzz budget (that is `FUZZ_TIME`), and it bootstraps the family at whatever `main`
was when it *started*, so a fix that lands during the run is not in it.

## Follow-ups

- **Build reuse:** `replay` runs its gates (seeds / regression / conformance /
  structured via `cross-encode.sh` / union / limits / structural sweep / materialized)
  as separate steps, rebuilding the whole roster each time — so the gate pays the build
  once per step. A build-once → compare-many-corpora mode would cut it to one build.
  The two streaming gates (`run-chunked.sh`, `run-encode.sh`) each pay a build too: since
  2026-08-16 they derive their participants from the roster + `meta` (`roster.sh caps`),
  and both run a full roster — fourteen and fifteen drivers.
- **Cross-repo auto-annotation:** have `nightly` open/annotate issues on the owning
  corelib/generator repos (needs a PAT with `issues:write`), instead of only
  uploading artifacts.
- **OSS-Fuzz:** the eventual home for continuous fuzzing (PLAN §12).
