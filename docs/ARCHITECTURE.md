# Crucible — Architecture (as-built)

> **Status: Phases 1–3 largely done** — the differential loop runs across all fifteen
> drivers / eleven corelibs (C pacemaker, Go, Rust-std, Rust-no-std, **four C++
> configurations** — two corelibs × both `allow_dynamic` settings — Python-Cython,
> Python-pure, Java, TypeScript, C#, Zig, Dart) over the full-scale `probe` schema.
> The roster itself is `drivers/roster`; no driver is currently quarantined, so all
> fifteen run in the blocking gates. Phase 3 is built (structure-aware mutator, round-trip + cross-encode
> oracles, three-valued verdict `A`/`I`/`R`, schema scale-up); Phase 4 (CI) is
> wired — see [`CI.md`](CI.md). This describes the architecture **as actually
> built** (the current, actual state) and *only* that. `PLAN.md` is the intended design
> and stays stable; the **dated record of what changed, why, and where the build
> deviates from PLAN lives in [`STATUS-LOG.md`](STATUS-LOG.md)** — not here.
>
> **Maintenance rule:** every change that alters a component boundary, a
> contract, a build flag, or a data format updates this file in the *same*
> change, so it always matches what exists today. Log the decision and any
> PLAN-deviation in `STATUS-LOG.md`; reflect only the resulting state here.

---

## Component status

Legend: `planned` · `in progress` · `built` · `changed` (differs from PLAN — see Deviations)

| Component | Status | Notes |
|---|---|---|
| `scripts/bootstrap.sh` | changed | **Always current, and branch-matched**: fetches every cloned corelib to the tracked family branch and installs the **latest green sofabgen CI build** of it — the platform binary the generator's `ci.yml` attaches to every successful run (sha256-verified against the `.sha256` shipped alongside it in the artifact). This is fresher than the tagged-release cadence and carries merged-but-unreleased backends (it is how the Dart target became usable in Crucible before any sofabgen release — see Deviation 2026-07-22a). Downloading a workflow-run artifact needs auth, so a token with `actions:read` on `sofa-buffers/generator` is resolved from `SOFABGEN_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN`/`gh auth token`; when none is available, or the artifact is missing, bootstrap **falls back — loudly — to the latest published release** (never silently, so the run always states which build it installed). Symlinked sibling `../corelib-*` checkouts are left alone (live working copies), and a *dirty* vendored checkout is warned about, never reset — the script must not silently destroy a corelib patch under test. **Which branch is tracked:** Crucible's own — `FAMILY_BRANCH` defaults to this checkout's branch (`GITHUB_HEAD_REF`/`GITHUB_REF_NAME` first, since Actions checks out detached), so a family-wide change under review on a same-named branch in every repo (e.g. `poc/omit-all-default-sequences`) is compared against itself, and `main` here means the released family exactly as before. A repo lacking that branch falls back to `main`, announced per repo; each corelib's local branch is moved onto the fetched tip with `checkout -B`, so `vendor/<lib>` never names a branch other than the one it holds. On a **non-main** branch the generator is built from source at that branch when its CI attaches no binary (the `sofabgen-<os>-<arch>` artifacts are published on `main` only) and the release fallback is **suppressed** there: `main` codegen against branch corelibs compares two designs, so every divergence would be an artifact of the mix. `SOFABGEN_VERSION=vX.Y.Z` pins a release (reproduce an old finding), `=source` (older spelling `=main`) builds the tracked branch from source (needs Go), `SOFABGEN_BRANCH=<name>` moves only the generator, `SOFABGEN_RUN=<id>` pins a specific CI run, `SOFABGEN_ARTIFACT=<name>` overrides the artifact name, `SOFABGEN_CI_REQUIRED=1` hard-fails instead of falling back, `NO_FETCH=1` goes offline. **Deliberately no skip-if-present shortcut**: a silently stale toolchain already produced a wrong claim once (a vendored sofabgen sat at 0.15.2 while findings were re-verified "on 0.16.1" — STATUS-LOG.md), and a differential fuzzer that misreports which versions it compared is worse than a slow one. |
| `schema/probe.sofab.yaml` | built | **Full-scale** message (Phase 3): 8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays, string array, blob array, and (WP-05, 2026-07-27, poc family) `struct_array` — the array-of-struct (`{k: u32, v: string}`, id 202) whose elements are sequences, the position the §2/§5.1 sequence-element rules are tested at. Still keyed `probe` (stable type name). |
| `schema/probe-union.sofab.yaml` | built | `probe` message carrying a **union** (`choice`: `as_u16`/`as_i32`/`as_text`/`as_blob`) between a scalar `tag` and `trailer` — the one wire feature the full-scale `probe` lacks. Drives `scripts/run-union.sh` (differential) **and, since WP-01 (2026-07-22), the report-only union pass of the structural sweeps** (`sweep_run.py --union`), which rebuilds the roster against it and back. |
| `drivers/roster` + `scripts/roster.sh` + `oracle/roster.py` | built | **The single source of truth for who is in the family**, one row per driver: name, the `drivers/<builder>/build.sh` that produces it, that script's variant argument, membership tags, and the built binary. Shell consumers go through `roster.sh` (`list` / `build [tag]`, which builds each entry and prints the comparator's `--driver name:path` arguments, and **`caps {encode|chunked}`**, which reports the entries whose `drivers/<builder>/meta` declares the capability); Python consumers through `roster.py`. **The two streaming gates derive their participant list through `caps` rather than carrying one** (since 2026-08-16): a hand-written list is how `go` stayed outside the encode gate for eleven days, because a missing name is indistinguishable from a declared exception. Staying out now requires a `meta` that denies the capability. It exists because the list had been **copied into five places** (`run.sh`, `materialize.sh`, `run-limits.sh`, `sweep_run.py`, `chunk_invariance.py`) and adding the two C++ configurations would have meant editing six lists — the exact shape CLAUDE.md's single-source rule warns about. Two tags: `limits` selects the limit-mode subset (a heap profile whose corelib reports `LIMIT_EXCEEDED`), and **`blocking` selects what the CI gates run**. A driver without `blocking` is **quarantined** — still built, still exercised by `ROSTER_TAG=` (the full roster) and by a manual or nightly pass, but kept out of the gates that block. Quarantine exists for the reason `results/known-clusters.txt` does: a permanently red gate stops meaning "something new broke". Every quarantine entry names the finding that justifies it, so it can be lifted the moment that finding closes. |
| `drivers/common/CONTRACT.md` | built | Persistent length-prefixed protocol + canonical output. Since 2026-08-04 it additionally **specifies the two streaming axes** the generated API exposes and the replay protocol cannot otherwise reach — chunked decode (`SOFAB_SPLIT`, `SOFAB_CHUNK`, `SOFAB_CHUNK_SCRUB`) and streaming encode (`SOFAB_ENCODE`, `SOFAB_FLUSH`) — including the normative rule that the chunked verdict is derived **the way the one-shot path derives it**: from the decoder's `status` where one exists, and from `finish()` only where that is the sole terminal check *and* returns the same three-valued outcome the one-shot path returns (Rust and C, whose generated decoders have no `status` at all — crucible#132's API table overstates this). Routing through `finish()` elsewhere would bake a backend difference into the canonical line: most throw mid-field, Dart returns null. Three `meta` keys, `chunked_decode`, `encode_surfaces` and `min_output_buffer`, record per backend what exists to be driven — the second is read by `encode_invariance.py` to decide which surfaces to compare and which must hard-fail, the third (§5.1) to size the flush sweep. **The specification, both oracles and all fourteen drivers are complete.** Which drivers a gate runs is declared in the two gate scripts, their own owner — a driver may be held out of one while a finding it exposes is open (zig on chunked for F-0058, py-pure on encode for F-0059) without leaving the other. A backend that cannot honour a setting exits **3** and the gate reports it inapplicable rather than as a pass: zig borrows a whole-chunk payload by design so `SOFAB_CHUNK_SCRUB` cannot test it, and python cannot alias at all so it cannot either. On the encode side exit 3 is no longer a skip — §5.1 makes every swept flush size one the port declared it accepts, so a refusal there is a failure (see the `encode_invariance.py` row). |
| `drivers/c/` (pacemaker) | built | gcc replay driver (ASan/UBSan) verified; libFuzzer front-end present, `#ifdef CRUCIBLE_LIBFUZZER`, built in devcontainer (no clang in bare workspace). |
| `drivers/go/` | built | Replay driver + native `FuzzProbe`; builds against vendored corelib-go via `replace`. |
| `oracle/canonical.md` | built | v2 canonical form: round-trip re-encoding, three-valued verdict `A`/`I`/`R` (§7). |
| `oracle/materialized.md` | built | Second canonical form (element-access oracle): `SOFAB_MATERIALIZE=1` makes a driver emit a full walk of the **decoded value** (every field + array element, floats as raw bits, `len:hex` strings/blobs) as its `A` payload — targeting the round-trip form's recorded blind spot (a decode that differs only where the sparse wire elides). Reuses the comparator (`accept_value` axis) unchanged. Grammar + wiring spec; **every driver in the roster implements it**. |
| `engine/structured/schema.py` | built | The **generated schema-type table**: parses a `*.sofab.yaml` into a language-neutral typed field tree (kinds `u`/`s`/`fp32`/`fp64`/`string`/`blob`/`struct`/`union`/`array`/`wrapper`/`struct_wrapper`, ids, counts, nesting; the `struct_wrapper` kind (WP-05) models array-of-struct — live since 2026-07-27, when `struct_array` (id 202) joined `probe`: every walker (5 runtime, 4 generated, plus the reference `materialize.py`) implements it) — the schema-type info a value walk needs but the wire does not carry (the C driver gets it free from sofabgen's object descriptor; this derives it for everyone else from the one schema source). The `union` kind (WP-01, 2026-07-22) emits `default_id` + typed `options` (string/blob options carrying `maxlen`) and is what makes `schema/probe-union.sofab.yaml` describable — the union sweep position model is derived from it. `--json` writes the artifact (probe output unchanged — the union branch fires only on a union field). |
| `oracle/materialized-schema.json` | built | The committed artifact `schema.py` emits — the schema-type table drivers/tools consume without re-parsing YAML. `materialize.sh` regenerates + `cmp`-checks it each run so it cannot drift from the schema. |
| `engine/structured/materialize.py` | built | The materialized-form **reference / ground truth**, now **driven by the generated schema descriptor** (`schema.py`) — no hardcoded message shape; only gen.py's value-vector key convention remains. Models `decode(encode(msg))` — since documentation#31 `count` is a **capacity**, so an array materializes exactly the elements the wire carried (no fill-to-N, no trailing trim; a wrapper is *highest present id + 1* with interior gaps restored), scalar ±0.0 normalized. Every driver's `SOFAB_MATERIALIZE` output must equal it byte-for-byte. `--driver PATH` runs a driver binary over `corpus/structured` and diffs it (the per-driver acceptance gate); `--check DIR` compares a dump dir. |
| `scripts/materialize.sh` | built | Runs the materialized differential over the **full blocking roster** (`drivers/roster`) with `SOFAB_MATERIALIZE=1`, over `corpus/structured` — **0 divergences** (agreement) **+ a C-anchor conformance check** vs the reference (a family-wide-wrong dump is agreement-green, conformance-red). **A standing CI gate** (`replay.yml`); exports `SOFAB_MATERIALIZE_SCHEMA` for the descriptor-driven drivers. **Every walker is schema-agnostic:** C (sofabgen object descriptor); **go/ts/java/cs/python** consume the generated `materialized-schema.json` at runtime (reflection); **rust/cpp/zig** — no runtime reflection — instead **generate their walker source at build time** from the descriptor (`drivers/<lang>/materialize_gen.py`, run by `build.sh`, unrolling the descriptor into straight-line access code). A schema change reflows to the whole roster with zero hand-editing. |
| `oracle/comparator.py` | built | N-way canonical diff, policy-aware, no external deps; parses `A`/`I`/`R`. **Crash- and hang-isolating:** a per-driver wall-clock budget (`--timeout`, default `max(30s, 0.25s × corpus)`; `TIMEOUT=` env via the scripts) via stdout-to-tempfile, so an adversarial input that hangs a driver is localized + reported `[TIMEOUT]` (a DoS finding), not a wedged run. `read_corpus` skips `*.md` + dotfiles so a corpus dir can carry a README (inputs can't be selected by extension — libFuzzer names files by content hash); this also stops the `.gitkeep` in the gitignored corpora being fed as an empty message. |
| `oracle/policy.yaml` | built | **What counts as a bug.** Two parts, both read by `comparator.py`. (1) The five **axes**: a difference in the verdict or in an accepted value is hard (it fails the run); a difference in a partial value, a reject class or a limit class is soft (reported, does not fail) while those taxonomies are still being aligned. (2) The **allow list**: named inputs that may differ on one named axis because the difference follows from a language's design rather than from a defect — today the C NUL-terminated-string projection (F-0018), plus one entry deliberately kept dormant for a case no current schema can reach. **Enforced since 2026-08-16**; before that the allow list was read by nothing, so the input it named had to be kept out of every gate corpus to avoid a red gate. Matching is by the input's **bytes**, never its path, so an allowance survives the file being promoted into a corpus; a path that no longer resolves is reported rather than ignored. |
| `scripts/run.sh` | built | Build all drivers → differential compare over a corpus (crash-isolating). |
| `scripts/run-union.sh` | built | Union suite: `SCHEMA=schema/probe-union.sofab.yaml CORPUS=corpus/union run.sh` — points the differential + round-trip oracles at a `probe` message carrying a 4-variant union. Drivers are schema-agnostic (round-trip form), so only the generated types change; `drivers/c/build.sh` made SCHEMA-aware to match the other 8. 11 seeds × the whole roster, 0 divergences — the `union` wire feature `probe` lacked, now covered. |
| `scripts/run-limits.sh` | built | Limit-mode loop (crucible#10 / generator#102): heap roster built from `schema/probe-dyn.sofab.yaml` with identical `max_dyn_*` caps, compared per dimension over `corpus/limits/{arr,str,blb}`. Full heap roster (incl. cpp) in all three dimensions since sofabgen 0.16.1 fixed G-0009. |
| `scripts/fuzz.sh` | built | The C pacemaker: build the libFuzzer target (clang) + run + grow corpus/interesting. |
| `oracle/minimize.py` | built | **Delta-minimizer for a finding's reproducer**: shrinks an input while its *camp partition* is unchanged — the rule every `findings/*/NOTES.md` follows, since a partition change means the finding changed rather than shrank. Takes the driver roster as `--driver name:path` exactly as `cluster.py` does, and is reached through `MINIMIZE=<file> ./scripts/run.sh` so the roster stays defined in one place. **Batched by design:** a check is almost pure process startup (measured here: 1507 ms for a 1-input corpus across the then-drivers — java alone 441 ms of JVM boot — against 10 ms per input at 100), so testing a hundred candidates is cheaper than testing one. Every candidate of a round goes into a single corpus, and deletions that each hold alone are first tried together. Measured against the per-candidate predecessor: 25 B input 57 s → 16 s (identical output), 1132 B input >35 min with no result → **2 min 15 s → 150 B**. |
| `scripts/fuzz-go.sh` + `drivers/go/{fuzz_test.go,gocorpus.py}` | built | **Second steering engine** — Go's native coverage-guided fuzzer (`go test -fuzz`, no external framework) over `corelib-go`'s decoder. The pacemaker steers by *C* coverage and so only explores C-complex paths; this steers by Go's and feeds discoveries into the same `corpus/interesting`. Go stores its corpus (seed *and* the coverage corpus under `$GOCACHE`) in a text format rather than raw bytes, in both directions; `gocorpus.py` is the **only** place that format is understood — it writes every byte as `\xNN` (always a valid Go literal) and, when reading, handles the richer set Go itself emits, including `\u`/`\U`, which name a code point and therefore contribute its multi-byte **UTF-8 encoding**. Seeds are named `seed_<sha1>` so anything else left in `testdata/` afterwards is by construction a Go-written failing input → `corpus/crashes/`. Runs in `nightly.yml` after the C pass at a quarter of its budget. |
| `oracle/cluster.py` | built | Groups divergences by camp-partition into root causes (`CLUSTER=1 ./scripts/run.sh`); 256 divergences → 47 clusters. With `--baseline` it diffs every camp against `results/known-clusters.txt` and exits non-zero on an unexplained one. **It checks that file's `# roster:` line first** (since 2026-08-16): every signature names every driver, so one added driver invalidates all of them at once — on 2026-08-05 that read as "9 NEW CAMPS, 0/9 accounted for" with zero new root causes. When the stamp and the running drivers disagree the run says so and stops, instead of reporting every camp as new; the baseline still has to be re-recorded, but the message is now true. A baseline with no stamp is refused for the same reason. |
| C pacemaker (libFuzzer) | built | `drivers/c/driver.c` `CRUCIBLE_LIBFUZZER` path; ~41k exec/s; grows the corpus fed to the differential loop. Coverage-guided but NOT yet structure-aware. |
| `corpus/seeds/` | built | 6 agreeing seeds (the regression gate); green across all 4 drivers. |
| `corpus/regression/` | built | **Resolved-findings gate** (× the blocking roster, 0 divergences): the reproducer of every fixed finding, so a bump that reintroduces one fails CI instead of waiting to be noticed in a manual re-run. Admits an input only when it is green **for the reason the finding is about** — reproducers that also trip an open axis are excluded and listed with their reason. The roster, the per-input assertion, the exclusions and the input count all live in `corpus/regression/README.md` (its own owner — restating them here only drifts). Runs via the documented `CORPUS=` mechanism (no new script). |
| `engine/structured/sweep_run.py` | built | The **sweep runner**: imports each axis module, emits its vectors into a temp dir, feeds them to the blocking roster and checks **two** oracles — *agreement* (identical canonical line) and *conformance* (the vector's declared expectation). The expectation vocabulary is the runner's contract with an axis: `accept` / `reject` (the verdict must be `A` / `R`), `not_reject` (a prefix of a valid message is `A` or `I`, never `R`), the §7.4 aliases `merge`/`replace`/`lastwins`/`skip` (treated as accept), and — since 2026-08-03 — **`same:<twin>`**: the input must be accepted **and re-encode to the same bytes as the named canonical vector in the same axis**. That last one exists because accept-vs-reject cannot see a family that accepts a non-canonical form and echoes it back, nor one that is *uniformly* too strict: both are unanimous, and unanimity is what the agreement oracle calls green. It is what makes CORELIB_PLAN §7.2's tolerance class (5b) testable at all. A `same:` vector additionally fails if its twin re-encodes to the **empty** message: "same payload" would then be satisfied by any driver that also produces nothing, proving no normalization — the blind spot F-0054's own isolate had, which an axis must not be able to reintroduce silently. |
| `engine/structured/sweep_tolerance.py` | built | The **tolerance axis** (§7.2 class 5b), blocking since 2026-08-03. 49 vectors over all 7 sequence positions: a sequence-end header carrying id 3 and id `ID_MAX`, and id 0 spelled non-minimally — each `same:` its canonical twin, so both halves of §4.9 are asserted (accept, *and* normalize to `0x07`) — against over-`ID_MAX` and over-64-bit-varint rejects as the strict-side contrast. Every vector closes a **declared** sequence holding a real field, because an empty frame is normalized away by §2 and would make the discarded id unobservable — the blind spot F-0054's own isolate had. The non-minimal *varint* half of class 5b stays in `sweep_varint` and is deliberately not duplicated here. `emit_union` carries the same seven vectors onto the **union** sequence in `schema/probe-union.sofab.yaml` — a union is an ordinary sequence on the wire, so §4.9 binds its closing marker too, but it lives in a schema the probe pass cannot reach. |
| `oracle/chunk_invariance.py` + `scripts/run-chunked.sh` | **oracle built, drivers pending** | The **chunk-invariance** gate (CORELIB_PLAN §7.2 item 4): for every input and every split point, feeding `[0,k)` then `[k,end)` into one decoder must produce the canonical line the whole message produces. Alone among the oracles here it is **not differential** — it compares a driver against itself, so it needs no second implementation, drivers opt in one at a time, and it is the only gate that can catch a defect the whole family shares. Also asserts **resumability**: an `I` must still reach the right verdict and value after the remaining bytes arrive. Drivers opt in via the variables and are named explicitly in `SOFAB_SPLIT_DRIVERS`, because a driver that ignores them emits identical output and would pass vacuously. **All three cuts are implemented here:** the `SOFAB_SPLIT=k` sweep over every interior boundary (which also says *which* boundary broke), `SOFAB_CHUNK=n` at sizes 1/2/3/5/8/16 (`n=1` splits every varint, length word and payload, so it cannot straddle the boundary that breaks), and `SOFAB_CHUNK_SCRUB=1` at `n=1` — a *lifetime* check rather than a boundary one, catching a decoder that borrows from a fed chunk instead of copying out of it. `--modes` selects a subset. **Which drivers implement it is declared in `scripts/run-chunked.sh`** — that list is its own owner, so it is not restated here. Each participating driver announces its configuration on stderr when a variable is set, which is what makes "it really re-feeds" checkable rather than asserted: stdout is identical either way. |
| `oracle/encode_invariance.py` + `scripts/run-encode.sh` | **oracle built, drivers pending** | The **encode-invariance** gate (crucible#132) — the encode-side twin of the above, and likewise **not differential**. The family is byte-canonical, so the three encode surfaces of one implementation (`SOFAB_ENCODE=new` → allocating `encode()`, `to` → caller-buffer `encodeTo()`, `stream` → `serialize(os)`) must emit identical bytes for the same decoded value, and `SOFAB_FLUSH=n` (an `n`-byte `OStream` buffer) must not change them — the encode-side mirror of `SOFAB_CHUNK=1`, walking the encoder across a buffer boundary at every offset. Which surfaces a backend has comes from `meta`'s `encode_surfaces`; the baseline every surface must reproduce is the driver's own **default** path, so a driver that reads the variable but wires it to the wrong call is caught too. It additionally asserts the contract's **hard-fail**: asking for a surface the backend lacks must exit non-zero, never fall back silently. Defaults to `corpus/structured` rather than `corpus/seeds` — only an accepted input re-encodes, so on `I`/`R` every surface trivially agrees. Opt-in via `SOFAB_ENCODE_DRIVERS`; **which drivers implement it is declared in `scripts/run-encode.sh`**, its own owner. **Which flush sizes are swept is the port's own declaration** (§5.1, rewritten by documentation#46/#48 on 2026-08-11): `meta`'s `min_output_buffer` carries the smallest streaming buffer the corelib accepts — `1` for a port that splits atomic units across a flush, otherwise the largest run it reserves as one piece, capped at `20`. The sweep is `{declaration} ∪ {1,2,3,5,8,16 above it}`, so it always contains the declaration itself and can never be empty; a refusal (exit **3**, distinct from 2, "no such surface") at or above the declaration is a conformance failure, and a size one byte *below* it is asserted to be refused, which is what stops a high declaration from being an escape hatch. Every port but `go` declares 1 and therefore sweeps the full 1/2/3/5/8/16 as before; `corelib-go` declares `2 × maxVarintLen` = 20. |
| `engine/structured/isolates.py` | built | Minimal isolates for findings whose *original* reproducer is contaminated (tests two axes at once, so it can never be gate-green). Imports wire primitives from `gen.py` — the one reference encoder — so an encoding change cannot desync them. Emits `corpus/regression/F0003_overcount_clean.bin` (green) and the F-0013 reproducers (diverging → `findings/`). Each isolate declares its own destination. |
| `scripts/gen-findings.py` | built | **Generates `results/FINDINGS.md` from the write-ups.** The index carries no fact of its own: the id is the folder name, the title the write-up's heading, the state its `**Status:**` line, and the upstream ticket its `**Issue:**` line. A `G-00NN` that is the generator side of a divergence is declared in that finding's write-up as `**Codegen:** <id> | <issue> | <title>` — it needs its own ticket in 11 of 21 cases and its own wording in 6, so it is stored rather than derived. A codegen defect with no divergence behind it keeps its own folder. The tally line is counted, not typed. |
| `scripts/check-catalog.py` | built | **The catalog gate**, driver-free and blocking. Since the index became generated (2026-08-16) it asserts only what generation cannot: that the committed index is what the write-ups produce today (regenerate-and-compare, the shape `materialize.sh` uses for the schema table), that every write-up declares a state, and that every closed finding carrying reproducers declares a **`**Guard:**`** — the corpus, sweep axis or oracle that re-checks it, or `none — <reason>`. The declaration is verified: a named corpus must hold either those bytes or a vector named for the finding, a named axis must exist, a `none` must carry a reason. The state-agreement checks it used to run are gone because they became unreachable — the index cannot disagree with a write-up about a fact it no longer holds. |
| `scripts/driver-audit.sh` | built | **The per-driver participation ledger**: for every roster entry, what its `meta` declares (`chunked_decode`, `encode_surfaces`, `min_output_buffer`) and which gates that declaration places it in. Asserts the declarations exist and are well-formed — an absent key is the state that hides work, while `none` is somebody having written down that the backend cannot do it. Also fails a quarantine that names no finding. Static only (no builds, no corpora), so it runs in the `catalog` CI job in seconds, before anything is built. It cannot tell whether a declaration is *true* — that is what the gates' hard-fails and the stderr-announcement assertions do. |
| `engine/structured/audit_canonical.py` | built, **unwired** | Static canonicality audit of the committed corpora against §2/§3, independent of `gen.py`: it re-derives the properties from the bytes, so it can catch a reference encoder that is itself wrong (the one check `gen.py` structurally cannot perform on itself). Run by hand — no gate calls it. A hit is only unambiguous on the corpora that are *meant* to be canonical (`corpus/structured`, `corpus/structured-union`, both clean as of 2026-08-16); `seeds`, `conformance` and `regression` carry deliberately non-canonical inputs and light it up by design. Wiring it to the canonical corpora is in [`TODO.md`](TODO.md). |
| `findings/`, `results/FINDINGS.md` | built | The findings catalog (F-00NN reproducers under `findings/`) **and** the codegen-defect log (G-00NN), merged into one file. |
| `.devcontainer/` | built | Fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, SharpFuzz, Jazzer.js). |
| `drivers/rust/` (rs + rs-no-std) | built | One shared `driver.rs` for both corelibs; single-pass `try_decode` (see notes). |
| `drivers/cpp/` (**four configurations**) | built | One shared `driver.cpp` across **two corelibs × both `allow_dynamic` settings** (crucible#129, since 2026-08-04): `cpp` (corelib-cpp, heap), `cpp-fixed` (corelib-cpp, heap-free), `cpp-c-cpp` (corelib-c-cpp, heap-free), `cpp-c-cpp-dyn` (corelib-c-cpp, heap). `allow_dynamic` was a c-cpp-only knob until generator#289 extended it to `corelib: cpp`, with corelib-cpp#70 making `readString`/`readBlob`/`StringSeq`/`BlobSeq` storage-agnostic. **`driver.cpp` and `materialize_gen.py` needed no change** — both were already written against only the member API the two storage flavours share, so `build.sh` selects the include path, the config, and (for both c-cpp rows) the C sources to compile, and nothing else differs. The heap-free path is a **different branch inside the corelib's typed reads**: it rejects an over-capacity payload against the *container's* capacity rather than only the declared `maxlen`, and its destination is address-stable and fixed-size. The wire format is byte-identical across all four, so any divergence between them is a bug by construction — which is how **F-0057** was found on the configuration's first run. Single-pass (feed returns Result). Limit mode is `cpp` only: it needs *both* a heap profile and a corelib whose `Error` carries `LimitExceeded`, and no other configuration has both. `cpp-c-cpp-dyn` was quarantined while F-0057 was open; the quarantine was lifted when corelib-c-cpp#132 closed it, and all four configurations are in the blocking gates. |
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
changes) and folds in the round-trip oracle. Verified: every driver emits
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
generic via C's object descriptor, a schema-type table elsewhere. **Every driver**
implement it, **all schema-agnostic** — C via the object descriptor, go/ts/java/cs/python
by consuming the generated `materialized-schema.json` at runtime, rust/cpp/zig by
generating their walker source from the descriptor at build time: **106×13 → 0
divergences**, and the C anchor matches the `engine/structured/materialize.py` reference
**0/106**, with the default round-trip path unchanged.

**A `count: N` array materializes exactly the elements it carries.** `count` is a
capacity, not a length (MESSAGE_SPEC §3), so there is no fill-to-N anywhere in this form:
every walker reads the container's own length — C from the `ARRAY_SIZED` descriptor's
companion `*_len` member and, for a wrapper holder, from the holder's count
(`fixed_seq >> SEQ_LEN_SHIFT`); Zig from `FixedArray(T,N).slice()`; the rest from their
native container. The wrapper branch reports that count rather than trimming to the
highest populated slot, because §2 requires a default-valued **last** element to be
present — trimming would report `["a", ""]` as `["a"]`. Until 2026-07-29 four walkers
iterated the capacity instead (the fill-to-N that documentation#31 retired), which is
what the gate caught when the family moved: 1068 divergences, closed in `4b650c6`.

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

**The streaming axes, per backend.** Every driver honours the two ENCODE variables; every driver except `go` also honours the three DECODE ones
(`drivers/common/CONTRACT.md`); what differs is what each backend *offers*, and that is
where the per-language work went:

| driver | chunked decode | encode surfaces | notes |
|---|---|---|---|
| c | `_decoder_init` + `_decoder_feed`; **no `status`** — the last feed's return is it | `to`, `stream` | no allocating encode, so the driver's **default** path is already `to` |
| cpp ×4 | **no generated `decoder()`** — driven by hand, as `try_decode`'s own `IStreamInline` fed in pieces | `new`, `to`, `stream` | a bare `IStreamObject` would decode under different rules and report a try_decode-vs-feed difference as a chunk-invariance failure |
| rust ×2 | `decoder()` → `feed`/`finish`; **no `status`** | `new`, `stream` | `finish()` feeds an empty chunk to probe end-of-input — what makes a truncated stream an error, not a half-filled value |
| java, csharp | `decoder()` → `feed`, `status()`, `message()` | `new`, `to`, `stream` | |
| dart | `decoder(out)` → `feed`, `status` | `new`, `to`, `stream` | the backend the "never `finish()`" rule exists for: it returns **null** where the others throw |
| zig | `decoder(out, alloc)` → `feed`, `status()` | `new`, `stream` | **borrows** a payload arriving whole in one chunk and requires the chunk to outlive the message, so `SOFAB_CHUNK_SCRUB` is inapplicable (exit 3) |
| typescript | `new ProbeDecoder()` → `feed`, `status` | `stream` only | no `encode()`, no `encodeTo()`; `OStream` cannot encode below its largest contiguous write, so small `SOFAB_FLUSH` sizes are inapplicable |
| python ×2 | **pull-shaped**: `deserialize(Decoder(reader))`, chunked by handing it a reader that returns short reads | `new`, `stream` | cannot alias — `read()` yields immutable `bytes` copied on arrival — so `SOFAB_CHUNK_SCRUB` is inapplicable for the opposite reason to zig's |
| go | **none** — corelib-go has no resumable decoder (decode side only; the encode axis landed 2026-08-16) | `new`, `to`, `stream` | declared `chunked_decode=none` in `meta`, so it is absent by record rather than by omission |

Every participating driver **announces its configuration on stderr** when a variable is
set. Without that, a driver that silently ignored the variables would be
indistinguishable from one that honours them — stdout is identical either way — which is
the vacuous pass the gates' opt-in rosters guard against, one level down.


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
  results/FINDINGS.md.)
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
  infallible generated `decode` (results/FINDINGS.md G-0005), uses `IStreamObject`
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
  `PYTHONPATH`. Registered as two drivers. The venv itself is reused across runs,
  but the **corelib-py install is stamped and reinstalled** whenever the vendored
  `src/`, `pyproject.toml`, or `setup.py` is newer than the stamp (`--force-reinstall
  --no-deps`) — a non-editable install is a copy, so without that the Python drivers
  keep testing the corelib-py that was vendored when the venv was first built (the
  rule the Java driver applies to its jar; see the 2026-07-27 decision). **Fallible decode:** unlike Rust/C++,
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
