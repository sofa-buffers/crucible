# Crucible — Master Plan

> **Crucible** is the differential fuzzing harness for the SofaBuffers wire
> format. It feeds the same bytes to every corelib implementation and fails when
> they *disagree*. This document is the authoritative design; everything is
> implemented from here, and new corelibs are onboarded against the checklist at
> the end. When reality diverges from this plan, record it in
> [`ARCHITECTURE.md`](ARCHITECTURE.md) — **do not** silently edit the plan to
> match the code.

---

## 1. Mission

SofaBuffers ships one wire format (`documentation/MESSAGE_SPEC.md`) implemented
independently in many languages (`corelib-c-cpp`, `corelib-cpp`, `corelib-cs`,
`corelib-go`, `corelib-java`, `corelib-py`, `corelib-rs`, `corelib-rs-no-std`,
`corelib-ts`, `corelib-zig`). Independent implementations of one format drift.
The drift that hurts is **silent**: two implementations both accept a byte
sequence but decode it to different values, or one accepts what another rejects.
No crash, no exception — just broken interop discovered in production.

Crucible exists to make that drift **loud, automatic, and continuous**.

**The defining principle:** the oracle is *disagreement between
implementations*, not a crash. A single-implementation fuzzer can only ask "did
I crash?". Crucible asks "do all implementations agree on what these bytes
mean?" — the question that actually matters for a shared wire format.

## 2. Scope

**In scope**

- Differential decode testing: same wire bytes → every corelib → compare result.
- Round-trip and cross-encode invariants (§6).
- Coverage-guided, structure-aware input generation (§5).
- Memory-safety detection via sanitizers as a *second* net (§9).
- Reproducible, minimized findings and a regression gate (§10).

**Out of scope (explicit non-goals)**

- **Not a benchmark.** Performance lives in `arena`. Crucible builds corelibs
  *instrumented and slow* (sanitizers + coverage) — the opposite of arena's
  optimized builds. This is the core reason Crucible is its own repo, not part
  of arena.
- **Not a replacement for per-corelib crash fuzzers.** Each corelib may keep its
  own in-tree fuzzer (e.g. `corelib-c-cpp/test/fuzz`); Crucible neither depends
  on nor modifies them. Those prove "my impl survives garbage"; Crucible proves
  "all impls agree."
- **Not the spec.** `documentation/MESSAGE_SPEC.md` is the source of truth for
  what is correct. Crucible *tests against* it and surfaces where the spec is
  underspecified (§8), but does not define behavior.

## 3. Architecture at a glance

```
                 ┌─────────────────────────────────────────────┐
   seed corpus → │  ENGINE  (coverage-guided, structure-aware)  │
                 │  drives ONE pacemaker impl (C) for coverage  │
                 └───────────────┬─────────────────────────────┘
                     interesting input (wire bytes)
                                 │  fan out
        ┌────────┬────────┬──────┴────┬────────┬─────── … N drivers
        ▼        ▼        ▼           ▼        ▼
      C(san)   Rust      Go        Java     Python   …
        │        │        │           │        │
        └────────┴────────┴─────┬─────┴────────┘
                  canonical result + verdict
                                 ▼
                       DIFFERENTIAL COMPARATOR
             (all must agree on ACCEPT/REJECT + canonical value,
              modulo the allowed-divergence policy)
```

**One engine, N oracles.** Running every language coverage-guided *and*
cross-comparing is needlessly complex. Instead a single **pacemaker** — the C
corelib, the fastest to instrument, built with libFuzzer + sanitizers — drives
coverage-guided exploration of the wire-format state space. Every input it flags
as coverage-interesting is replayed through **all** drivers and their canonical
outputs compared. C is the coverage motor, not a privileged oracle: its own
output is compared like everyone else's.

## 4. Components

