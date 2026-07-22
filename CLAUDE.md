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
| [`docs/STATUS.md`](docs/STATUS.md) | **start here for orientation** — current state, how it runs, findings + where each is tracked, spec decisions, gotchas (durable snapshot of the working memory). |
| [`docs/TODO.md`](docs/TODO.md) | open work on Crucible itself (fixes for found bugs live in the owning repos, not here). |
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

## Attribute every finding before filing it: generated code, or the corelib?

**Required triage step, not an afterthought.** A divergence is never filed against
"SofaBuffers" — it goes to **the repo that contains the bug**. Guess wrong and you burn a
maintainer's time and the issue gets closed as misfiled: F-0008 was first filed against
corelib-c-cpp#84, and the maintainer had to redirect it (crucible#16) — it was codegen.

**The question that decides it:** *does the fix need knowledge only the schema has?*

| the bug is about… | who can even know it | file against |
|---|---|---|
| `count`, `maxlen`, `N`, a field's declared type — **schema** facts | only **generated code** (the corelib is schema-agnostic *by design*) | `generator` (sofabgen); log it as `G-00NN` in [`docs/SOFABGEN.md`](docs/SOFABGEN.md) |
| varints, the `fixlen_word`, wire types, subtypes, sequence framing, INVALID-vs-INCOMPLETE precedence — **wire** mechanics | the **corelib** reader/writer | `corelib-<lang>` (one issue per affected impl) |

MESSAGE_SPEC §7 states the same split from the other side: *"The corelib cannot know the
schema, so schema-bound violations are detected — and reported — by generated code."*

**Establish it, don't infer it:**

1. Read the **generated** code for the field (`drivers/<lang>/gen/…`) *and* the corelib
   function it calls.
2. Ask which of the two had the information to reject. If the corelib was handed a
   slice/length and faithfully used it, **the corelib is correct and its caller is the
   bug** — that is how F-0010 was pinned (every corelib array writer correctly writes
   `count = len(passed slice)`; only generated code knows `N`).
3. Diff a **sibling profile** that behaves differently — `cpp` vs `cpp-c-cpp`, `rust-std`
   vs `rust-no-std`, `py-cython` vs `py-pure`. A split *inside one language* usually
   indicts the generated container, not the wire code. (Counting `invalidate()` calls in
   the two generated C++ profiles — 13 vs 0 — is what pinned F-0013's residual.)
4. Put the evidence in the issue: `file:line`, what it validates **vs what it omits**, and
   the minimal isolate. Issues filed that way have been fixed the same day; vague ones
   bounce.

Worked examples: **F-0010 / F-0013** → codegen (`N` is schema-only) → `generator`.
**F-0014** → corelib (each decoder's `ARRAY_FIXLEN` element-word check) → three
`corelib-*` issues, all fixed same-day. **F-0009** → codegen (the C blob descriptor).
**F-0016** → corelib (the varint reader's 64-bit overflow check).

*Caveat:* the answer is occasionally **both** — F-0010's C slice needed corelib-c-cpp#87
alongside the codegen fix. Attribution decides where to *start*, and the write-up should
name the other side when it is implicated.

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

**Built and running** — do not trust this line for detail, read
[`docs/STATUS.md`](docs/STATUS.md) (it is the current-state snapshot and is kept
current; this file only orients you).

Phases 1–2 are done and Phase 3 is largely done: **13 drivers / 11 corelibs**, the
three-valued verdict (`A`/`I`/`R`, plus `L` in limit mode), a structure-aware mutator,
a C libFuzzer pacemaker, crash- *and* hang-isolation, auto-clustering, and six green
suites — differential (seeds), cross-encode, union, limit mode, the
**resolved-findings regression gate** (`corpus/regression/`, wired into CI), and the
**materialized element-access oracle** — plus the **structural sweep gate** (six axes,
all blocking).

Twenty-six findings are catalogued (`results/FINDINGS.md`): **25 resolved, 1 by-design,
0 open.** Three Crucible-authored MESSAGE_SPEC clauses have been adopted
(documentation#17/#18/#20). `./scripts/bootstrap.sh` always installs the **latest green
sofabgen CI build** (sha256-verified; falls back loudly to the latest release) and fetches the
corelibs to `origin/main` — there is deliberately no skip-if-present shortcut, because a
silently stale toolchain once made this repo report the wrong versions.
