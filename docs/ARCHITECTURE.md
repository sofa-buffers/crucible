# Crucible — Architecture (living document)

> **Status: Phase 2 in progress** — the differential loop runs across eleven
> drivers (C pacemaker, Go, Rust-std, Rust-no-std, C++, C++/c-cpp, Python-Cython,
> Python-pure, Java, TypeScript, C#) over the minimal `probe` schema. This describes
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
| `schema/probe.sofab.yaml` | built | Minimal Phase-1 message (u32/i32/fp32/string). Full-scale deferred (Deviation 2026-07-08a). |
| `drivers/common/CONTRACT.md` | built | Persistent length-prefixed protocol + canonical output. |
| `drivers/c/` (pacemaker) | built | gcc replay driver (ASan/UBSan) verified; libFuzzer front-end present, `#ifdef CRUCIBLE_LIBFUZZER`, built in devcontainer (no clang in bare workspace). |
| `drivers/go/` | built | Replay driver + native `FuzzProbe`; builds against vendored corelib-go via `replace`. |
| `oracle/canonical.md` | built | v0 canonical form. |
| `oracle/comparator.py` | built | N-way canonical diff, policy-aware, no external deps. |
| `oracle/policy.yaml` | built | Permissive Phase-1 policy (verdict/accept_value hard, reject_class soft). |
| `scripts/run.sh` | built | Build all four drivers → differential compare over a corpus. |
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
| `engine/mutator/` (structure-aware) | planned | Phase 3. |
| Round-trip + cross-encode oracles | planned | Phase 3. |
| CI (`replay`, `nightly`) | planned | Phase 4. |
| Drivers: zig | planned | Phase 2 (remaining, last). |

## As-built detail

### Replay driver protocol (as built)

stdin: repeated records `<uint32 little-endian length N><N payload bytes>`; clean
EOF at a record boundary → exit 0. stdout: exactly one canonical line per record,
`\n`-terminated, in input order. stderr: logs only. Implemented identically in
`drivers/c/driver.c` (`main`) and `drivers/go/driver.go` (`main`). The comparator
(`oracle/comparator.py`) frames the whole corpus into one stream per driver and
reads back one line per input.

### Canonical form (as built)

Per `oracle/canonical.md`: `A u=<dec> i=<dec> f=<8 hex, IEEE-754 bits> s=<hex utf-8>`
on accept (fields in ascending schema-id order), `R <class>` on reject. Floats as
raw bits so `-0.0`/NaN/±inf are exact. Verified: valid inputs produce
byte-identical lines from C and Go (e.g. `A u=42 i=-7 f=3fc00000 s=6869`).

### Per-language driver notes (as built)

- **c** — object API (`message_probe_decode`) into a value struct; reject class
  mapped from `sofab_ret_t`. Built with gcc `-fsanitize=address,undefined`.
  libFuzzer front-end guarded by `CRUCIBLE_LIBFUZZER` (clang, devcontainer).
  **Empty-input precondition:** `sofab_istream_feed` asserts `datalen>0` (a debug
  precondition); under `NDEBUG` the same call returns OK with defaults, agreeing
  with Go. The driver treats a 0-byte input as the valid all-defaults message so
  the asserts-on build does not false-abort on a valid empty message, while
  asserts still fire on real bugs for non-empty input.
- **go** — generated visitor decode (`DecodeProbe`) into a value struct; any
  decode error → `R invalid_msg` (coarse; reject-class comparison is soft in
  Phase 1). Native coverage via `go test -fuzz=FuzzProbe`. Module resolves
  corelib-go through a `replace` to `vendor/corelib-go`.
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
- **2026-07-08 — Python: build the Cython extension per interpreter.** The
  prebuilt `_speedups.so` is version-specific; a mismatched CPython silently falls
  back to pure, so "cython" mode would be a false label. build.sh compiles the
  extension for the venv's interpreter and asserts `sofab.IMPL` matches the
  requested mode.

## Deviations from PLAN

### 2026-07-08a — Phase 1 uses a minimal `probe` schema, not the full-scale message
- **PLAN says:** the fuzzed message is the "full scale" message (every width,
  arrays, nested structs, unions, unicode) — PLAN §13/§14.
- **Reality:** Phase 1 ships a 4-field `probe` (u32/i32/fp32/string).
- **Why:** the loop, driver ABI, canonical form, and comparator are the risk in
  Phase 1; a minimal schema proves them end-to-end without the canonical-form
  surface area of arrays/unions/nesting. Scaling the schema is mechanical.
- **Impact:** canonical form (`oracle/canonical.md`) currently specifies only
  scalar + string/blob encodings; arrays/nested/union encodings are added when
  the schema scales (Phase 3). No PLAN revision needed — PLAN §12 Phase 1 only
  requires "end-to-end divergence detection on seeded corpus".

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

## First finding

The Phase-1 loop found **F-0001** on its first run: a truncated trailing varint
(`80`, `ff ff ff`). Phase 2 grew it to a **7-accept vs 4-reject camp split** — the
C/C++/Rust/Java/C# camp (c-cpp, cpp, c-cpp wrapper, rs, rs-no-std, java, cs)
accepts it as the all-defaults message; **three independent lineages — Go, Python
(cython and pure), and TypeScript — reject it**. Real, hand-verified against all
eleven corelibs. Three unrelated implementations rejecting is strong evidence the
lenient camp is wrong — exactly the pressure the PLAN §8 spec decision needs.
See `results/FINDINGS.md` and `findings/F-0001-truncated-trailing-varint/`.
