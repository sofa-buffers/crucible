# corelib-dart integration — execution log

Autonomous run integrating `corelib-dart` (the generator's 10th language target,
generator#211 / crucible#77) into every Crucible feature. One commit per step on
branch `dart-integration`. Findings are attributed (generated code vs corelib)
per the CLAUDE.md triage table and filed in `results/FINDINGS.md`.

**Baseline toolchain:** sofabgen `0.0.0-20260722065611-f61a29b31c01` (latest green
CI build, sha256-verified); corelib-dart `7717fab`; Dart SDK 3.12.2. Target roster
grows **12 → 13 drivers / 10 → 11 corelibs**.

The generated Dart API maps 1:1 to the canonical form:
`Probe.tryDecode(Uint8List, Probe) -> DecodeStatus{complete,incomplete,invalid,limitExceeded}`
→ `A / I / R / L`; schema-bound violations fold into `invalid` via a sticky flag
(the Rust/Zig model). It is the Go driver, in Dart.

---

## Stage 1 — Replay driver (seeds / regression / cross-encode / union)

**Goal:** `drivers/dart/{driver.dart,build.sh,meta}` + register `dart` in
`scripts/run.sh`. Because the round-trip canonical form is schema-agnostic, this
one driver unlocks the four suites that reuse `run.sh` (cross-encode and union
`exec run.sh`).

### Steps
1. `drivers/dart/driver.dart` — persistent replay front-end. Reads the whole framed
   stdin stream (comparator writes it all, then reads stdout after exit — the proven
   TS pattern), parses `<u32 le len><payload>` records, maps `DecodeStatus` → canonical
   line. Coarse reject class `invalid_msg` (the status carries no finer code; soft axis).
2. `drivers/dart/build.sh` — `sofabgen --lang dart` → `bin/message.dart`; a minimal
   `pubspec.yaml` path-depends on `vendor/corelib-dart`; `dart pub get`; **`dart compile
   exe`** (AOT). Honors `SCHEMA`/`LIMITS` like the peers.
3. `drivers/dart/meta`.
4. Registered `dart` in `scripts/run.sh` (build + `--driver dart:$DART_BIN`).

**AOT, never JIT** — per the operator constraint, the suite runs the **native
release binary**, not `dart run`/VM. Verified: `build.sh` uses `dart compile exe`
only (no `dart run` anywhere), and the artifact is a native ELF
(`drivers/dart/build/driver`, magic `\x7fELF`).

### Results — all Stage 1 suites GREEN
- **Self-check:** Dart output byte-identical to Go on all 6 seeds.
- **seeds** — 6 × 13 drivers, **0 divergences**.
- **regression gate** — 73 × 13, **0 divergences** (4 expected soft `incomplete_value`
  warnings, c-vs-java on truncation reproducers — pre-existing, Dart not involved).
- **cross-encode** — 75 × 13, **0 divergences** (cross-encode `exec`s run.sh).
- **union** — 11 × 13, **0 divergences** (run-union `exec`s run.sh with the union schema).

Roster is now **13 drivers / 11 corelibs**. No finding. The schema-agnostic round-trip
form paid off exactly as planned: one replay driver, four suites green, zero per-field
Dart code.