| Component | Responsibility |
|---|---|
| `vendor/` | Every corelib + `sofabgen`, checked out (pattern inherited from arena). |
| `schema/` | The fuzzed message definition(s) + canonical field values — single source of truth (arena's `STATE.md`/`state.json` pattern). |
| `drivers/<lang>/` | Per-language persistent fuzz driver: wire bytes in → canonical result + verdict out. Built with sanitizers + coverage. |
| `engine/` | The coverage-guided motor + the structure-aware mutator + corpus manager. Drives the pacemaker. |
| `oracle/` | The differential heart: the canonical-form spec, the comparator, and the allowed-divergence policy. |
| `corpus/` | `seeds/` (from published test vectors + hand-picked frames), `interesting/` (accumulated coverage inputs), `crashes/` (minimized findings). |
| `scripts/` | `run.sh` (one input → all drivers → compare), `fuzz.sh` (pacemaker loop), `replay.sh` (regression gate). |
| `results/` | Human-readable findings reports. |
| `tools/` | Fuzzing toolchains (libFuzzer, cargo-fuzz, Jazzer, Atheris, …). |

## 5. Input generation

Two techniques, both absent from the naive per-corelib fuzzers, combined:

- **Coverage-guided** (libFuzzer/AFL++ via the pacemaker): inputs that open new
  code paths are kept and mutated further. Without this, random bytes almost
  always die at the first length/type byte and deep paths (nested sequences,
  depth limits, array counts, varint boundaries) are never reached.
- **Structure-aware**: a custom mutator that understands the TLV/varint grammar
  and mutates at the *frame* level — flip a field id, extend a varint past 64
  bits, claim an array count of 2³² with 3 elements present, nest sequences to
  the depth limit ±1. This gets past the first parser stage into the semantically
  interesting code.

**Two corpus tracks:**

- **Malformed track** — raw/mutated bytes. Hunts crashes, UB, and
  accept-vs-reject divergence.
- **Structured track** — valid-ish frames generated from the schema. Hunts
  *semantic* divergence: implementations that all accept but decode to different
  values. This is where interop bugs live.

## 6. The three oracles

The comparator checks three invariants, not just crash-freedom:

1. **Decode agreement** — all drivers must agree on `ACCEPT`/`REJECT`, and on
   `ACCEPT` agree on the canonical value.
2. **Round-trip idempotence** (per impl) — `decode → re-encode → decode` must be
   stable. Catches non-canonical encoding.
3. **Cross-encode** — encode a structured value in impl A, decode in impl B,
   compare. Catches encoder/decoder asymmetry *between* languages.

## 7. Driver ABI (the contract)

Every `drivers/<lang>/` obeys one contract so the comparator treats them
uniformly. **Drivers are generated from the schema where possible** (via
`sofabgen`), so they stay in sync as the schema evolves — hand-writing N drivers
is a maintenance trap.

- **Persistent mode.** One process handles millions of inputs via a loop reading
  length-prefixed inputs from a pipe/stdin. Fork+exec per input caps throughput
  at thousands/sec; persistent mode reaches millions. This is a 100–1000× factor
  and is non-negotiable for real fuzzing depth. (This is *why* Crucible does not
  reuse the generator's `encode`/`decode` CLI, which is process-per-input.)
- **Canonical output, not general JSON.** The driver emits the decode result in
  the canonical form defined in `oracle/canonical.md` — designed for byte-exact
  diffing: floats as bit patterns (not `"NaN"`/`"inf"` strings), explicit type
  tags, and an explicit distinction between *field absent* / *field present but
  default* / *field has value*. General JSON blurs exactly the cases where impls
  diverge.
- **Verdict + error taxonomy.** Output is `ACCEPT(canonical)` or
  `REJECT(error-class)` where error-class is a real taxonomy
  (`truncated`, `bad-varint`, `depth-exceeded`, `length-overflow`, …), not just
  pass/fail — so the comparator can tell "rejected for the same reason" from
  "rejected differently."

## 8. Allowed-divergence policy & the spec dependency

Differential testing needs a definition of which divergences are *bugs* vs
*legal*. For malformed/truncated input: is there one spec-correct outcome (then
accept-vs-reject disagreement is a bug) or is it undefined (then impls may
legally differ)? This lives in `oracle/policy.yaml`.

**Design stance:** push toward *specifying* malformed-input handling in
`MESSAGE_SPEC.md` wherever practical. More spec work, but it turns Crucible into
a **spec-completeness engine**: every unresolved divergence is either a bug or a
hole in the spec, and both are worth surfacing. `policy.yaml` starts permissive
(record divergence on undefined input without failing) and tightens as the spec
firms up. Every entry in `policy.yaml` cites the `MESSAGE_SPEC.md` clause (or
records that none exists yet).

## 9. Sanitizers (the second net)

Differential catches semantic divergence; sanitizers catch memory/UB faults that
don't immediately crash. Both run in parallel:

- Native drivers (C, C++, Rust, Zig): **ASan + UBSan**, plus a separate **MSan**
  build for uninitialized reads.
- Managed drivers lean on their runtime: Jazzer (Java), Atheris (Python), native
  bounds/race checks (Go), SharpFuzz (C#).

## 10. Findings, reproducibility, CI

The naive fuzzers have none of this (infinite loop, no artifacts). Crucible:

- Saves every crash/divergence as a **minimized** input (`libFuzzer -minimize`),
  tagged with *which impls disagreed* and *their canonical outputs*,
  deterministically replayable.
- Keeps a **regression corpus** replayed by `scripts/replay.sh`.
- CI has **two workflows**: `replay` (fast, blocking, every push — replays the
  regression corpus + known crashes) and `nightly` (long, non-blocking,
  continuous fuzzing that grows the corpus). OSS-Fuzz is the eventual home for
  continuous fuzzing (§12).

## 11. Repo layout

```
crucible/
├── CLAUDE.md               # agent entry point
├── README.md               # human overview (short)
├── docs/
│   ├── PLAN.md             # this file — the master plan
│   └── ARCHITECTURE.md     # living as-built doc + deviations from PLAN
├── vendor/                 # all corelibs + sofabgen (arena pattern)
├── schema/
│   ├── message.sofab.yaml  # the "full scale" fuzzed message
│   └── STATE.md/state.json # canonical field values (single source of truth)
├── drivers/
│   ├── common/             # contract doc; shared canonical-form helpers
│   ├── c/                  # PACEMAKER: libFuzzer + ASan/UBSan  {build.sh, driver.c, meta}
│   ├── rust/               # cargo-fuzz                          {build.sh, driver.rs, meta}
│   ├── go/                 # native go fuzz                      {build.sh, driver.go, meta}
│   ├── java/               # Jazzer
│   ├── python/             # Atheris
│   └── cpp/ cs/ ts/ zig/   # (SharpFuzz for cs, Jazzer.js for ts)
├── engine/
│   ├── mutator/            # structure-aware TLV/varint grammar
│   └── corpus_mgr.*        # coverage-guided corpus management
├── oracle/
│   ├── canonical.md        # canonical comparison form (spec)
│   ├── comparator.*        # compares N canonical outputs
│   └── policy.yaml         # allowed-divergence policy (cites MESSAGE_SPEC)
├── corpus/{seeds,interesting,crashes}/
├── scripts/{run.sh,fuzz.sh,replay.sh}
├── results/
├── tools/
├── .devcontainer/          # fuzz toolchains (NOT arena's optimized env)
└── .github/                # workflows: replay (push) + nightly (continuous)
```

## 12. Roadmap (phases)

- **Phase 0 — Skeleton.** Repo layout, `vendor/` bootstrap (corelibs + sofabgen),
  schema, driver contract in `drivers/common/`, `oracle/canonical.md` v0,
  `oracle/policy.yaml` (permissive).
- **Phase 1 — Two-language differential loop.** C pacemaker (libFuzzer +
  ASan/UBSan) + one second language (**Go**, native fuzzing, no external
  framework → fastest to a running loop). `run.sh` + comparator prove end-to-end
  divergence detection on seeded corpus.
- **Phase 2 — Fill out drivers.** Add remaining languages one at a time against
  the checklist (§13): Rust, C++, Java, Python, C#, TypeScript, Zig.
- **Phase 3 — Structure-aware mutator.** Replace/augment byte-level mutation with
  the TLV/varint grammar mutator; add the structured corpus track and the
  round-trip + cross-encode oracles.
- **Phase 4 — Continuous.** Minimization, regression gate in CI, then OSS-Fuzz
  onboarding for continuous fuzzing.

## 13. Checklist — add a new corelib / language

This is the reason the plan exists. To onboard a new implementation:

1. **Vendor it.** Add the corelib to the `vendor/` bootstrap list; add its
   toolchain + fuzzing framework to `.devcontainer/`.
2. **Create `drivers/<lang>/`** mirroring an existing driver (start from `go/` or
   `c/`): `build.sh` (sanitizers + coverage, *not* optimized), the persistent
   `driver` (generated from the schema via `sofabgen` where possible), `meta`.
3. **Implement the driver contract (§7):** persistent length-prefixed loop,
   canonical output per `oracle/canonical.md`, `ACCEPT`/`REJECT` + error
   taxonomy. Reuse `drivers/common/` helpers.
4. **Wire sanitizers (§9):** native → ASan/UBSan (+ MSan build); managed → the
   language's fuzzing runtime.
5. **Register in `run.sh`/`fuzz.sh`** (or, following arena's precedent, make the
   comparator discover drivers from output so there is no registry to maintain —
   preferred).
6. **Validate:** run the seed corpus through the new driver alone (self-check:
   canonical output stable, round-trip idempotent), then through the comparator
   against the existing drivers. Any immediate divergence is either a real bug or
   a `policy.yaml` gap — triage before merging.
7. **Update [`ARCHITECTURE.md`](ARCHITECTURE.md)** with the new driver's
   framework, quirks, and any deviation from this checklist.

## 14. Open questions (resolve as we build)

- **Zig fuzzing maturity.** Zig 0.16's built-in fuzzing is young; the Zig driver
  may need libFuzzer/AFL via C interop. Confirm in Phase 2.
- **Spec formality of malformed input (§8).** The single biggest signal/noise
  lever. Drive the `MESSAGE_SPEC.md` decision early.
- **Canonical form for floats/NaN payloads and default-vs-absent** — pin exactly
  in `oracle/canonical.md` before Phase 1 comparator work.
- **Driver generation vs hand-writing** — how much of each driver `sofabgen` can
  emit vs. per-language glue. Establish the split with the C + Go pair.
