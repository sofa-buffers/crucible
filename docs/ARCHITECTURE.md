# Crucible — Architecture (living document)

> **Status: Phase 2 complete** — the differential loop runs across all twelve
> drivers / ten corelibs (C pacemaker, Go, Rust-std, Rust-no-std, C++, C++/c-cpp,
> Python-Cython, Python-pure, Java, TypeScript, C#, Zig) over the minimal `probe`
> schema. Next is Phase 3 (structure-aware engine + round-trip/cross-encode
> oracles + schema scale-up). This describes
> architecture **as actually built**, and is updated whenever the real system
> changes — especially when it **deviates from [`PLAN.md`](PLAN.md)**. `PLAN.md`
> is the intended design and stays stable; this file tracks what exists and why
> it differs.
>
> **Maintenance rule:** every change that alters a component boundary, a
> contract, a build flag, or a data format updates this file in the *same*
> change. When behavior deviates from `PLAN.md`, add a dated entry to
> §"Deviations from PLAN".

---

## Component status

Legend: `planned` · `in progress` · `built` · `changed` (differs from PLAN — see Deviations)

| Component | Status | Notes |
|---|---|---|
| `scripts/bootstrap.sh` | built | Symlinks sibling `../corelib-*` when present, else clones; sources sofabgen from a sibling arena/generator or clones+builds. |
| `schema/probe.sofab.yaml` | built | **Full-scale** message (Phase 3): 8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays, string array. Still keyed `probe` (stable type name). |
| `drivers/common/CONTRACT.md` | built | Persistent length-prefixed protocol + canonical output. |
| `drivers/c/` (pacemaker) | built | gcc replay driver (ASan/UBSan) verified; libFuzzer front-end present, `#ifdef CRUCIBLE_LIBFUZZER`, built in devcontainer (no clang in bare workspace). |
| `drivers/go/` | built | Replay driver + native `FuzzProbe`; builds against vendored corelib-go via `replace`. |
| `oracle/canonical.md` | built | v0 canonical form. |
| `oracle/comparator.py` | built | N-way canonical diff, policy-aware, no external deps. |
| `oracle/policy.yaml` | built | Permissive Phase-1 policy (verdict/accept_value hard, reject_class soft). |
| `scripts/run.sh` | built | Build all drivers → differential compare over a corpus (crash-isolating). |
| `scripts/fuzz.sh` | built | The C pacemaker: build the libFuzzer target (clang) + run + grow corpus/interesting. |
| C pacemaker (libFuzzer) | built | `drivers/c/driver.c` `CRUCIBLE_LIBFUZZER` path; ~41k exec/s; grows the corpus fed to the differential loop. Coverage-guided but NOT yet structure-aware. |
| `corpus/seeds/` | built | 6 agreeing seeds (the regression gate); green across all 4 drivers. |
| `findings/`, `results/FINDINGS.md` | built | F-0001 recorded (see below). |
| `docs/SOFABGEN.md` | built | Generated-code weakness log (G-0001..G-0004 from the Rust drivers). |
| `.devcontainer/` | built | Fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, SharpFuzz, Jazzer.js). |
| `drivers/rust/` (rs + rs-no-std) | built | One shared `driver.rs` for both corelibs; two-pass decode (see notes). |
| `drivers/cpp/` (cpp + c-cpp) | built | One shared `driver.cpp` for both corelibs; single-pass (feed returns Result). |
| `drivers/python/` (cython + pure) | built | One `driver.py`, both engines of corelib-py via `SOFAB_PUREPYTHON`; fallible decode (try/except). |
| `drivers/java/` | built | Replay driver on the JVM against corelib-java's jar; fallible decode (try/catch); Jazzer coverage target. |
| `drivers/ts/` | built | Node replay driver, esbuild-bundled from corelib-ts source; fallible decode (try/catch); Jazzer.js coverage target. |
| `drivers/cs/` | built | .NET replay driver referencing corelib-cs's built DLL; fallible decode (try/catch); SharpFuzz coverage target. |
| `drivers/zig/` | built | Zig 0.16 replay driver, corelib wired as the `sofab` module; fallible decode (`catch`); coverage target is a placeholder (Zig fuzzing immature). |
| `engine/mutator/` (structure-aware) | planned | Phase 3 — libFuzzer's byte-level mutator works; a TLV/varint grammar mutator is the next step. |
| Round-trip oracle | built | Folded into the canonical form (re-encoding) — found F-0002. |
| Cross-encode oracle | planned | Phase 3. |
| CI (`replay`, `nightly`) | planned | Phase 4. |

