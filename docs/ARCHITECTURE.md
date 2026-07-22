# Crucible — Architecture (living document)

> **Status: Phases 1–3 largely done** — the differential loop runs across all thirteen
> drivers / eleven corelibs (C pacemaker, Go, Rust-std, Rust-no-std, C++, C++/c-cpp,
> Python-Cython, Python-pure, Java, TypeScript, C#, Zig, **Dart**) over the full-scale
> `probe` schema. Phase 3 is built (structure-aware mutator, round-trip + cross-encode
> oracles, three-valued verdict `A`/`I`/`R`, schema scale-up); Phase 4 (CI) is
> wired — see [`CI.md`](CI.md). This describes
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
| `scripts/bootstrap.sh` | changed | **Always current**: fetches every cloned corelib to `origin/main` and installs the **latest green sofabgen CI build** — the platform binary the generator's `ci.yml` attaches to every successful run on `main` (sha256-verified against the `.sha256` shipped alongside it in the artifact). This is fresher than the tagged-release cadence and carries merged-but-unreleased backends (it is how the Dart target became usable in Crucible before any sofabgen release — see Deviation 2026-07-22a). Downloading a workflow-run artifact needs auth, so a token with `actions:read` on `sofa-buffers/generator` is resolved from `SOFABGEN_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN`/`gh auth token`; when none is available, or the artifact is missing, bootstrap **falls back — loudly — to the latest published release** (never silently, so the run always states which build it installed). Symlinked sibling `../corelib-*` checkouts are left alone (live working copies), and a *dirty* vendored checkout is warned about, never reset — the script must not silently destroy a corelib patch under test. `SOFABGEN_VERSION=vX.Y.Z` pins a release (reproduce an old finding), `=main` builds from source (needs Go), `SOFABGEN_RUN=<id>` pins a specific CI run, `SOFABGEN_ARTIFACT=<name>` overrides the artifact name, `SOFABGEN_CI_REQUIRED=1` hard-fails instead of falling back, `NO_FETCH=1` goes offline. **Deliberately no skip-if-present shortcut**: a silently stale toolchain already produced a wrong claim once (a vendored sofabgen sat at 0.15.2 while findings were re-verified "on 0.16.1" — STATUS.md), and a differential fuzzer that misreports which versions it compared is worse than a slow one. |
| `schema/probe.sofab.yaml` | built | **Full-scale** message (Phase 3): 8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays, string array. Still keyed `probe` (stable type name). |
| `schema/probe-union.sofab.yaml` | built | `probe` message carrying a **union** (`choice`: `as_u16`/`as_i32`/`as_text`/`as_blob`) between a scalar `tag` and `trailer` — the one wire feature the full-scale `probe` lacks. Drives `scripts/run-union.sh`. |
| `drivers/common/CONTRACT.md` | built | Persistent length-prefixed protocol + canonical output. |
| `drivers/c/` (pacemaker) | built | gcc replay driver (ASan/UBSan) verified; libFuzzer front-end present, `#ifdef CRUCIBLE_LIBFUZZER`, built in devcontainer (no clang in bare workspace). |
| `drivers/go/` | built | Replay driver + native `FuzzProbe`; builds against vendored corelib-go via `replace`. |
| `oracle/canonical.md` | built | v2 canonical form: round-trip re-encoding, three-valued verdict `A`/`I`/`R` (§7). |
| `oracle/materialized.md` | built | Second canonical form (element-access oracle): `SOFAB_MATERIALIZE=1` makes a driver emit a full walk of the **decoded value** (every field + array element, floats as raw bits, `len:hex` strings/blobs) as its `A` payload — targeting the round-trip form's recorded blind spot (a decode that differs only where the sparse wire elides). Reuses the comparator (`accept_value` axis) unchanged. Grammar + wiring spec; **all 13 drivers implement it**. |
| `engine/structured/schema.py` | built | The **generated schema-type table**: parses `schema/probe.sofab.yaml` into a language-neutral typed field tree (kinds `u`/`s`/`fp32`/`fp64`/`string`/`blob`/`struct`/`array`/`wrapper`, ids, counts, nesting) — the schema-type info a value walk needs but the wire does not carry (the C driver gets it free from sofabgen's object descriptor; this derives it for everyone else from the one schema source). `--json` writes the artifact. |
| `oracle/materialized-schema.json` | built | The committed artifact `schema.py` emits — the schema-type table drivers/tools consume without re-parsing YAML. `materialize.sh` regenerates + `cmp`-checks it each run so it cannot drift from the schema. |
| `engine/structured/materialize.py` | built | The materialized-form **reference / ground truth**, now **driven by the generated schema descriptor** (`schema.py`) — no hardcoded message shape; only gen.py's value-vector key convention remains. Models `decode(encode(msg))` (fill-to-N arrays, wrapper grown to max-index+1, scalar ±0.0 normalized). Every driver's `SOFAB_MATERIALIZE` output must equal it byte-for-byte. `--driver PATH` runs a driver binary over `corpus/structured` and diffs it (the per-driver acceptance gate); `--check DIR` compares a dump dir. |
| `scripts/materialize.sh` | built | Runs the materialized differential over the **full 13-driver roster** with `SOFAB_MATERIALIZE=1`, over `corpus/structured` — **75×13 → 0 divergences** (agreement) **+ a C-anchor conformance check** vs the reference (a family-wide-wrong dump is agreement-green, conformance-red). **A standing CI gate** (`replay.yml`); exports `SOFAB_MATERIALIZE_SCHEMA` for the descriptor-driven drivers. **Every walker is schema-agnostic:** C (sofabgen object descriptor); **go/ts/java/cs/python** consume the generated `materialized-schema.json` at runtime (reflection); **rust/cpp/zig** — no runtime reflection — instead **generate their walker source at build time** from the descriptor (`drivers/<lang>/materialize_gen.py`, run by `build.sh`, unrolling the descriptor into straight-line access code). A schema change reflows to all 13 with zero hand-editing. |
| `oracle/comparator.py` | built | N-way canonical diff, policy-aware, no external deps; parses `A`/`I`/`R`. **Crash- and hang-isolating:** a per-driver wall-clock budget (`--timeout`, default `max(30s, 0.25s × corpus)`; `TIMEOUT=` env via the scripts) via stdout-to-tempfile, so an adversarial input that hangs a driver is localized + reported `[TIMEOUT]` (a DoS finding), not a wedged run. `read_corpus` skips `*.md` + dotfiles so a corpus dir can carry a README (inputs can't be selected by extension — libFuzzer names files by content hash); this also stops the `.gitkeep` in the gitignored corpora being fed as an empty message. |
| `oracle/policy.yaml` | built | Permissive Phase-1 policy (verdict/accept_value hard, incomplete_value/reject_class soft). |
| `scripts/run.sh` | built | Build all drivers → differential compare over a corpus (crash-isolating). |
| `scripts/run-union.sh` | built | Union suite: `SCHEMA=schema/probe-union.sofab.yaml CORPUS=corpus/union run.sh` — points the differential + round-trip oracles at a `probe` message carrying a 4-variant union. Drivers are schema-agnostic (round-trip form), so only the generated types change; `drivers/c/build.sh` made SCHEMA-aware to match the other 8. 11 seeds × 13 drivers, 0 divergences — the `union` wire feature `probe` lacked, now covered. |
| `scripts/run-limits.sh` | built | Limit-mode loop (crucible#10 / generator#102): heap roster built from `schema/probe-dyn.sofab.yaml` with identical `max_dyn_*` caps, compared per dimension over `corpus/limits/{arr,str,blb}`. Full heap roster (incl. cpp) in all three dimensions since sofabgen 0.16.1 fixed G-0009. |
| `scripts/fuzz.sh` | built | The C pacemaker: build the libFuzzer target (clang) + run + grow corpus/interesting. |
| `oracle/cluster.py` | built | Groups divergences by camp-partition into root causes (`CLUSTER=1 ./scripts/run.sh`); 256 divergences → 47 clusters. |
| C pacemaker (libFuzzer) | built | `drivers/c/driver.c` `CRUCIBLE_LIBFUZZER` path; ~41k exec/s; grows the corpus fed to the differential loop. Coverage-guided but NOT yet structure-aware. |
| `corpus/seeds/` | built | 6 agreeing seeds (the regression gate); green across all 4 drivers. |
| `corpus/regression/` | built | **Resolved-findings gate** (73 inputs × 13 drivers, 0 divergences): the reproducer of every fixed finding (F-0001/02/03/04/05/06/07/09/10/11/13/14/15/16/17), so a bump that reintroduces one fails CI instead of waiting to be noticed in a manual re-run. Admits an input only when it is green **for the reason the finding is about** — reproducers that also trip an open axis are excluded and listed with their reason in `corpus/regression/README.md`. Runs via the documented `CORPUS=` mechanism (no new script). |
| `engine/structured/isolates.py` | built | Minimal isolates for findings whose *original* reproducer is contaminated (tests two axes at once, so it can never be gate-green). Imports wire primitives from `gen.py` — the one reference encoder — so an encoding change cannot desync them. Emits `corpus/regression/F0003_overcount_clean.bin` (green) and the F-0013 reproducers (diverging → `findings/`). Each isolate declares its own destination. |
| `findings/`, `results/FINDINGS.md` | built | F-0001 recorded (see below). |
| `docs/SOFABGEN.md` | built | Generated-code weakness log (G-0001..G-0007; all fixed in sofabgen 0.15.1). |
| `.devcontainer/` | built | Fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, SharpFuzz, Jazzer.js). |
| `drivers/rust/` (rs + rs-no-std) | built | One shared `driver.rs` for both corelibs; single-pass `try_decode` (see notes). |
| `drivers/cpp/` (cpp + c-cpp) | built | One shared `driver.cpp` for both corelibs; single-pass (feed returns Result). |
| `drivers/python/` (cython + pure) | built | One `driver.py`, both engines of corelib-py via `SOFAB_PUREPYTHON`; fallible decode (try/except). |
| `drivers/java/` | built | Replay driver on the JVM against corelib-java's jar; fallible decode (try/catch); Jazzer coverage target. |
| `drivers/ts/` | built | Node replay driver, esbuild-bundled from corelib-ts source; fallible decode (try/catch); Jazzer.js coverage target. |
| `drivers/cs/` | built | .NET replay driver referencing corelib-cs's built DLL; fallible decode (try/catch); SharpFuzz coverage target. |
| `drivers/zig/` | built | Zig 0.16 replay driver, corelib wired as the `sofab` module. Consumes corelib-zig's finish-less `feed→Status` decode via the generated `DecodeError!Probe` (`.incomplete` → `error.IncompleteMessage` → `I`); coverage target is a placeholder (Zig fuzzing immature). Rebuilt green on sofabgen 0.16.2 (G-0010 fixed). |
| `drivers/dart/` | built | Dart replay driver against corelib-dart (crucible#77 / generator#211, the 10th target). **AOT** (`dart compile exe`, native ELF — never `dart run`/JIT); a pub path-dependency wires the vendored corelib. Status-returning single-pass decode: the generated `Probe.tryDecode(Uint8List, Probe) → DecodeStatus` maps 1:1 to `A`/`I`/`R`/`L` (`limitExceeded`→`L`), with schema-bound violations folded into `invalid` via the generated sticky flag (the Rust/Zig model). Heap profile (growable `List`) → in the limit-mode roster. Materialize walker is **build-time generated** (`materialize_gen.py`, like rust/cpp/zig — no `dart:mirrors` under AOT). Coverage front-end is a placeholder (`fuzz.dart`, not built by `build.sh`) — Dart has no first-party libFuzzer. |
| `engine/mutator/` (structure-aware) | built | `sofab_mutator.{h,c}` — grammar-aware libFuzzer custom mutator (varint truncate/extend/flip/maxout, header type/id, fixlen length, array count, sequence open/close, invalid-UTF-8, fp NaN/inf, field dup). Wired via `LLVMFuzzerCustomMutator` in `drivers/c/driver.c` (~37% byte-mutator mix-in) + `scripts/fuzz.sh`. Pure/testable; `test_mutator.c` soak = 336k mutations, 0 OOB under ASan, deterministic. See DESIGN.md "As built". |
| Round-trip oracle | built | Folded into the canonical form (re-encoding) — found F-0002. |
| Cross-encode oracle | built | `engine/structured/gen.py` emits valid value-rich messages → `corpus/structured/` (green gate); `scripts/cross-encode.sh` runs the round-trip+decode-agreement oracle over them. Realizes cross-encode via the byte-canonical invariant (all encoders identical → agreement = "encode in A decode in B"). Found F-0009 (blob, slice 1) + F-0010 (under-count array, slice 2) on first runs. Slice 2 covers the numeric arrays (id 100) + string_array (id 200) value space; green gate = 69 inputs. |
| CI (`image`, `replay`, `nightly`) | in progress | `.github/workflows/` authored (Phase 4, docs/CI.md): `image.yml` builds the 12-toolchain devcontainer image → GHCR; `replay.yml` (blocking, push/PR) runs the **five** green gates (seeds + **regression** + structured + **union** + limits — union was green since 2026-07-16 but had never been wired in); `nightly.yml` fuzzes → clusters → uploads. Needs a one-time manual `image` run to seed GHCR, then it's live. Each gate rebuilds the drivers (build-reuse is an open follow-up in [`TODO.md`](TODO.md); adding two gates made that cost 5× rather than 3×). |

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
changes) and folds in the round-trip oracle. Verified: all 13 drivers emit
byte-identical hex for the seed corpus (e.g. `02_basic → A 002a090d12200000c03f1a126869`).

**v2 (added, built) — materialized value form** (`oracle/materialized.md`,
the element-access oracle). The round-trip form has a *recorded* blind spot
(`canonical.md` §Tradeoff): two decoders holding different in-memory values that
re-encode to the same sparse-canonical bytes are masked (F-0010's class — the
sparse wire elides trailing default runs / omitted fields). Under
`SOFAB_MATERIALIZE=1` a driver instead emits `A <dump(decode(input))>` — a full
walk of the decoded value, every field and every array element explicit, floats as
raw bit patterns, strings/blobs as `len:hex`. This is PLAN §7's original per-field
form, resurrected as a *second, added* oracle (not a replacement — round-trip stays
the default and the schema-agnostic path). It is **not schema-agnostic**: it needs
schema-type info (fp32-vs-fp64, count N) the round-trip got free from the encoder —
generic via C's object descriptor, a schema-type table elsewhere. **Measured caveat
(steers the whole design):** every corelib already materializes a fixed-count
*numeric* array to its full N in memory (the wire count M is reconstructed only at
encode time by the trim heuristic), so this form is uniform there today; its live
signal is the **wrapper arrays** (`string_array`/`blob_array`, genuinely dynamic),
**element-level fidelity**, and **regression-proofing**. **All 13 drivers** implement
it, **all schema-agnostic** — C via the object descriptor, go/ts/java/cs/python by
consuming the generated `materialized-schema.json` at runtime, rust/cpp/zig by
generating their walker source from the descriptor at build time: **75×13 → 0
divergences**, all matching the
`engine/structured/materialize.py` reference byte-for-byte, with the default round-trip
path unchanged. One surfaced nuance: the **Go** corelib leaves an absent numeric array
`nil` rather than filling to N in memory, so its driver pads to N for the dump (the
logical fill-to-N value is identical — benign; noted, not a finding).

### Limit mode (as built)

`scripts/run-limits.sh` (crucible#10 / generator#102) exercises the receiver-side
decode caps (`max_dyn_array_count` / `max_dyn_string_len` / `max_dyn_blob_len`),
which bind only schema-*unbounded* fields. It uses a dedicated unbounded schema
`schema/probe-dyn.sofab.yaml` (one count-less array, one maxlen-less string, one
maxlen-less blob) and a **heap-only** roster — the fixed-capacity profiles (c,
c-cpp, rust-nostd) cannot represent an unbounded field, so they are out by
construction. Each driver's `build.sh` takes `SCHEMA` + `LIMITS` from the
environment and bakes the **same** caps into every driver, so a disagreement on
`A` (under cap) vs `L` (LIMIT_EXCEEDED, over cap) is a real verdict finding — the
fourth canonical verdict `L` (`oracle/canonical.md`) exists only here.

The corpus is split by dimension (`corpus/limits/{arr,str,blb}`) so the roster
*can* differ per dimension, but since **sofabgen 0.16.1** the **full heap roster
(incl. cpp) runs all three dimensions**. Previously the **arr** dimension dropped
**cpp** (G-0009 / generator#112 — sofabgen 0.16.0 emitted its unbounded array as
`std::array<T,0>`, so an accepted array decoded to empty; the cap itself still
fired); 0.16.1 (commit `7899c4b`) makes it a `std::vector`, and cpp now agrees on
the arr vectors (re-verified 2026-07-15). Verified green: arr 3×9, str 2×9,
blb 2×9, 0 divergences. rust-std gained the `L` arm behind a `limit` cargo feature
(`drivers/rust/build.sh` enables it for the std variant only; rs-no-std's `Error`
has no `LimitExceeded`).

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
  `go test -fuzz=FuzzProbe`; module resolves corelib-go via a `replace`. (The old
  **G-0006 workaround** — injecting a missing `"bytes"` import into the generated
  `types.go` — was removed once G-0006 was fixed in sofabgen 0.15.1; see
  docs/SOFABGEN.md.)
- **rust (rs + rs-no-std)** — one shared `drivers/rust/driver.rs` builds against
  BOTH corelibs; `build.sh <rs|rs-no-std>` selects the vendored crate and
  prepends a per-variant `Probe` import (`mod message` for std, the lib crate
  `sofabuffers_generated` for no-std). Registered as two separate drivers
  (`rust-std`, `rust-nostd`) — they are two implementations to compare.
  **Single-pass decode:** the driver calls the generated fallible
  `Probe::try_decode(&[u8]) -> Result<Probe, sofab::Error>` (sofabgen 0.16.0,
  G-0001 fix) — `Ok`→`A <hex>`, `Err(Incomplete)`→`I`, else `R <class>`. This
  replaced the earlier two-pass workaround (value from the infallible
  `Probe::decode` + verdict from a null-visitor `feed`), which the fallible
  `try_decode` made unnecessary. Because `try_decode` runs the real generated
  visitor, rust now runs the generated per-field checks the null-visitor pass
  skipped — e.g. the over-count-array check (F-0003 / generator#100, **fixed in
  sofabgen 0.16.1** `ca0fda7`: re-verified 2026-07-15 that a clean non-truncated
  over-count array → rust `R`, agreeing with the family). Reject
  class maps `sofab::Error` (same 4 codes as C's `sofab_ret_t`; the std corelib
  additionally has `LimitExceeded`, used only in limit mode). Coverage engine is
  cargo-fuzz (libFuzzer; devcontainer). The
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
  **Status-returning single-pass decode:** the generated
  `DecodeStatus Probe.tryDecode(byte[], Probe)` (sofabgen 0.16.0, G-0008 fix) fills
  the message and returns the §7 status — `INCOMPLETE`→`I`, `COMPLETE`→`A`, and a
  thrown `SofabException`→`R` (reject class derived coarsely from the exception).
  This replaced the earlier two-pass G-0008 workaround (a null-visitor `feed` for
  the verdict + `decode` for the value). Fields `u`/`i` are widened to `long` by the
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
  **Status-returning single-pass decode:** `DecodeStatus Probe.TryDecode(byte[],
  out Probe)` (sofabgen 0.16.0, G-0008 fix) fills the message and returns the §7
  status — `Incomplete`→`I`, `Complete`→`A`, and a thrown `SofabException`
  (carrying a `SofabError`, same 4 codes as C)→`R` with class from `.Error`. This
  replaced the earlier two-pass G-0008 workaround (a null-visitor `Feed` verdict +
  `Decode` value). Fields are native `uint`/`int`; float bits via `BitConverter.SingleToUInt32Bits`
  (raw, NaN-preserving). Coverage engine is SharpFuzz (`Fuzz.cs`, devcontainer —
  not compiled by `build.sh`, which builds only the replay driver).
- **zig** — `drivers/zig/driver.zig` built with `zig build-exe`, wiring the
  corelib as the `sofab` module from its `src/root.zig` (root module = driver.zig
  `--dep sofab`; the file-imported `message.zig`'s `@import("sofab")` resolves via
  that dep). Zig 0.16 std.Io: `main(init: std.process.Init)` provides `io`/`gpa`;
  stdin/stdout via `std.Io.File` reader/writer interfaces. Built `-OReleaseSafe`
  so Zig's safety checks (bounds, overflow) stay on as a free sanitizer.
  **Fallible decode (finish-less §7, sofabgen 0.16.2):** the generated
  `Probe.decode` returns `DecodeError!Probe` (`DecodeError = sofab.Error ||
  error{IncompleteMessage}`), binding corelib-zig's `feed(chunk)→Status` and
  returning `error.IncompleteMessage` when the terminal status is `.incomplete`. The
  driver `catch`es: `error.IncompleteMessage`→`I`, `error.LimitExceeded`→`L`, the
  other `sofab.Error` variants→`R <class>`. (This replaced the pre-0.16.2 API where
  INCOMPLETE was `error.Incomplete`; the migration was **G-0010** / generator#120.)
  Decode is **zero-copy** — `m.s` borrows from the input buffer — so the canonical
  line is emitted before that buffer is freed.
  Coverage front-end is unresolved (PLAN §14): Zig 0.16 exposes no stable
  `std.testing.fuzz`, so `drivers/zig/fuzz.zig` is a placeholder with decode smoke
  tests; coverage-guided fuzzing will likely need libFuzzer via C interop.
- **dart** — `drivers/dart/driver.dart` AOT-compiled with `dart compile exe`
  (native ELF; **never** `dart run`/JIT). `build.sh` generates `message.dart`
  (`sofabgen --lang dart`), writes a minimal `pubspec.yaml` with a **path
  dependency** on `vendor/corelib-dart` (the corelib's dev-deps are not fetched
  transitively, so `dart pub get` needs nothing hosted), then compiles. **Fallible,
  status-returning single-pass decode:** `Probe.tryDecode(Uint8List, Probe)` returns
  `sofab.DecodeStatus` — `complete`→`A <hex>`, `incomplete`→`I`, `invalid`→`R
  invalid_msg`, `limitExceeded`→`L` — with schema-bound violations (over-count /
  over-index / over-maxlen) folded into `invalid` by the generated sticky `_Dec.inv`
  flag (the Rust/Zig model). Reject class is coarse (the status carries no finer
  code; soft axis). Dart is a **heap** profile (growable `List<...>`), so it joins the
  limit-mode roster and its generated `tryDecode` bakes the `max_dyn_*` caps into a
  `DecoderLimits`. The driver reads the whole framed stdin stream then emits all
  lines (the comparator writes-all-then-reads; the TS pattern). **Materialize
  (`SOFAB_MATERIALIZE=1`)** uses a **build-time-generated walker**
  (`materialize_gen.py` → `materialize_gen.dart`, regenerated every build) because
  AOT Dart has no `dart:mirrors` — the rust/cpp/zig camp. Dart type care: fp32 stored
  as a 64-bit `double` is repacked to the 32-bit pattern, fp64 printed as two uint32
  halves, and **u64** (signed 64-bit `int`) is reinterpreted unsigned via `BigInt`.
  Coverage engine is a placeholder (`fuzz.dart`, not built by `build.sh`): Dart has no
  first-party libFuzzer, and the intended dart:ffi + C-libFuzzer path (like Zig) is
  unresolved (PLAN §14).

## Key decisions (decision log)

- **2026-07-18 — drivers build with strict UTF-8 ON (F-0004 / crucible#55).** The
  fuzzer runs the §8 `SOFAB_STRICT_UTF8` check ON so an invalid-UTF-8 `string` is
  rejected family-uniformly. Most drivers are strict by default (go/zig/cpp default
  ON; py/ts/java/cs/rs Unicode types always strict); the **C corelib defaults OFF**
  for footprint, so the two corelib-c-cpp-based drivers opt in: `drivers/c/build.sh`
  and `drivers/cpp/build.sh` (`c-cpp`) add `-DSOFAB_ENABLE_STRICT_UTF8` and compile
  `corelib-c-cpp/src/utf8.c` (defines `sofab_utf8_valid`). The **zig** driver builds
  the corelib as a bare module with `zig build-exe` (no `build.zig`), so it
  synthesizes the `build_options` module corelib-zig's `utf8.zig` imports
  (`strict_utf8 = true`). Seeds: `engine/structured/utf8_seeds.py`.
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
  The generated Rust `decode` was infallible; testing it verbatim would make Rust
  ACCEPT everything and flood the comparator with codegen-artifact divergences.
  The driver originally read the corelib's true `feed` result via a two-pass
  (null-visitor verdict + `decode` value), isolating wire semantics from the
  codegen's error-handling gap (docs/SOFABGEN.md G-0001). **Superseded
  2026-07-14 (crucible#10):** G-0001 is fixed — the driver is now single-pass on
  the fallible `try_decode`, which surfaces the verdict directly *and* runs the
  real generated per-field checks the null-visitor pass had skipped (e.g. the
  over-count-array check; F-0003 / generator#100 — **fixed in sofabgen 0.16.1**,
  re-verified 2026-07-15: clean over-count array → rust `R`).
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
- **2026-07-15 — comparator is hang-isolating (per-driver timeout).** Companion to
  crash isolation: a per-driver wall-clock budget (`--timeout`, default
  `max(30s, 0.25s × corpus size)`; `TIMEOUT=` env through `run.sh`/`run-limits.sh`).
  `run_driver` sends the driver's stdout/stderr to temp files (not pipes) so that on
  a `subprocess` timeout — which on POSIX does *not* carry the killed process's
  partial output — the flushed lines are still recovered; the culprit is the input
  at index `len(lines)`, reported `[TIMEOUT] driver X hung … culprit ≈ input N`.
  `cluster.py` recovers past it exactly like a crash. A driver that takes unbounded
  time on a small malformed input is a **DoS finding**, not a wedged run (the
  gap the structure-aware mutator surfaced: maxed array counts / deep nesting made
  the replay loop crawl). Precision note: exact for flush-per-line drivers; a
  slurp-then-emit driver (ts) yields 0 partial lines, so it reports "hung, produced
  0/N" without a precise index — bisection to localize those is a follow-up.
- **2026-07-08 — canonical form v1: round-trip re-encoding.** Replaced the v0
  per-field text form with `A <hex(encode(decode(input)))>`. Reason: the full-scale
  message (arrays, nested structs, unions) makes per-field walking in 12 languages
  intractable and error-prone; re-encoding the decoded value is schema-agnostic
  (drivers reference no fields) and identical across the family because the
  encoders are sparse-canonical (the arena reference-wire invariant). Also gives
  the round-trip oracle for free. Tradeoff (benign masking of encode-equivalent
  differences) recorded in `oracle/canonical.md`. This is what surfaced F-0002.
- **2026-07-13 — canonical form v2: three-valued verdict (`A`/`I`/`R`).** Added a
  third verdict line `I` (INCOMPLETE) alongside `A`/`R`, tracking the finish-less
  MESSAGE_SPEC §7 decode model (documentation PR #12). Truncated input is
  INCOMPLETE — a distinct, non-error outcome — not accept and not reject. Touched
  the canonical-form triad together (the CLAUDE.md invariant): the grammar +
  three-verdict table in `oracle/canonical.md`, the `parse()`/compare logic in
  `oracle/comparator.py` (new `incomplete_value` axis, soft), and the driver
  contract in `drivers/common/CONTRACT.md`. `policy.yaml` gains
  `incomplete_value: soft` and resolves the PLAN §8 truncated-input question
  (SPECIFIED as INCOMPLETE). Drivers emit `I` only once their corelib exposes the
  state (generator#86 + per-corelib issues); until then F-0001 stays red — the
  correct signal. Verification tracked in crucible#8. See Deviation 2026-07-13a.
- **2026-07-08 — Python: build the Cython extension per interpreter.** The
  prebuilt `_speedups.so` is version-specific; a mismatched CPython silently falls
  back to pure, so "cython" mode would be a false label. build.sh compiles the
  extension for the venv's interpreter and asserts `sofab.IMPL` matches the
  requested mode.
- **2026-07-16 — the regression corpus admits an input only when it is green *for
  the reason the finding is about*.** The tempting rule is "a finding is fixed →
  its reproducer joins the gate." That is wrong here, because several reproducers
  are raw fuzzer inputs that trip **two** axes: F-0003's `array_overflow.bin` is
  over-count *and* truncated, F-0008's `hang_min.bin` is over-index *and*
  truncated. Both findings are fixed, yet both inputs still split the family on the
  *open* INVALID-vs-INCOMPLETE precedence hole (documentation#15). Admitting them
  would force a choice between a red gate and a policy exception that mutes a real
  open divergence. So a contaminated reproducer stays in `findings/` and the gate
  gets a **clean isolate** (`engine/structured/isolates.py`) testing the one axis —
  the F-0004 lesson ("characterize with a minimal isolate, not a raw fuzzer input")
  applied to the gate. Corollary: **never weaken the gate to admit an input.** The
  exclusions and their reasons are listed in `corpus/regression/README.md`, so an
  excluded reproducer is visibly deferred rather than silently forgotten.

## Deviations from PLAN

### 2026-07-22b — Dart added as the 11th corelib / 13th driver (roster 12→13)
- **PLAN says:** `drivers/` lists c/rust/go/java/python + cpp/cs/ts/zig (PLAN §11);
  onboarding a new language follows the §13 checklist.
- **Change:** `drivers/dart/` added (crucible#77 / generator#211, sofabgen's 10th
  language target). Roster is now **13 drivers / 11 corelibs**. Registered in every
  suite: `run.sh` (seeds/regression/cross-encode/union), `run-limits.sh` (heap
  roster), `engine/structured/sweep_run.py` (structural sweep), `materialize.sh`
  (element-access). No PLAN revision — this is the §13 checklist executed; PLAN's
  "N drivers" abstraction is unchanged.
- **Why it slots in cleanly:** the schema-agnostic round-trip form means the replay
  driver needs zero per-field code; the generated `Probe.tryDecode → DecodeStatus`
  maps 1:1 to `A`/`I`/`R`/`L`. Only the materialized oracle needs schema knowledge,
  supplied by a build-time-generated walker (AOT Dart has no `dart:mirrors`).
- **AOT, never JIT** — the suite runs the native `dart compile exe` binary, not
  `dart run`/VM (operator constraint).
- **CI:** the gates invoke the scripts (which carry Dart), so **no per-gate edit**;
  the CI image already installs the Dart SDK (`.devcontainer/Dockerfile`), so it only
  needs the standing one-time `image.yml` rebuild to carry it into `replay`/`nightly`.
- **Result:** all suites green — seeds 6×13, regression 73×13, cross-encode 75×13,
  union 11×13, limit mode (arr/str/blb) 10-heap-driver roster, structural sweep
  (5 blocking axes), materialized 75×13. No
  Dart-attributable finding. (One Crucible-side walker bug found+fixed during
  Stage 4; one toolchain-bump side-result: F-0025 now resolved on the CI build.)

### 2026-07-22a — bootstrap installs the latest sofabgen *CI build*, not the latest *release*
- **PLAN/prior as-built:** `scripts/bootstrap.sh` installed the latest published
  sofabgen **release** binary (checksum-verified) — see the `bootstrap.sh` row above
  as it was before this entry.
- **Change:** bootstrap now installs the binary the generator's `ci.yml` attaches to
  its latest **green run on `main`** (still sha256-verified, via the `.sha256` shipped
  in the same artifact). The tagged-release path is preserved but demoted to an
  explicit opt-in (`SOFABGEN_VERSION=vX.Y.Z`); it is also the **loud fallback** when no
  cross-repo token is present or the artifact is missing, so the tree never wedges and
  every run says which build it used.
- **Why:** the release cadence lagged behind merged generator work. The trigger was
  **Dart** (crucible#77): `corelib-dart` + the `dart` backend (generator#211) landed on
  generator `main` and CI began attaching a `dart`-capable `sofabgen` (target list now
  `…|dart|…`) and a `generated-dart` artifact — but no *release* carried it yet. Pulling
  the CI build lets Crucible exercise the newest family members as they merge, which is
  the whole point of a conformance fuzzer, without pinning to an *unmerged* PR (rejected
  — that would violate the "never lie about what it compiled" invariant).
- **Cost / caveat:** workflow-run artifacts are not anonymously downloadable, so CI needs
  a PAT secret (`SOFABGEN_TOKEN`, `actions:read` on `sofa-buffers/generator`) — wired into
  `replay.yml`/`nightly.yml`; absent it, CI degrades loudly to the latest release. CI
  builds carry a pseudo-version (`0.0.0-<ts>-<sha>`) rather than a semver tag.

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
  full-scale example has none) — **covered separately** via
  `schema/probe-union.sofab.yaml` + `scripts/run-union.sh` rather than folded into
  `probe` (keeping the main message's type names stable). The schema-agnostic
  round-trip form pays off again: pointing the oracles at the union schema needs
  only a rebuild, no driver edits. All 12 backends generate + agree on every
  variant and the one-of/unknown-member edge cases — green, no finding.

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

### 2026-07-13a — canonical verdict is three-valued (`A`/`I`/`R`), not binary
- **PLAN says:** the canonical form's verdict axis is accept-vs-reject (PLAN §6/§7
  frame decode as a binary outcome).
- **Reality:** MESSAGE_SPEC §7 (finish-less, documentation PR #12) makes decode
  three-valued — COMPLETE / **INCOMPLETE** / INVALID — where INCOMPLETE (truncated
  but well-formed-so-far) is an explicit non-error outcome. The canonical form
  gained a third line `I` (`oracle/canonical.md` v2), the comparator a third
  verdict + a soft `incomplete_value` axis, and the driver contract an `I`
  mapping.
- **Why:** collapsing INCOMPLETE into accept (`A`) or reject (`R`) is exactly the
  F-0001 bug; the loop cannot verify the family's convergence on INCOMPLETE
  without a distinct verdict for it.
- **Impact:** verdict comparison now ranges over `A`/`I`/`R` (all hard). Drivers
  emit `I` only after their corelib exposes INCOMPLETE (generator#86 +
  per-corelib issues); until then their `A`/`R` on a truncated seed is a real
  verdict divergence. No PLAN revision needed — this refines §7's outcome model to
  match the now-settled spec. Verification: crucible#8.

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

### Clustering (as built)

`oracle/cluster.py` (`CLUSTER=1 ./scripts/run.sh`) reduces the divergence firehose
to root causes: for each divergent input it partitions the drivers into
equivalence classes by identical output, drops the exact bytes, and keys the
cluster by the *shape* (which driver-set landed in each class, with its verdict).
Inputs sharing a shape share a root cause; clusters rank by size with a minimal
representative. It recovers past crashes (re-runs a crashed driver on the
remaining inputs). First run: 256 divergences → 47 clusters, top 12 ≈ 208, mapping
to F-0001/F-0004/F-0005 (+ the F-0003 crash cluster). Snapshot +
finding-mapping in `results/CLUSTERS.md`.

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
