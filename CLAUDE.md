# CLAUDE.md — agent entry point

This repo is **Crucible**: the differential fuzzing harness for the SofaBuffers
wire format. It feeds identical bytes to every corelib implementation and fails
when they **disagree** (accept-vs-reject, or decode to different values). The
oracle is *disagreement between implementations*, not a crash — sanitizers are
only a second net.

**Do not rely on this file for the details — read the sources of truth:**

| read | for |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | the authoritative master plan: mission, scope, architecture, driver ABI, oracles, the add-a-corelib checklist, roadmap. **Everything is built from here.** |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | the living as-built architecture + component status + decision log + **deviations from PLAN**. Read this to know what actually exists today. |
| [`oracle/canonical.md`](oracle/canonical.md) | the canonical comparison form every driver must emit (once written). |
| [`oracle/policy.yaml`](oracle/policy.yaml) | which divergences are legal vs bugs; each entry cites `MESSAGE_SPEC.md`. |
| [`drivers/common/`](drivers/common/) | the driver contract every `drivers/<lang>/` obeys. |
| [`docs/SOFABGEN.md`](docs/SOFABGEN.md) | generated-code weakness log — codegen defects to fix in `sofabgen`, not work around silently. |
| `drivers/<lang>/{meta,build.sh,driver.*}` | per-language ground truth for build flags, framework, generation. |

Everything below is only what is **not** written in those files.

## Prime directive: keep PLAN and ARCHITECTURE honest

- `PLAN.md` is the **intended** design and stays stable. Do not edit it to match
  code that drifted.
- `ARCHITECTURE.md` is the **as-built** design. Any change that alters a
  component boundary, a contract, a build flag, or a data format updates
  `ARCHITECTURE.md` in the *same* change. When behavior deviates from `PLAN.md`,
  add a dated entry to its "Deviations from PLAN" section — the deviation log is
  the point, not an afterthought.

## Invariants with multiple sync points

- **Crucible builds corelibs instrumented, arena builds them optimized.** These
  are opposite configurations of the *same* code. Never copy a build flag from
  arena's `languages/<lang>/setup.sh` into a `drivers/<lang>/build.sh` without
  re-checking it — arena optimizes for speed, Crucible for sanitizer/coverage
  coverage.
- **The driver contract lives in three places at once:** the prose in
  `drivers/common/`, the canonical grammar in `oracle/canonical.md`, and the
  comparator that parses it in `oracle/`. A change to the wire between engine and
  drivers, or to the canonical output form, must update all three together or the
  comparator silently mis-reads a driver as "divergent."
- **`schema/` is the single source of truth for the fuzzed message** (arena's
  `STATE.md`/`state.json` pattern). Drivers are generated from it via `sofabgen`
  where possible; a schema change regenerates every driver.
- **`oracle/policy.yaml` ↔ `MESSAGE_SPEC.md`.** Every allowed-divergence entry
  cites a spec clause (or records that none exists yet). A policy entry with no
  spec basis is a spec hole to file upstream, not a silent exception.

## Checklists

The canonical **add-a-new-corelib** checklist is in
[`docs/PLAN.md`](docs/PLAN.md) §13 — follow it there (it is the reason the plan
exists), then record the new driver's quirks in `ARCHITECTURE.md`.

## Gotchas

- **No toolchains in the bare workspace** — work inside `.devcontainer/`, which
  carries the fuzzing frameworks (libFuzzer, cargo-fuzz, Jazzer, Atheris,
  SharpFuzz, Jazzer.js). This mirrors the corelib repos' setup.
- **Persistent-mode drivers, never process-per-input.** The generator's
  `encode`/`decode` CLI is process-per-input and emits general JSON — it is *not*
  the fuzz driver. Reusing it caps throughput ~1000× and blurs
  absent/default/value. See PLAN §7.
- **C is the coverage pacemaker but not a privileged oracle** — its output is
  compared like every other driver's. Don't special-case it in the comparator.
- **Findings must be minimized and reproducible** — a raw crashing input with no
  minimization and no "who disagreed" tag is not a finding, it's noise. See
  PLAN §10.
- **Zig fuzzing is immature** (Zig 0.16); the Zig driver may need libFuzzer via C
  interop rather than built-in fuzzing. Confirm before committing the approach.
- **Generated decode may not surface the verdict.** The Rust `Probe::decode` is
  infallible (drops `feed`'s `Result`), so `drivers/rust/` reads the corelib's
  real accept/reject from a second `IStream::feed` pass. When adding a language,
  check whether its generated decode returns the error; if not, capture the
  corelib's real result and log the codegen gap in `docs/SOFABGEN.md`.
- **A driver builds against multiple corelibs via one source.** `drivers/rust/`
  has one `driver.rs` for both `corelib-rs` and `corelib-rs-no-std`, selected by
  `build.sh <variant>` and registered as two drivers in `run.sh`. Mirror this if
  another language ships std/embedded corelib pairs (e.g. cpp / c-cpp).

## Status

Pre-implementation. The three documents above exist; no code yet. Phase 0
(skeleton) and Phase 1 (C + Go two-language differential loop) are the next
steps — see `docs/PLAN.md` §12.