## As-built detail

### Replay driver protocol (as built)

stdin: repeated records `<uint32 little-endian length N><N payload bytes>`; clean
EOF at a record boundary → exit 0. stdout: exactly one canonical line per record,
`\n`-terminated, in input order. stderr: logs only. Implemented identically in
`drivers/c/driver.c` (`main`) and `drivers/go/driver.go` (`main`). The comparator
(`oracle/comparator.py`) frames the whole corpus into one stream per driver and
reads back one line per input.

### Canonical form (as built)

**v1 — round-trip re-encoding** (Phase 3; superseded the v0 per-field text form).
Per `oracle/canonical.md`: each driver emits `A <hex(encode(decode(input)))>` on
accept, `R <class>` on reject — the decoded value re-encoded with the corelib's
own sparse-canonical encoder, hex-printed. This makes every driver
**schema-agnostic** (no per-field code; scaling the schema needs zero driver
changes) and folds in the round-trip oracle. Verified: all 12 drivers emit
byte-identical hex for the seed corpus (e.g. `02_basic → A 002a090d12200000c03f1a126869`).

### Per-language driver notes (as built)

- **c** — object API (`message_probe_decode`) into a value struct; reject class
  mapped from `sofab_ret_t`. Built with gcc `-fsanitize=address,undefined`.
  libFuzzer front-end guarded by `CRUCIBLE_LIBFUZZER` (clang, devcontainer).
  **Empty-input precondition:** `sofab_istream_feed` asserts `datalen>0` (a debug
  precondition); under `NDEBUG` the same call returns OK with defaults, agreeing
  with Go. The driver treats a 0-byte input as the valid all-defaults message so
  the asserts-on build does not false-abort on a valid empty message, while
  asserts still fire on real bugs for non-empty input.
- **go** — generated visitor decode (`DecodeProbe`); decode error → `R invalid_msg`
  (coarse; reject-class soft), else re-encode → hex. Native coverage via
  `go test -fuzz=FuzzProbe`; module resolves corelib-go via a `replace`. `build.sh`
  carries a **G-0006 workaround**: sofabgen's generated `types.go` uses
  `bytes.Equal` (blob in a nested struct) without importing `"bytes"`, so the
  build injects the missing import (see docs/SOFABGEN.md).
- **rust (rs + rs-no-std)** — one shared `drivers/rust/driver.rs` builds against
  BOTH corelibs; `build.sh <rs|rs-no-std>` selects the vendored crate and
  prepends a per-variant `Probe` import (`mod message` for std, the lib crate
  `sofabuffers_generated` for no-std). Registered as two separate drivers
  (`rust-std`, `rust-nostd`) — they are two implementations to compare.
  **Two-pass decode:** sofabgen's generated `Probe::decode` is infallible (drops
  `feed`'s `Result` — docs/SOFABGEN.md G-0001), so the driver takes the *value*
  from `Probe::decode` (faithful string/capacity handling) and the *verdict* from
  a second `IStream::feed` against a null visitor. Visitor callbacks return unit
  and cannot affect `feed`'s result, so the null-pass verdict equals the one
  inside `decode`. Reject class maps `sofab::Error` (same 4 codes as C's
  `sofab_ret_t`). Coverage engine is cargo-fuzz (libFuzzer; devcontainer). The
  Rust `Probe.s` differs by variant (`String` vs `heapless::String<64>`) but
  `.as_bytes()` canonicalizes both identically.
