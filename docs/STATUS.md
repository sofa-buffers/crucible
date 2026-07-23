# Crucible — status & running notes

Durable snapshot of where the project stands (mirrors the working agent's memory,
so a fresh session or another contributor is oriented immediately). Authoritative
design is [`PLAN.md`](PLAN.md); as-built detail + deviations are in
[`ARCHITECTURE.md`](ARCHITECTURE.md); this file is the *current-state* summary. The
dated, session-by-session work journal now lives in [`STATUS-LOG.md`](STATUS-LOG.md)
(history, append-only); per-finding truth is [`../results/FINDINGS.md`](../results/FINDINGS.md).

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
- `./scripts/materialize.sh` — the **element-access oracle** (`oracle/materialized.md`):
  `SOFAB_MATERIALIZE=1` makes each driver dump the **decoded value** (all fields + array
  elements explicit, floats as raw bits) instead of the round-trip hex, catching a decode
  that differs only where the sparse wire elides. **All 13 drivers** implement it — 75×13
  green vs the `engine/structured/materialize.py` reference (a **standing CI gate**); default
  round-trip path unchanged. The **table** (`engine/structured/schema.py` →
  `oracle/materialized-schema.json`) is generated from the schema and drives the reference; **all 13
  walkers are schema-agnostic** — C via the object descriptor, go/ts/java/cs/python consume the
  descriptor at runtime, rust/cpp/zig/dart generate their walker source from it at build time.
- `./scripts/run-union.sh` — the **union suite**: points the oracles at
  `schema/probe-union.sofab.yaml` (a `probe` carrying a 4-variant union), the one
  wire feature the main `probe` lacks. 11 seeds × 13 drivers, 0 divergences.
- `CORPUS=corpus/regression ./scripts/run.sh` — the **resolved-findings gate**: the
  reproducer of every fixed finding (0 divergences across all 13 drivers). A
  divergence here = a resolved bug came back. See `corpus/regression/README.md` for
  what it admits, and the exclusions (a reproducer that also trips an open axis stays
  in `findings/`).

## Current state
- **Phases 1–3 largely done:** 13 drivers / 11 corelibs green across all suites on the
  latest green **sofabgen CI build** (c, go, rust-std, rust-nostd, cpp, cpp-c-cpp,
  py-cython, py-pure, java, typescript, csharp, zig, **dart**). `./scripts/bootstrap.sh`
  keeps sofabgen at the latest green CI build (sha256-verified) and the corelibs at
  `origin/main`. **Dart** (crucible#77) was integrated 2026-07-22.
- **Structural sweep framework** (`engine/structured/sweep_*.py`, PLAN §6): a sweep enumerates
  one normative rule across **every** schema position and checks two oracles (agreement +
  conformance). **Seven axes** wired via `sweep_run.py` / `scripts/sweep.sh` — repeated-id (§7.4),
  over-bound (§7.1), reserved-subtype (§4.6), truncation (§7), malform×truncation (§5.2),
  wiretype (§7.3), varint (§2 canonicality) — **all seven blocking + green, no carve-out**.
  This is what found F-0020–F-0025 — "isolate-green ≠ axis-green". An **eighth axis (report-only)**
  **`sweep_framing`** (§5.2 stray-end + §6.2 ID_MAX/FIXLEN_MAX/ARRAY_MAX/MAX_DEPTH) is wired
  **report-only** — its stray-end/FIXLEN_MAX/ARRAY_MAX vectors are green, but the ID_MAX and MAX_DEPTH
  vectors surfaced F-0028/F-0029, so the axis stays report-only until those resolve. A **union pass**
  (report-only) runs the five reject/skip axes over `schema/probe-union.sofab.yaml`; it surfaced F-0027.
- **Findings: 33 catalogued** (`results/FINDINGS.md`) — **25 resolved, 1 by-design (F-0018), 7 open
  (F-0027…F-0033; F-0033 is a spec hole).** See `results/FINDINGS.md` for the per-finding table and
  `STATUS-LOG.md` for the chronological resolution history. Three Crucible-authored MESSAGE_SPEC
  clauses adopted (documentation#17/#18/#20).
- **Phase 3 (built):** canonical form v2 = **round-trip re-encoding** with a
  **three-valued verdict** (`A` complete / `I` incomplete / `R` reject, per
  MESSAGE_SPEC §7); drivers are schema-agnostic; schema scaled to the **full-scale**
  message; **C pacemaker active** (~41k exec/s); comparator is **crash-isolating**;
  **auto-clustering**; plus the **second (materialized) canonical form** as a standing gate.
- **Union feature covered:** `schema/probe-union.sofab.yaml` + `corpus/union/` (11 seeds) +
  `scripts/run-union.sh` — all backends generate the union and agree on every variant, the
  one-of encoding, and the malformed-union edge cases. Cross-encoded and swept too.
- Remaining Phase 3 / Phase 4: see [`TODO.md`](TODO.md).

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
Fixes live in the **owning repos** (done in fresh contexts); Crucible is the catalog + verifier.
Four records, each with one owner:

| for | read |
|---|---|
| the per-finding catalog (F-00NN: title, impls, axis, root cause, resolution, links) | [`../results/FINDINGS.md`](../results/FINDINGS.md) |
| generated-code weaknesses (G-00NN) | [`../results/FINDINGS.md`](../results/FINDINGS.md) |
| root-cause clusters of raw divergences | [`../results/CLUSTERS.md`](../results/CLUSTERS.md) |
| the dated resolution history / work journal | [`STATUS-LOG.md`](STATUS-LOG.md) |

Reproducers live under `findings/<id>/`. Transient, un-triaged crash/divergence artifacts live
under `corpus/crashes/` (gitignored); promoted findings land in the catalog.

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
- **G-0006 is fixed** (sofabgen 0.15.1, generator#84): the old `drivers/go/build.sh`
  workaround that injected a missing `bytes` import into the generated `types.go` has
  been removed — the generator now emits the import.
- **Characterize a divergence with a minimal isolate**, not a raw fuzzer input — the
  coarse `invalid_msg` reject class conflated reasons (F-0004 was mischaracterized
  until isolated).
