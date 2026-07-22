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

---

## Stage 2 — Limit mode (`L` verdict)

**Goal:** add Dart to the heap-only roster in `scripts/run-limits.sh`. Dart uses
growable `List<...>`, so it can represent a schema-unbounded field (unlike the
fixed-capacity c/c-cpp/rust-nostd) and belongs in the roster.

### Verification of the codegen path
Generating with a `max_dyn_*` config shows the Dart backend bakes a
`const sofab.DecoderLimits _limits = DecoderLimits(maxArrayCount: …, …)` and passes
it to `Decoder.decode(data, visitor, limits: _limits)`, returning
`DecodeStatus.limitExceeded` when a cap is exceeded — my driver already maps that to
`L`. **No driver change needed.**

### Steps
1. `scripts/run-limits.sh` — build `DART_BIN` under the exported `SCHEMA=probe-dyn`
   / `LIMITS`, add `dart:` to the echo loop and the `ALL` driver list.

### Results — GREEN
- **arr** 3 × 10, **str** 2 × 10, **blb** 2 × 10 — **0 divergences** (roster now 10
  heap drivers incl. dart).
- Explicit `L` check (cap = 8, `corpus/limits/arr`): `under_arr → A`, `at_arr_8 → A`,
  `over_arr → L`. Dart agrees with the family on the fourth verdict. No finding.

---

## Stage 3 — Structural sweep (6 axes)

**Goal:** add Dart to `engine/structured/sweep_run.py`'s hardcoded `DRIVERS` roster
(it does *not* reuse run.sh's list — confirmed) and the cosmetic 12→13 strings.

### Steps
1. `engine/structured/sweep_run.py` — add `("dart", …/drivers/dart/build/driver)`.
2. `sweep_run.py` + `scripts/sweep.sh` — 12→13 in docstrings/log lines.

### Results — GREEN, incl. the §7.3/§7.4 structural-skip the issue flagged
All five **blocking** axes 0 divergences / 0 conformance failures **with 13 drivers**:
repeated-id (§7.4) 15, over-bound (§7.1) 30, reserved-subtype (§4.6) 110,
truncation (§7) 179, malform×truncate (§5.2) 20. Dart's dispatch-by-resolved-type
skip on a contradictory wire type / array-at-scalar-id / fixlen-subtype mismatch
matches the family — no desync, no Dart-specific split. No finding for Dart.

### 🔎 Bonus finding (NOT Dart) — **F-0025 resolved on the current toolchain**
The **wiretype (§7.3) axis came back GREEN** (319 vectors, 0/0), where it was
report-only for the open **F-0025** (fp scalar field receiving an fp array —
rust-std/rust-nostd/java/csharp/zig stored the element; generator#193). Cause: the
bootstrapped **sofabgen CI build `0.0.0-20260722065611-f61a29b31c01`** is newer than
0.19.4 and carries generator#193. **Verified three ways:** (1) sweep wiretype green;
(2) both reproducers (`f32_recv_array_fp32`, `f64_recv_array_fp64`) now show **all 13
drivers agree** — the fp array is skipped, re-encoding to the empty-scalar form
`5607a606560707c60c07ce0c07` — including the five formerly-storing backends; (3) both
controls still agree. Dart also skips correctly.

This is a toolchain-bump result, independent of Dart, so it is **left out of this
branch's scope**. Recommended separate follow-up (per `docs/TODO.md`): promote the
wiretype axis from report-only → blocking in `scripts/sweep.sh`, mark F-0025 resolved
in `results/FINDINGS.md`/`STATUS.md`, and promote its isolates into `corpus/regression/`.