- **cpp (cpp + c-cpp)** — one shared `drivers/cpp/driver.cpp` builds against BOTH
  corelibs; `build.sh <cpp|c-cpp>` selects the include path (`corelib-cpp/include`
  vs `corelib-c-cpp/src/include`) and, for c-cpp, compiles the C corelib sources
  (`object/istream/ostream.c`, C99, sanitized) and links them. The generated
  `probe.hpp` and the `sofab::` API are identical across both, so the source is
  shared. Registered as two drivers (`cpp`, `cpp-c-cpp`). **Single-pass:** unlike
  Rust, `IStreamObject::feed` returns the `Result`, so the driver bypasses the
  infallible generated `decode` (docs/SOFABGEN.md G-0005), uses `IStreamObject`
  directly, and reads value (`*in`) and verdict (`feed`'s Result) in one pass.
  Reject class maps `sofab::Error` (same 5 codes as C's `sofab_ret_t`). Empty
  input guarded (len==0 → all-defaults) because c-cpp routes to the C istream's
  `datalen>0` assert. Coverage engine is libFuzzer (devcontainer).
- **python (cython + pure)** — one shared `drivers/python/driver.py` runs against
  BOTH engines of the SAME corelib-py, switched at runtime by `SOFAB_PUREPYTHON`
  (`0` → compiled Cython `sofab._speedups`; `1` → pure-Python fallback). `build.sh`
  makes one venv, `pip install`s corelib-py **with Cython present** (so the
  `_speedups` extension is compiled for the running interpreter — otherwise
  "cython" mode silently degrades to pure), generates `message.py`, and emits one
  executable wrapper per mode (`py-cython`, `py-pure`) that sets the env +
  `PYTHONPATH`. Registered as two drivers. **Fallible decode:** unlike Rust/C++,
  the generated Python `Probe.decode` *raises* (`SofaError` subclasses) on bad
  input, so the verdict is a plain try/except — no workaround; reject class maps
  the exception type. Float canonical uses `struct` repack to f32 bits (NaN
  payloads may not round-trip double→f32 — a known limit, harmless for current
  seeds). Coverage engine is Atheris (needs clang; devcontainer).
- **java** — `drivers/java/Driver.java` (persistent replay, package `crucible`)
  compiled with the generated `message.*` classes against corelib-java's
  `target/sofab.jar` (built via `mvn package` if the vendored checkout lacks it);
  `build.sh` emits an executable wrapper that runs `java … crucible.Driver`.
  **Fallible decode:** the generated `Probe.decode` wraps a decode failure in a
  `RuntimeException`, so the verdict is a try/catch; reject class is derived
  coarsely from the exception cause. Fields `u`/`i` are widened to `long` by the
  Java backend but hold in-range u32/i32 values, so decimal printing matches;
  float bits via `Float.floatToRawIntBits` (raw, NaN-preserving). Coverage engine
  is Jazzer (`FuzzProbe.java`, devcontainer — not compiled by `build.sh`, which
  builds only the replay driver).
- **typescript** — `drivers/ts/driver.ts` runs on Node; `build.sh` bundles it +
  the generated `message.ts` + corelib-ts **source** into one CJS file with
  esbuild, aliasing `@sofa-buffers/corelib` to the corelib's `src/index.ts`. We
  bundle from source deliberately: the vendored corelib-ts's committed `dist/` was
  stale (missing `Cursor`, which the generated code imports), and bundling the
  source avoids depending on a built artifact and needs no separate corelib build.
  **Fallible decode:** the generated `Probe.decode` throws `SofabError` on bad
  input (try/catch verdict). The driver reads the whole framed stream via
  `readFileSync(0)` (Node stdin is async; the corpus fits in memory), fp32 bits
  via `Float32Array`/`DataView` (NaN payloads may not round-trip, as in Python).
  corelib-ts has swappable js/native/wasm kernels; the driver uses the default
  (js) — the native/wasm kernels are candidate future variants (like Python
  cython/pure). Coverage engine is Jazzer.js (`fuzz.ts`, devcontainer).
- **csharp** — `drivers/cs/Driver.cs` (console, namespace `Crucible`) compiled
  with the generated `Message.cs` against corelib-cs. `build.sh` builds the corelib
  assembly standalone into `build/corelib` and references the **built DLL** rather
  than a `ProjectReference` (a ProjectReference into the symlinked vendor tree hit
  a ref-assembly ordering error, CS0006; the DLL reference also keeps build output
  out of the vendored source). `InvariantGlobalization` avoids an ICU dependency.
  **Fallible decode:** `Probe.Decode` throws `SofabException` (carrying a
  `SofabError`, same 4 codes as C) — try/catch verdict, class from `.Error`.
  Fields are native `uint`/`int`; float bits via `BitConverter.SingleToUInt32Bits`
  (raw, NaN-preserving). Coverage engine is SharpFuzz (`Fuzz.cs`, devcontainer —
  not compiled by `build.sh`, which builds only the replay driver).
- **zig** — `drivers/zig/driver.zig` built with `zig build-exe`, wiring the
  corelib as the `sofab` module from its `src/root.zig` (root module = driver.zig
  `--dep sofab`; the file-imported `message.zig`'s `@import("sofab")` resolves via
  that dep). Zig 0.16 std.Io: `main(init: std.process.Init)` provides `io`/`gpa`;
  stdin/stdout via `std.Io.File` reader/writer interfaces. Built `-OReleaseSafe`
  so Zig's safety checks (bounds, overflow) stay on as a free sanitizer.
  **Fallible decode:** `Probe.decode` returns `sofab.Error!Probe` (`catch` verdict,
  same 4 error variants as C). Decode is **zero-copy** — `m.s` borrows from the
  input buffer — so the canonical line is emitted before that buffer is freed.
  Coverage front-end is unresolved (PLAN §14): Zig 0.16 exposes no stable
  `std.testing.fuzz`, so `drivers/zig/fuzz.zig` is a placeholder with decode smoke
  tests; coverage-guided fuzzing will likely need libFuzzer via C interop.

## Key decisions (decision log)

- **Separate repo, arena-cloned structure.** Instrumented (sanitizer+coverage)
  vs arena's optimized builds; opposite configs → own repo. See PLAN §2, §11.
- **One coverage pacemaker (C), N differential oracles.** PLAN §3.
- **Purpose-built driver ABI, not the generator CLI.** Persistent + canonical
  diff form, not process-per-input JSON. PLAN §7.
- **The oracle is disagreement, not the crash.** PLAN §1, §6.
- **Name:** `crucible` (`corelib-*` is reserved).
- **2026-07-08 — comparator has no driver registry.** Drivers are passed to
  `comparator.py` as `name:path`; adding a language needs no central edit, only a
  `--driver` flag in `run.sh` (mirrors arena's "impls discovered from output").
- **2026-07-08 — bring up on a minimal schema, not full-scale.** Fastest path to
  a proven loop, canonical form, and comparator. See Deviation 2026-07-08a.
- **2026-07-08 — Rust: capture the corelib's verdict, not the generated API's.**
  The generated Rust `decode` is infallible; testing it verbatim would make Rust
  ACCEPT everything and flood the comparator with codegen-artifact divergences.
  The driver instead reads the corelib's true `feed` result (two-pass), isolating
  wire semantics from the codegen's error-handling gap. The gap itself is logged
  as docs/SOFABGEN.md G-0001 (fix: emit a fallible `try_decode`).
- **2026-07-08 — generated-code weaknesses go to docs/SOFABGEN.md.** Building the
  Rust drivers surfaced four (G-0001 infallible decode; G-0002 std/no-std invalid
  UTF-8; G-0003 std/no-std chunked strings; G-0004 no-std silent capacity drop);
  the C++ drivers a fifth (G-0005 infallible C++ decode). Crucible tests corelibs,
  but codegen ships to users, so codegen defects are tracked as generator changes,
  not worked around silently. (Python's generated `decode` *raises* — the
  fallible model G-0001/G-0005 propose for Rust/C++.)
- **2026-07-08 — comparator is crash-isolating.** A driver that dies mid-stream
  (fewer output lines than inputs) is reported as `[CRASH] driver X on input N`
  and the run continues comparing the survivors, instead of aborting the whole
  differential. Necessary once the pacemaker feeds adversarial inputs — a
  crashing implementation (F-0003) is itself a finding, not a harness failure.
- **2026-07-08 — canonical form v1: round-trip re-encoding.** Replaced the v0
  per-field text form with `A <hex(encode(decode(input)))>`. Reason: the full-scale
  message (arrays, nested structs, unions) makes per-field walking in 12 languages
  intractable and error-prone; re-encoding the decoded value is schema-agnostic
  (drivers reference no fields) and identical across the family because the
  encoders are sparse-canonical (the arena reference-wire invariant). Also gives
  the round-trip oracle for free. Tradeoff (benign masking of encode-equivalent
  differences) recorded in `oracle/canonical.md`. This is what surfaced F-0002.
- **2026-07-08 — Python: build the Cython extension per interpreter.** The
  prebuilt `_speedups.so` is version-specific; a mismatched CPython silently falls
  back to pure, so "cython" mode would be a false label. build.sh compiles the
  extension for the venv's interpreter and asserts `sofab.IMPL` matches the
  requested mode.

## Deviations from PLAN

### 2026-07-08a — Phase 1 used a minimal `probe` schema (RESOLVED in Phase 3)
- **PLAN says:** the fuzzed message is the "full scale" message (every width,
  arrays, nested structs, unions, unicode) — PLAN §13/§14.
- **Phase 1–2:** shipped a 4-field `probe` (u32/i32/fp32/string) to prove the
  loop, driver ABI, canonical form, and comparator without the full canonical-form
  surface area.
- **Resolved (Phase 3):** `schema/probe.sofab.yaml` is now the full-scale message
  (8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays,
  string array). The switch to the round-trip canonical form (decision
  2026-07-08) made this a **schema+seeds-only change with zero driver edits** —
  the drivers reference no fields. Loop green across all 12 drivers on 6
  full-scale seeds. Kept the message key `probe` so generated type names are
  stable. Unions are the one full-scale feature not in this message (the family's
  full-scale example has none); add a union corpus def in a later Phase-3 step.

### 2026-07-08b — absent/default/value collapsed to two states
- **PLAN says:** canonical form distinguishes *absent* / *present-but-default* /
  *value* (PLAN §7).
- **Reality:** the C object API and Go visitor API both materialize values with
  the schema default for omitted fields; on the sparse-canonical wire
  `absent == default`, so the two are equal and indistinguishable. Canonical form
  emits the value (default when absent).
- **Why:** both Phase-1 decoders are value-materializing; neither tracks presence.
- **Impact:** documented in `oracle/canonical.md`. When a presence-tracking
  decoder joins, the canonical form gains a presence marker and the comparator
  learns cross-model compatibility. No PLAN revision — PLAN §7's three-way
  distinction remains the target for models that support it.

### 2026-07-08c — C libFuzzer pacemaker not built in the bare workspace
- **PLAN says:** C pacemaker built with libFuzzer + sanitizers (PLAN §3, §12).
- **Reality:** the bare workspace has gcc but no clang, so only the gcc replay
  driver (with ASan/UBSan) is built/verified here. The libFuzzer front-end exists
  in `driver.c` behind `CRUCIBLE_LIBFUZZER` and builds in the devcontainer.
- **Why:** libFuzzer is a clang/LLVM feature; the devcontainer ships clang.
- **Impact:** none to the differential loop (which runs on the replay drivers).
  Coverage-guided pacemaker runs live in the devcontainer/CI.

### Pacemaker (as built)

`scripts/fuzz.sh` builds the C driver's `CRUCIBLE_LIBFUZZER` entry with clang
(`-fsanitize=fuzzer,address,undefined`) and runs it, seeded from `corpus/seeds` +
`corpus/interesting` + the findings reproducers; new coverage-increasing inputs
grow `corpus/interesting/`, crashes land in `corpus/crashes/`. Measured ~41k
exec/s, ~1M runs in 26s. It only decodes (coverage over the C decoder); the
discovered inputs then go through the differential loop
(`CORPUS=corpus/interesting ./scripts/run.sh`) where decode+re-encode across all
12 drivers finds the divergences. On its **first** run over 309 discovered inputs
it produced F-0003 (2 crashes) and a large divergence cluster dominated by F-0004
(string UTF-8) and F-0001 (truncated input) — findings 8 hand-seeds never reached.

Needs clang + `libclang-rt-dev` (in the devcontainer image); the comparator
(`oracle/comparator.py`) is **crash-isolating** — a driver that dies mid-stream is
reported as `[CRASH] driver X on input N`, not a bare harness abort, so the
pipeline survives a crashing implementation.

## First finding

The Phase-1 loop found **F-0001** on its first run: a truncated trailing varint
(`80`, `ff ff ff`). Phase 2 grew it to a **7-accept vs 5-reject camp split** — the
C/C++/Rust/Java/C# camp (c-cpp, cpp, c-cpp wrapper, rs, rs-no-std, java, cs)
accepts it as the all-defaults message; **four independent lineages — Go, Python
(cython and pure), TypeScript, and Zig — reject it**. Real, hand-verified against
all twelve drivers. Notably Zig (a systems language) rejects while C/C++/Rust
accept, so the split is per-decoder-design, not systems-vs-managed. Four
unrelated implementations rejecting is strong evidence the lenient camp is wrong —
exactly the pressure the PLAN §8 spec decision needs.
See `results/FINDINGS.md` and `findings/F-0001-truncated-trailing-varint/`.
