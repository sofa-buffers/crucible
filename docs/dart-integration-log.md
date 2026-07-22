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

---

## Stage 4 — Materialized (element-access) oracle

**Goal:** the only suite needing Dart-specific schema knowledge. Dart AOT has no
`dart:mirrors`, so Dart joins the **build-time-generated-walker camp** (rust/cpp/zig),
not the runtime-reflection camp (go/ts/java/cs/py).

### Steps
1. `drivers/dart/materialize_gen.py` — unrolls `oracle/materialized-schema.json` into
   `materialize_gen.dart` (`String materialize(Probe m)`), straight-line field access.
   Non-probe schema → compile-only stub (union/limit don't materialize).
2. `drivers/dart/driver.dart` — import the walker; on COMPLETE + `SOFAB_MATERIALIZE=1`
   emit `A <materialize(out)>` instead of the round-trip hex.
3. `drivers/dart/build.sh` — run the generator each build.
4. `scripts/materialize.sh` — add `dart` to the roster; 12→13 strings.

### Dart type gotchas handled in the walker
- **u64** — Dart `int` is signed 64-bit; a high-bit value prints negative. `_u()`
  reinterprets via `BigInt.from(v) + (1<<64)`. **Verified** on `02_full` (u64 = max):
  Dart emits `u18446744073709551615`, byte-identical to C.
- **fp32** — stored as a Dart `double`; `_f32` repacks to the 32-bit IEEE pattern via
  `ByteData.setFloat32` (the mandated repack, `materialized.md` §floats).
- **fp64** — emitted as two `getUint32` halves so `toRadixString(16)` never sees a
  negative int (which would prepend `-`).

### 🐞 Finding (my driver, fixed same step — NOT a corelib/generator bug)
First materialize run diverged on **every** vector: Dart emitted integer leaves
**without the `u`/`s` type-tag prefix** (`0:0` vs C's `0:u0`) — I omitted the prefix in
the walker's `u`/`s` leaf emitters (the fp/string/blob helpers already tagged). Fixed
`materialize_gen.py` to prepend `u`/`s`; rebuilt. This is a **driver-side defect in
Crucible's own walker**, caught by the C-anchor conformance gate exactly as designed —
not attributable to corelib-dart or the generator.

### Results — GREEN
- **materialize differential** — 75 × 13, **0 divergences**.
- **C-anchor conformance** vs `engine/structured/materialize.py` — **0/75 mismatch**.
- Default round-trip path unregressed after the driver edits (seeds 6 × 13, 0 div).
- All 13 walkers remain schema-agnostic; Dart reflows from the descriptor at build time.

---

## Stage 5 — Coverage front-end (placeholder, mirrors Zig)

**Goal:** a coverage target skeleton. The C corelib stays the pacemaker (PLAN §3);
a Dart coverage engine is a stretch goal. Dart has no first-party libFuzzer, so the
intended path (per `.devcontainer/Dockerfile`) is a dart:ffi native-callable decode
core AOT-compiled into a shared lib and driven by a C libFuzzer harness — the same
C-interop plan as Zig, and like Zig's it is **unresolved** (PLAN §14).

### Steps
1. `drivers/dart/fuzz.dart` — documented placeholder smoke check exercising the decode
   core (empty→complete, `0x80`→incomplete, crash-freedom over all 1/4-byte prefixes).
   **Not** built by `build.sh` (matches Zig's `fuzz.zig`).

### Results
- **AOT-compiled** (`dart compile exe fuzz.dart`) and run: `dart fuzz smoke: OK`. Stays
  native end-to-end — no VM/JIT, per the operator constraint.
- `build.sh` has zero references to `fuzz.dart` (builds only the replay driver). No
  finding.

---

## Stage 6 — CI + docs

**Goal:** make the roster change durable and honest.

### CI — no per-gate edit needed
`replay.yml` and `nightly.yml` invoke the **scripts** (`run.sh`, `cross-encode.sh`,
`run-union.sh`, `run-limits.sh`, `sweep.sh`, `materialize.sh`), all of which now build
and register Dart — so Dart flows into every CI gate automatically. The only
requirement is the Dart SDK in the CI container image; `.devcontainer/Dockerfile`
already installs it (commit `9f85232`), so the standing one-time `image.yml` rebuild
carries it into `crucible-ci:latest`. Bootstrap already lists `corelib-dart` and pulls
the CI sofabgen build (needs `SOFABGEN_TOKEN`, already wired). Updated the stale "12
drivers" line in `nightly.yml`.

### Docs
- `docs/ARCHITECTURE.md` — header 12→13 / 10→11 + Dart; `drivers/dart/` component-table
  row; a full **per-language dart driver note**; present-tense count bumps
  (materialize/union/regression rows); **Deviation 2026-07-22b**.
- `docs/STATUS.md` — Current-state bullet refreshed to 13/11 on the CI build; a
  **Twenty-fifth change** entry (this integration + the F-0025 side-result).
- `README.md`, `CLAUDE.md` — driver/corelib counts and the sample output → 13 (+dart).
- Historical/dated narrative (past first-run descriptions, resolved-deviation notes) is
  **left intact** — those record what was true then; only present-tense capability
  claims were updated (prime directive: keep the as-built doc honest without rewriting
  history).

### Final consolidated verification (13 drivers)
| suite | result |
|---|---|
| seeds (`run.sh`) | 6×13, 0 div |
| regression gate | 73×13, 0 div (4 expected soft `incomplete_value`) |
| cross-encode | 75×13, 0 div |
| union | 11×13, 0 div |
| limit mode | arr 3×10 / str 2×10 / blb 2×10, 0 div |
| structural sweep | 5 blocking axes 0/0; wiretype now green (F-0025) |
| materialized | 75×13, 0 div + C-anchor 0/75 |

---

## Summary

**corelib-dart is integrated into every Crucible feature.** Roster: **13 drivers / 11
corelibs**. All suites green; Dart is AOT end-to-end (`dart compile exe`), never JIT.

- **No Dart-attributable finding** — the new corelib + generated Dart backend agree
  with the family on every suite, including the §7.3/§7.4 structural-skip and the
  INVALID-precedence edges the issue flagged.
- **One Crucible-side bug** (my materialize walker's missing `u`/`s` type tag), found
  and fixed in Stage 4 by the C-anchor conformance gate.
- **One toolchain side-result:** F-0025 (generator#193) is resolved on the current
  sofabgen CI build — verified, documented, recommended for a separate promotion
  follow-up (not bundled here).

Per-stage commits on branch `dart-integration`.
