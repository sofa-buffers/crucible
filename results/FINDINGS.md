# Findings

Triaged divergences the differential loop has surfaced. Each has a reproducer
under `findings/<id>/` and a verdict path (corelib bug fix, or a `policy.yaml`
allow-entry once the spec rules). Transient, un-triaged crash/divergence
artifacts live under `corpus/crashes/` (gitignored); promoted findings land here.

| id | title | impls | axis | status |
|---|---|---|---|---|
| [F-0001](../findings/F-0001-truncated-trailing-varint/NOTES.md) | truncated trailing varint: two camps — C/C++/Rust/Java/C# accept, Go+Python+TS+Zig reject (7 vs 5) | {c,cpp,c-cpp,rust-std,rust-nostd,java,csharp} vs {go,py-cython,py-pure,typescript,zig} | verdict | ✅ **resolved — target met.** Spec-resolved (§7 finish-less: truncated = INCOMPLETE); corelibs → [generator#86](https://github.com/sofa-buffers/generator/issues/86); Crucible third verdict `I` → [crucible#8](https://github.com/sofa-buffers/crucible/issues/8). The target — **every impl emits `I`**, not accept/reject — is **met**: verified green 2026-07-13 and re-verified 2026-07-17, all 12 drivers emit `I` on both seeds (was 7-accept/5-reject). Both reproducers are in the green `corpus/regression/` gate. *(java additionally emits an `incomplete_value` payload on `I` — a **soft** axis, tracked separately; the verdict itself is unanimous.)* |
| [F-0002](../findings/F-0002-encoder-negative-left-shift-ub/NOTES.md) | corelib-c-cpp encoder left-shifts a negative value (UB) | corelib-c-cpp | ub (sanitizer) | ✅ resolved — [corelib-c-cpp#70](https://github.com/sofa-buffers/corelib-c-cpp/pull/70) merged (verified @ sofabgen 0.15.1) |
| [F-0003](../findings/F-0003-rust-array-oob-panic/NOTES.md) | Rust decoder panics (index OOB) on an over-long array — crash/DoS | corelib-rs, corelib-rs-no-std | crash → **verdict** | ✅ **fully resolved** — crash fixed by [generator#87](https://github.com/sofa-buffers/generator/pull/87) (issue [#78](https://github.com/sofa-buffers/generator/issues/78)); the residual over-count *accept* divergence ([generator#100](https://github.com/sofa-buffers/generator/issues/100)) is **fixed in sofabgen 0.16.1** (commit `ca0fda7`, "reject over-count scalar arrays in every backend"). **Re-verified 2026-07-15:** a clean non-truncated over-count(8>5) array → **all 12 drivers reject** (`R invalid_msg`); rust-std/nostd now reject with the family |
| [F-0004](../findings/F-0004-string-invalid-utf8-divergence/NOTES.md) | invalid UTF-8 in a string: 4 behaviors driven by the string type — raw (C/C++/Zig) / U+FFFD (Java/C#/TS) / empty (Rust-std + Rust-no-std) / reject (Go/Py) | 4-way | verdict + value | ✅ **RESOLVED 2026-07-18** (sofabgen 0.18.0, crucible#55). The `SOFAB_STRICT_UTF8` epic landed family-wide — 0.18.0 codegen for rust/java/cs/zig ([generator#162](https://github.com/sofa-buffers/generator/pull/162)) + corelib-internal checks (c/cpp/go/py/ts) + always-strict Unicode types. **Crucible built all drivers with the check ON** (`drivers/c` + `drivers/cpp` c-cpp variant opt in via `-DSOFAB_ENABLE_STRICT_UTF8` + `utf8.c`; zig supplies `build_options.strict_utf8=true`) and added 11 invalid-UTF-8 seeds (`engine/structured/utf8_seeds.py`, reusing corelib-c-cpp's `invalid_utf8` vectors) + 3 valid controls. **Verified:** the 4-way raw/U+FFFD/empty/reject split is gone — every malformed vector → **all 12 `R invalid_msg`**, every valid control → **all 12 `A`** and round-trips. Promoted into `corpus/regression/` (29→43). *(Embedded U+0000 is accepted by all 12 but the C object API truncates it on re-encode — a separate value axis, split out as **F-0018**.)* |
| [F-0005](../findings/F-0005-corelib-cpp-over-lenient/NOTES.md) | corelib-cpp accepts malformed messages the whole family (incl. its c-cpp sibling) rejects; collapses distinct inputs to one value | corelib-cpp | verdict + value | ✅ resolved — [corelib-cpp#22](https://github.com/sofa-buffers/corelib-cpp/issues/22) closed. Re-verified 2026-07-15 (sofabgen 0.16.1): cpp rejects the reproducer `56 0a 59` in step with the family. **Note:** on that same input corelib-py now returns `I` where the family returns `R` — a *new*, unrelated divergence split out as **F-0006** |
| [F-0006](../findings/F-0006-corelib-py-fixlen-fp-incomplete-vs-invalid/NOTES.md) | corelib-py: a truncated fixlen fp32/fp64 with a wrong declared length (≠4/≠8) returned INCOMPLETE (`I`) instead of INVALID (`R`) | corelib-py (both engines) | verdict | ✅ **resolved** — [corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38) fixed & closed. corelib-py `main` now validates fp fixed width at the FIXLEN header (before payload read). **Re-verified 2026-07-15:** `56 0a 59` / `56 02 38` → all 11 drivers `R`. Was surfaced by the `e14e4ba` un-eager-allocation bump; the clean single-culprit slice of F-0007 |
| [F-0007](../findings/F-0007-invalid-vs-incomplete-precedence/NOTES.md) | INVALID-vs-INCOMPLETE precedence: a truncated wrong-width fixlen fp read as `I` instead of `R` (C istream checked `length > target_len`, not the exact width) | corelib-c-cpp (c + cpp-c-cpp) | verdict | ✅ **resolved** — [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82) fixed & closed (`635966d`, "reject wrong-width fixlen fp32/fp64 as INVALID (#82)(#83)"). **Re-verified 2026-07-15 (sofabgen 0.17.0):** `56 0a 09` / `56 02 10` → all 12 drivers `R`. Direct analogue of the closed corelib-py#38. (A family-wide MESSAGE_SPEC §7 precedence clause remains a nice-to-have.) |
| [F-0008](../findings/F-0008-cpp-c-cpp-nested-seq-in-string-array-hang/NOTES.md) | generated **fixed-capacity C++** string/blob-array fill **hangs (infinite loop / DoS)** on an element index ≥ the fixed capacity — a 4-byte input (`c6 0c c6 07`) | generator (sofabgen C++ backend) — G-0011 | liveness / DoS | ✅ **resolved** — [generator#126](https://github.com/sofa-buffers/generator/issues/126) fixed in **sofabgen 0.17.1** (commit `483c281`, "bound fixed-capacity string/blob-seq fill loop"). **Re-verified 2026-07-16:** `c6 0c c6 07` → `I` (terminates, no hang). Root cause: generated `_FixedStrSeq`/`_FixedBlobSeq` do `while (out->size() <= id) out->emplace_back()`, but `InlineVector::emplace_back` no-ops once full, so `id ≥ N` spins forever. Heap `cpp`, C object API `c`, go, rust all return `I`. **Correction:** first mis-filed against corelib-c-cpp#84 (closed — not a corelib bug; the maintainer redirected in [crucible#16](https://github.com/sofa-buffers/crucible/issues/16)); re-targeted to codegen. Found by the mutator + localized by the per-driver timeout |
| [F-0009](../findings/F-0009-c-object-blob-padded-to-maxlen/NOTES.md) | the C object API re-encodes a sub-`maxlen` blob padded to full `maxlen` (zero-fill), and drops an all-zero blob — round-trip data loss | generator (sofabgen C backend) — G-0012 | accept_value (round-trip) | ✅ **resolved** — [generator#128](https://github.com/sofa-buffers/generator/issues/128) fixed in **sofabgen 0.17.1** (commit `25d5853`, sized blob descriptor). **Re-verified 2026-07-16:** short blobs round-trip in `c`, matching the family; the sub-`maxlen` vectors are back in the green `corpus/structured/` gate (52 inputs, 0 divergences). Root cause: C backend generates `blob` as a bare `uint8_t[maxlen]` + plain `SOFAB_OBJECT_FIELD(...BLOB)` (fixed full-capacity) with **no length**; should use `SOFAB_OBJECT_FIELD_BLOB_SIZED` (the corelib already provides it, byte-identical wire). `[0x01]` → c `01 00 00 00` vs family `01`; `[0x00]` → c drops it. Even the C++ wrapper `cpp-c-cpp` (same C `istream/ostream`) preserves it. **Found by the cross-encode / structured-value oracle** on its first run |
| [F-0010](../findings/F-0010-undercount-array-pad-vs-keep/NOTES.md) | under-count fixed array (`0 < wire count < schema count`) round-trips to different values — pad-to-capacity vs keep-count, a clean 6-vs-6 split along the memory model | family-wide (spec) | accept_value (round-trip) | **spec-RESOLVED, corelibs converging.** Clause **adopted → [documentation#18](https://github.com/sofa-buffers/documentation/pull/18)** merged (§3+§5.1, sparse fill-to-N: decode materializes N, canonical encode **elides the trailing default run** → canonical wire is count 3). **Audit 2026-07-16:** neither camp fully compliant yet — {c, rust×2, cpp, cpp-c-cpp, zig} must **trim trailing defaults on encode** (they emit count 5, observable); {go, py×2, java, ts, cs} must **fill-to-N on decode** (they keep M — latent, round-trip-masked). Traced to **codegen, not corelib** (corelib array writers correctly write `count = len(passed slice)`); filed **[generator#136](https://github.com/sofa-buffers/generator/issues/136)** with R1/R2 reproducers — **✅ fixed in sofabgen 0.17.2** (PR #137): all 12 backends now emit the canonical count 3/1 on the R1/R2 reproducers (C via corelib-c-cpp#87). The trim/pad question is resolved family-wide. **(The same go changeset introduced a separate omission regression — split out as F-0011.)** **Found by the cross-encode oracle, slice 2** (array value space) |
| [F-0011](../findings/F-0011-go-fixed-count-array-not-omitted/NOTES.md) | go emits an **all-default `count:N` array field explicitly** (`<hdr> 00`) instead of omitting it (§2) — a sofabgen 0.17.2 go-backend regression from the F-0010 fix | corelib-go (codegen) | accept_value (round-trip) | ✅ **resolved — [generator#139](https://github.com/sofa-buffers/generator/issues/139) fixed in sofabgen 0.17.3** (commit `0713b94`). Short-lived regression: commit `684656d` (0.17.2, while fixing F-0010) made go emit all-default `count:N` arrays explicitly instead of omitting them (§2); go-only. **Re-verified 2026-07-16 (0.17.3):** `empty_arrays` → all 12 omit the arrays; full box green again. Found on the 0.17.2 bump, fixed on the 0.17.3 bump same day |
| [F-0012](../findings/F-0012-ts-skip-fixlen-incomplete-vs-invalid/NOTES.md) | corelib-ts reports `I` (INCOMPLETE) where the family reports `R` (INVALID) for a **malformed fixlen word in a skipped (unknown) field** + truncation — a §5.2 precedence gap in the unknown-field skip path | corelib-ts | verdict | ✅ **resolved — [corelib-ts#49](https://github.com/sofa-buffers/corelib-ts/issues/49) fixed** (`0279378`, "validate fixlen word in the cursor skip path (§5.2 precedence)"). Root cause: `src/decode/cursor.ts` `skipValue` checked only `len > FIXLEN_MAX`, never the subtype/fp-width, so a reserved subtype or wrong-width fp in the skip path → `take()` → `INCOMPLETE` on truncation. **Re-verified 2026-07-17:** `aa7e79` / `5df35d07` → TS now `R invalid_msg` (was `I`), aligned with the family; the valid-skip controls stay `A`/`I`. **Found by the coverage-guided fuzzer** — was the single largest divergence class (~66%, 11-vs-1). The TS analogue of the fixed F-0006/F-0007; the PR #37 audit's "§5.2 all-12-compliant" only covered known small field ids |
| [F-0013](../findings/F-0013-overindex-string-array-element-kept-vs-dropped/NOTES.md) | a `string_array` element at an index ≥ the schema `count` is **kept** by the 9 heap profiles and **dropped** by the 3 fixed-capacity ones — all 12 accept, so the split is value-only; the same unbounded fill is a memory-amplification **DoS** (9 B → cpp 226 MB / go 122 MB at index 2,000,000, vs ~8 MB fixed) | sofabgen — every heap backend (codegen, **G-0013**) | accept_value (round-trip) + resource | ✅ **RESOLVED** — closed over two releases, in the right order. **0.17.4** ([generator#142](https://github.com/sofa-buffers/generator/issues/142)) killed the DoS (cpp **226 MB → 10 MB**) and made the 9 heap backends reject; **0.17.6** ([generator#149](https://github.com/sofa-buffers/generator/issues/149) → #151 fixed-capacity C family + #150 no_std) made the last 3 profiles (`c`/`cpp-c-cpp`/`rust-nostd`) reject instead of silently dropping. **Re-verified 2026-07-17 (0.17.6):** `overindex_clean` + `overindex_amplify` → **all 12 `R invalid_msg`**; in-range elements still accepted; promoted into the green `corpus/regression/` gate. Root cause: heap backends emitted an unbounded container + `while (len <= id) push(default)` fill, so the schema `count` was enforced nowhere; the fixed profiles honored it (via #126's F-0008 guard) but *dropped* rather than rejected. §7/§7.1 require both camps to reject. **The half of F-0008 that #126 left unfixed** — found 2026-07-16 while building a clean over-index isolate for F-0008 |
| [F-0014](../findings/F-0014-array-fixlen-element-word-not-validated/NOTES.md) | the **`ARRAY_FIXLEN` element word** is not (fully) validated at the header → `I` (INCOMPLETE) instead of `R` (INVALID) on truncation (§4.8/§5.2). Each impl misses a *different* check: **c** validates size-vs-subtype but not §4.8's fp32/fp64-only array restriction; **py** validates the subtype but never the size; **ts** validates both but *too late* (the `count > remaining` guard fires first) | corelib-c-cpp, corelib-py, corelib-ts | verdict | ✅ **resolved** — all three fixed & closed the same day: [corelib-c-cpp#89](https://github.com/sofa-buffers/corelib-c-cpp/issues/89) (`ab062e3`), [corelib-py#41](https://github.com/sofa-buffers/corelib-py/issues/41) (`d4fe94f`), [corelib-ts#51](https://github.com/sofa-buffers/corelib-ts/issues/51) (`7a9033f`, "validate fixlen element word **before truncation guard**" — the ordering diagnosis). **Re-verified 2026-07-17 (0.17.5):** all three isolates → **all 12 `R invalid_msg`**; promoted into the green `corpus/regression/` gate. The **array** analogue of the fixed F-0006/F-0007/F-0012 (all scalar-path). Three minimal isolates, each pinning one impl as the lone `I`. **Found by the 1 h fuzzer round**: corelib-ts#49 removed the dominant cluster (divergence rate 86%→32%), unmasking these residuals — all one class. Nice detail: corelib-py's scalar branch already *comments* the array width check ("the eager element-width check on the fixlen-array path below") that was never written; corelib-ts#49 *identified* the ordering trap and sidestepped it in `skipValue` but not in the known-field path |
| [F-0015](../findings/F-0015-maxlen-not-enforced/NOTES.md) | a `string`/`blob` **over its schema `maxlen`** splits the family **9-vs-2-vs-1**: the 9 heap profiles accept and keep the over-long value (never consult `maxlen`), c+cpp-c-cpp reject `invalid_msg`, rust-nostd rejects `buffer_full`. Within-`maxlen` → all 12 agree | family-wide (spec) | verdict + accept_value | ✅ **RESOLVED — spec clause adopted *and* implemented, verified against the pre-bump baseline.** **sofabgen 0.17.5** (`b0b2832`, "reject over-maxlen strings/blobs as INVALID on decode (Option B)") → **all 12 drivers `R invalid_msg`** on all three over-`maxlen` vectors (baseline: 9 accept / 2 `invalid_msg` / 1 `buffer_full`). Both halves: the 9 heap backends enforce `maxlen`, **and** rust-nostd's `buffer_full` became `invalid_msg`. Within-`maxlen` control still accepts on all 12. All four vectors promoted into the green `corpus/regression/` gate. **The arc closed in one day:** hole → clause (documentation#19) → spec PR merged (#20) → codegen (0.17.5) → verified. *Original:* spec-RESOLVED, corelibs to converge. Clause **adopted → [documentation#20](https://github.com/sofa-buffers/documentation/pull/20) merged** (closing [#19](https://github.com/sofa-buffers/documentation/issues/19)); **MESSAGE_SPEC §7.1** now binds a declared `count`/`maxlen` to **every target regardless of allocation strategy** (*"MUST NOT accept an over-bound value merely because its storage happens to be able to hold it"*), §7.2 defines the unbounded case, and CORELIB_PLAN §6.2.1 + the new `LimitExceeded` code normalize the receiver-side `max_dyn_*` limits Crucible already tests via `L`. **Target: all 12 → `R invalid_msg`** (the 9 heap backends must enforce `maxlen`; rust-nostd's `buffer_full` class becomes wrong) (Crucible spec Proposal 3 → documentation#20). The spec **never says** what to do when a string/blob exceeds `maxlen`: §7's "Enforce schema bounds as INVALID" enumerates only `M > N` and element id `≥ N`; MESSAGE_SPEC mentions `maxlen` 5× but never normatively (§5.1 uses it as a *pre-sizing hint* "on heap-less profiles"); **CORELIB_PLAN mentions it 0×**. Contrast `count`, which *is* specified to bind every target since documentation#18. So the 3 "enforcers" enforce only because their fixed buffer can't hold more — an artifact of the memory model, same shape as F-0010/F-0013. **Found 2026-07-17 while preparing the regression for an announced count/maxlen codegen update** — the axis was untested and already divergent; the vectors are the pre-bump **baseline**. Proposal 3 also closes two adjacent holes: the unbounded (no-bound) obligation, and the undocumented receiver-side `max_dyn_*` limits (which Crucible already tests via the `L` verdict) |
| [F-0016](../findings/F-0016-overlong-varint-accepted/NOTES.md) | an **overlong (>64-bit) varint** is **accepted and silently truncated** instead of rejected — 8-vs-4 split, and the value is corrupted (different malformed inputs → different wrong u64) | corelib-cpp, corelib-go, corelib-rs-no-std, corelib-py, corelib-java, corelib-cs, corelib-ts (7) | verdict + accept_value | ✅ **RESOLVED** — all 7 fixed & closed; **re-measured 2026-07-17: all 12 `R invalid_msg`** on both over-64-bit vectors (baseline 8A/4R), control still `A`; promoted into the green `corpus/regression/` gate (29 inputs). Was filed per-impl (corelib-side, the varint reader): [corelib-cpp#39](https://github.com/sofa-buffers/corelib-cpp/issues/39), [corelib-go#48](https://github.com/sofa-buffers/corelib-go/issues/48), [corelib-rs-no-std#45](https://github.com/sofa-buffers/corelib-rs-no-std/issues/45), [corelib-py#43](https://github.com/sofa-buffers/corelib-py/issues/43), [corelib-ts#53](https://github.com/sofa-buffers/corelib-ts/issues/53), [corelib-java#41](https://github.com/sofa-buffers/corelib-java/issues/41), [corelib-cs#37](https://github.com/sofa-buffers/corelib-cs/issues/37). Each caps the byte count at 10 but never checks the **10th byte's** overflow bits; the 3 that reject (c-cpp/rs/zig) do a pre-shift room test (`istream.c:110`). Spec §4.1/§6.3 already require `INVALID`. `ff…ff 01` (2⁶⁴−1) is accepted by all — not an off-by-one. **Found by the coverage-guided fuzzer** (2nd 1 h round) — cluster 2 minimized to it |
| [F-0017](../findings/F-0017-ts-decode-ignores-header-wire-type/NOTES.md) | the generated **TypeScript** decode dispatches on the field **id alone** and calls the schema-typed reader **without checking the header wire type** → on a wire-type ≠ declared-type header it reads the field as the *schema* type and **desynchronizes from the wire framing**. Clean isolate `05 00 01`: **11 → `R invalid_msg`, ts → `I`**; proof `05 07` → ts decodes `u8 = 7` (reads an ArrayFixlen header as an unsigned scalar) | generator (sofabgen **TypeScript backend**, codegen) — **G-0014** | verdict | ✅ **RESOLVED 2026-07-18** — [generator#160](https://github.com/sofa-buffers/generator/issues/160) fixed in **sofabgen 0.18.0** ([PR #161](https://github.com/sofa-buffers/generator/pull/161), "frame each decoded field by header wire type"). **Re-verified:** isolate `05 00 01` → **all 12 `R invalid_msg`** (ts was `I`). The generated TS decode now consults the header wire type per field before picking the reader. Promoted `F0017_ts_wiretype_iso.bin` into the green `corpus/regression/` gate. |
| [F-0018](../findings/F-0018-c-embedded-nul-string-truncation/NOTES.md) | the C object API projects a `string` with an embedded U+0000 to first-NUL (`A\0B` re-encodes to `A`) on c + cpp-c-cpp; the other 10 preserve it — all 12 accept, a value split | corelib-c-cpp object API (NUL-terminated string, by design) | accept_value (round-trip) | **by-design / allowed divergence** — **not a bug.** A `string` with an embedded U+0000 is valid on the wire and preserved by the 10 length-carrying profiles; the C object API stores strings NUL-terminated (`char[]` + `strlen`), so it projects to first-NUL — the corelib still receives the full bytes correctly, and the lossless path is the byte/length visitor API. Sanctioned in `oracle/policy.yaml` (axis `accept_value`, spec MESSAGE_SPEC §8: preservation of embedded U+0000 is implementation-defined for a NUL-terminated profile). Reproducer in `findings/`; kept out of the green gate. (Surfaced 2026-07-18 adding F-0004's embedded-NUL control; earlier SOFABGEN G-0015 codegen entry withdrawn.) |
| [F-0019](../findings/F-0019-duplicate-sequence-id-fields-lost/NOTES.md) | a **sequence (struct) field id repeated in the same scope**: 11 profiles **merge** both occurrences, the generated **TypeScript** decode **replaces** the sub-object, silently losing every child set in the earlier occurrence — all 12 accept, a value split | **spec hole first** (CORELIB_PLAN §3 requires ids unique per scope but defines no decoder behavior); codegen (sofabgen TypeScript backend) second | accept_value (round-trip) | ✅ **RESOLVED (sofabgen 0.19.2, 2026-07-19).** MESSAGE_SPEC §7.4 ([documentation#23](https://github.com/sofa-buffers/documentation/pull/23), `0894035`): last occurrence per field id wins — struct + union **merge**, array wrapper **replaced**. Both codegen halves landed ([generator#175](https://github.com/sofa-buffers/generator/issues/175): TS `decodeInto` + C++ wrapper clear) plus [corelib-c-cpp#99](https://github.com/sofa-buffers/corelib-c-cpp/issues/99). **Re-verified:** all 7 vectors → all 12 agree, 0 divergences; promoted into the green gate (44 → 51). Minimal reproducer 20 B: `56 1a23 deadbeef 07 56 0a41 …0440 07` — `nested` (id 10) opened twice, blob in the first occurrence, f64 in the second → 11 re-encode `nested{f64, blob}`, ts re-encodes `nested{f64}`. Same split for `arrays` (id 100), 12 B. **Scoped by three controls that all 12 agree on:** a repeated *scalar*, the *same* child in both occurrences, and both children in *one* sequence — so it needs a sequence reopened with *differing* children. **Attribution:** generated code, not corelib — C++ emits `is.read(nested)` and Go `return &m.Nested, nil` (both decode into the existing member) while TS emits `o.nested = ProbeNested.decodeFrom(c)` (`message.ts:351`, fresh object). corelib-ts delivers both sequences faithfully. **But the spec never says what a decoder must do with a duplicate id** — §3 declares the encoding illegal, nothing defines reject/merge/replace — so there is no basis for a `policy.yaml` entry and **no issue filed yet**: if the clause resolves to "reject as INVALID" (the §3+§7-consistent reading), all 12 are wrong, not one. Proposed order is the F-0015 pattern: spec proposal → adoption → codegen. Kept **out** of the green `corpus/regression/` gate meanwhile. **Found by the 24 h pacemaker round** (11.4 G execs, 0 crashes) as the dominant `accept_value` class, delta-debugged from 1456 B to 20 B |
| [F-0020](../findings/F-0020-header-wire-type-vs-declared-type/NOTES.md) | a field header whose **wire type contradicts the schema's declared type** produces **four incompatible behaviors** — skip / `R usage` / `R invalid_msg` / **decode it anyway with a wrong value**. Systematic sweep: all 11 correctly-typed vectors agree, **all 55 mismatched vectors diverge (100 %)** | **part 1** corelib-cpp + generator (C++ backend) — G-0014 unfixed there; **part 2** spec hole (family-wide) | verdict + accept_value | ✅ **RESOLVED (sofabgen 0.19.3, 2026-07-20).** §7.3 ([documentation#23](https://github.com/sofa-buffers/documentation/pull/23)): a mis-typed field is **skipped**. Landed over corelib-cpp#43 + corelib-c-cpp#100 + generator#174, and the final array-into-scalar corner in **0.19.3** (generator#183, split out as F-0021). **Re-verified:** full 66-vector sweep → 0 divergences (axis-green); 5 vectors promoted into the green gate. **Part 1 — independent of that clause, wrong under every candidate rule:** the generated C++ dispatches on the field **id alone** (`probe.hpp:288-300`, `case 4: is.read(u32);`) with no wire-type check, violating corelib-cpp's documented precondition (`sofab.hpp:1619`, *"The requested type must match the field's wire type"*). `01 06` (id 0 = `u8`, wire type Signed, zig-zag 3) → cpp re-encodes **`u8 = 6`**, the raw un-zig-zagged varint — a silently wrong value, no reject. This is [generator#161](https://github.com/sofa-buffers/generator/pull/161)'s F-0017 fix **never applied to the C++ backend**. Not generator-only: `deserialize()` receives the stream as a separate object and `type_` is `protected` with no public accessor (`sofab.hpp:1074`), so corelib-cpp must expose the wire type first — the F-0010 shape (corelib + codegen together). **Part 2 — spec first:** nothing normative says what a decoder must do on a type mismatch; "skip" (what 7–9 do) would make c/cpp-c-cpp/py stop rejecting (**corelib** `object.c:396-410`, not generator), "reject" would need all five visitor backends to emit a per-scope **id → declared-type table**, because "unknown id" and "known id, wrong type" are indistinguishable there today. **F-0017 is correctly closed but was isolate-green, not axis-green** — its vector still converges, the axis behind it never did. Reproducers + `sweep.py` in `findings/`; kept **out** of the green gate. Found 2026-07-19 while checking whether repeated-field-with-differing-type was covered by any test (it was not); the repetition framing was a red herring — a *single* mis-typed field already diverges |
| [F-0021](../findings/F-0021-scalar-field-receives-array-wire-type/NOTES.md) | a **scalar integer field receiving an array wire type of the same signedness** (`u8…u64` ← ArrayUnsigned, `i8…i64` ← ArraySigned) is **decoded** (element written into the scalar) instead of **skipped** per §7.3 — the last 8 of F-0020's 55 mismatch vectors | generator (sofabgen) — rust-std/rust-nostd/csharp/java/zig backends; **generator-only** | verdict / accept_value | ✅ **RESOLVED (sofabgen 0.19.3, 2026-07-20)** — [generator#183](https://github.com/sofa-buffers/generator/issues/183) (PR #184). After 0.19.2 closed 47/55 of the §7.3 axis (F-0020), these 8 remain: clean **7-skip vs 5-decode** split. The 5 are the corelibs that deliver an integer array **element-by-element through the scalar `unsigned()`/`signed()` callback** (with `arrayBegin(id,kind,count)` announced first); the generated visitor dispatches on the id alone so the element lands in the scalar's arm. **Not** "visitor vs pull" — go/python are visitor-based and skip (they route arrays to a distinct method). **Generator-only, no corelib change** (verified per source: all 5 announce `arrayBegin`+count before the elements): the generated `arrayBegin` sets `skip_remaining=count` for a scalar-declared id, `unsigned()`/`signed()` honour it. The delivery design is deliberate (streaming, zero-alloc — rust-nostd/zig need it) and stays. Found re-checking F-0020 on 0.19.2 |
| [F-0022](../findings/F-0022-array-field-receives-scalar/NOTES.md) | an **array-declared field receiving a scalar of its element type** (`u8[]`←`u8`, `i8[]`←`i8`, `fp32[]`←`fp32`) is **decoded as a one-element array** instead of **skipped** per §7.3 — the exact **mirror of F-0021** (which was scalar-field←array) | generator (sofabgen) — rust-std/rust-nostd/csharp/java/zig backends; **generator-only** | verdict / accept_value | ✅ **RESOLVED (sofabgen 0.19.4, 2026-07-21)** — [generator#188](https://github.com/sofa-buffers/generator/issues/188). The array-fill arm now carries the §7.3 guard (`if self.afill == 0 { return; }`) and `array_begin` arms `afill` only at a real array position — so a bare scalar with no preceding `array_begin` falls through and is skipped, symmetric to the F-0021 `askip` fix; no corelib change. **Re-verified:** all 5 isolates (`u8[]`/`i8[]`/`fp32[]`←scalar + 2 controls) → 0 divergences across all 12, and the wiretype sweep no longer flags any array-field←scalar position; promoted into the green gate (`F0022_*`). **Root cause:** the five shared-callback backends delivered an array element-by-element through the same `unsigned()`/`signed()`/fp callback as a lone scalar; generator#183 (F-0021, 0.19.3) had guarded the **scalar arms** but not the **array-fill arms** `(Root_arrays,n)=>fill`, so a scalar inside the `arrays` scope was stored as element 0. **F-0020/F-0021 looked axis-green but were isolate-green** — their vectors only tested the scalar-field position, never the array-field position. **Found 2026-07-20 by the wire-type sweep** (`engine/structured/wiretype_sweep.py`) on its first run — 7-skip vs 5-decode, validated across all 12 |
| [F-0023](../findings/F-0023-wrapper-element-wire-type-not-guarded/NOTES.md) | a **mis-typed `string_array` wrapper element** (a scalar / wrong fixlen subtype / sequence where a `string` is declared) is **not skipped** per §7.3 — ts/py reject it, cpp mis-accepts a blob as the string, cpp-c-cpp rejects a subtype mismatch | generator (sofabgen) — ts/py/cpp/cpp-c-cpp backends; **generator-only** | verdict | ✅ **RESOLVED (sofabgen 0.19.4, 2026-07-21)** — [generator#189](https://github.com/sofa-buffers/generator/issues/189). The wrapper-element loop now emits the same §7.3 guard the struct-field dispatch already had — TS `if (c.wire !== Fixlen \|\| c.fixSub !== String) { c.skip(c.wire); continue; }` (`message.ts:372`), Py `if _ef0.type != FIXLEN or _ef0.subtype != STRING: d.skip(); continue` (`message.py:446`), and the C++ `_StrSeq` element loop — so a mis-typed element is skipped instead of read as the declared type. **Re-verified:** all 5 isolates (blob / fp32 / signed scalar / sequence element + control) → 0 divergences across all 12; promoted into the green gate (`F0023_*`). **Not a spec hole:** §5.1 makes a wrapper element a normal field, §7.3 says a mis-typed field is skipped — they compose. **Root cause:** generator#174 added the §7.3 guard to *struct-field dispatch* but **not to the array-wrapper element loop**, so ts/py rejected, cpp mis-accepted a blob as the string, cpp-c-cpp rejected a subtype mismatch. **The third §7.3 position the guard missed** (after F-0020 struct fields, F-0022 array-fill arms). **Found 2026-07-20 by the wire-type sweep** — validated across all 12 |
| [F-0024](../findings/F-0024-rust-trydecode-incomplete-over-invalid/NOTES.md) | generated Rust `try_decode` returns **INCOMPLETE where INVALID must win**: an input that is both malformed (invalid UTF-8, over-count array, over-length string/blob, `string_array` id ≥ 5) **and** truncated is reported `I` instead of `R`, violating §5.2 (INVALID dominates INCOMPLETE) | generator (sofabgen) — rust-std/rust-nostd backend; **generator-only** | verdict | ✅ **RESOLVED (sofabgen 0.19.4, 2026-07-21)** — [generator#190](https://github.com/sofa-buffers/generator/issues/190) (G-0016). The emitted `try_decode` now captures `feed`'s result without `?`, reads `v.inv`, and returns `InvalidMsg` **before** surfacing the Incomplete: `fed = is.feed(data, &mut v); … invalid = v.inv; … if invalid { return Err(InvalidMsg); } fed?;` (`message.rs:235/237/242/246`) — INVALID now dominates a truncated tail per §5.2. **Re-verified:** the 4 isolates → 0 divergences across all 12, and the malform×truncate sweep is green — all 18 malformed×{complete,trunc} vectors → `R` (0 conformance failures); **the axis was promoted from report-only to blocking** and the 4 vectors into the regression gate (`F0024_*`, gate 69 → 73). **Root cause:** 0.19.3 emitted `is.feed(data, &mut v)?;` (`message.rs:234`), whose `?` propagated `feed`'s `Err(Incomplete)` before the sticky `v.inv` was read — a **pure ordering bug, not a missing check** (`control_invalid_utf8_complete` was already `R` on all 12; only `bad+trunc` flipped rust to `I`). **corelib-rs `feed` was correct** (structural Incomplete is its job); csharp/java/zig + all non-callback backends already emitted `R`, so the wrong order was **Rust-backend-specific**. Same §5.2 family as F-0006/F-0007/F-0012/F-0014 (those missed a check; this **discarded** a correct one via `?`); distinct from §7.3 F-0022/F-0023. **Found 2026-07-20 by the 8 h pacemaker round** (2.24 G execs) as the dominant divergence class (63 % of sampled verdict-splits); delta-debugged 146 B → 11 B |
| [F-0025](../findings/F-0025-scalar-fp-field-receives-fp-array/NOTES.md) | a **scalar fp field receiving an fp fixlen array** (`f32`←`fp32[]`, `f64`←`fp64[]`, wire type ArrayFixlen) is **decoded** (element stored into the scalar) instead of **skipped** per §7.3 — the **fp analogue of F-0021**, which generator#183 fixed for integer arrays only | generator (sofabgen) — rust-std/rust-nostd/csharp/java/zig backends; **generator-only** | accept_value | ✅ **RESOLVED — [generator#193](https://github.com/sofa-buffers/generator/issues/193) fixed & closed** (post-0.19.4 sofabgen; verified on the CI build `0.0.0-20260722065611-f61a29b31c01`, 2026-07-22). Was a clean **7-skip vs 5-store** split (the wiretype §7.3 sweep's last residual after F-0022/F-0023 landed in 0.19.4). generator#183 (F-0021) armed the discard counter (`askip`) for **integers** only — (1) generated `arrayBegin` armed `askip` only for `Unsigned`\|`Signed`, never `Fixlen` (fp); (2) the `fp32()`/`fp64()` callbacks lacked the `askip` guard `unsigned()`/`signed()` carry. The fix (mirroring #183/#188, generator-only, no corelib change) arms `askip` for the fp array kinds and adds the guard to both fp callbacks. **Re-verified:** both reproducers (`f32_recv_array_fp32`, `f64_recv_array_fp64`) → **all 12 skip** (re-encode to the empty-scalar form `5607a606560707c60c07ce0c07`), the two controls agree, and the **wiretype (§7.3) sweep is green** (319 vectors, 0 divergences) — promoted **report-only → blocking** in `scripts/sweep.sh`. The 2 reproducers + 2 controls promoted into the green `corpus/regression/` gate (`F0025_*`, 73 → 77). **Isolate-green ≠ axis-green** — F-0021's vectors only exercised integer positions, so its fix looked complete while the fp position stayed broken until the sweep enumerated it. **Found 2026-07-21 by the wire-type sweep**; resolved 2026-07-22 |
| [F-0026](../findings/F-0026-c-blob-wrapper-reopen-stale-element/NOTES.md) | a **re-opened `blob_array` wrapper** keeps the earlier occurrence's element (zeroed) instead of **replacing the array whole** per §7.4 — C object API only; the `string_array` analogue is uniform across all 12 | corelib-c-cpp (pure-C object API — the `c` driver); **corelib-only, not codegen** | accept_value (round-trip) | ✅ **RESOLVED — [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) fixed & closed** (commit `2416a2b`, "reset sized-blob used-length in `sofab_object_init` (§7.4 re-open)"; verified 2026-07-22 on `origin/main`). Was: all 12 accept; `c` alone re-encoded a stale element. Minimal isolate `ce0c0213dead07ce0c07` (open `blob_array`{id0=dead}, re-open empty → §7.4 replace → empty): 11 drop element 0, **c keeps it as `00 00`**. **Root cause:** the §7.4 replace-init `sofab_object_init` (`object.c:242-254`) zeros a **sized blob**'s buffer via a generic `memset(offset, size)` but never its **companion length** at `offset - nested_idx` — the one function of four that omits the sized-blob branch (`_field_is_default` `:205`, encode `:354`, decode `:499` all honour it). Stale `len != 0` → the "cleared" element re-encodes. A **string** slot has no separate length, so `string_array` (id 200) replaces correctly — the split is blob-specific. **Attribution — corelib, not codegen:** the descriptor already flags the sized blob (`nested_idx`); no schema knowledge needed; `cpp-c-cpp` (C++ `FixedBytes` over the *same* corelib) agrees, so it is the pure-C `object.c` path only. Neighbour of F-0009 (sized-blob encode) / F-0013 (`_BlobSeq` over-index) — the reset/init residual, reachable only via a §7.4 wrapper re-open. **Found 2026-07-21** the moment a `blob_array` was added to `probe` (the F-0013 blob-path follow-up): the repeated-id sweep's `string_array` reopen was green, its blob analogue diverged. The over-bound blob path (§7.1) is **green** by the same integration. **Re-verified 2026-07-22:** all 4 isolates → **all 13 agree** (`c` now drops the re-opened element); the `elem=="blob"` carve-out removed from the repeated-id (§7.4) sweep, which is green with the blob wrapper included (16 vectors); the 2 reproducers + 2 controls promoted into the gate (`F0026_*`, 77 → 81) |
| [F-0027](../findings/F-0027-nostd-feature-gated-skip-rejects-array-fp64/NOTES.md) | **rust-nostd rejects a §7.3-skippable array / fp64 field the schema never declares**: a mis-typed or unknown-id field carrying an **array** wire type (VARINTARRAY_U/S, FIXLENARRAY = 3/4/5) or an **fp64** fixlen subtype is `R invalid_msg` on rust-nostd where all 12 others **skip** → `A` (§7.3). Surfaced only on `probe-union` (a schema with no array/fp field); `probe` is green | generator (sofabgen) — the rust-nostd Cargo feature set; **corelib-rs-no-std implicated** (G-0017) | verdict | 🔴 **OPEN** — [generator#215](https://github.com/sofa-buffers/generator/issues/215). **Root cause:** corelib-rs-no-std gates wire-type *parsing* behind cargo features (`array`, `fp64`); sofabgen provisions those features from the wire types the **schema declares** — `["fixlen","sequence"]` for `probe-union` vs `["array","fixlen","fp64","sequence","value64"]` for `probe` — so without `array`/`fp64` the no-std decoder's shared parse/skip dispatch (`istream.rs::on_header` → `_ => Err(InvalidMsg)` :331; fp64 arm `#[cfg(feature="fp64")]` :386) **cannot skip** those wire types, only reject. But §7.3 skip-ability is **schema-independent** (any field can receive any wire type as a mismatch; any unknown id can carry any construct), so omitting them yields a **§7.3-non-conformant decoder**. **Attribution — generator, corelib implicated (F-0010 "occasionally both"):** the corelib was handed a feature config and faithfully rejected (diagnostic step 2 → caller is the bug); only codegen makes the schema→feature decision and writes the `Cargo.toml` (`build.sh` only touches `limit`) → **fix in sofabgen: always enable the full wire-type feature set for the *decoder* regardless of schema.** corelib-rs-no-std jointly implicated (a feature-independent read-and-discard *skip* path would also close it). **Confirmed by the two-way sibling split (diagnostic step 3):** `rust-std` (same generated code, non-gated corelib) agrees with the family, and `rust-nostd` on `probe` (features on) skips fine — only `probe-union` + no-std rejects. Minimal isolate `0300` (2 B, empty arr_u @id0). **Found 2026-07-22 by the WP-01 union pass** of the wiretype (§7.3) sweep — the first sweep run against a union-only schema. Union pass held **report-only** until fixed |
| [F-0028](../findings/F-0028-cpp-dart-decode-id-over-idmax-accepted/NOTES.md) | **a field id > ID_MAX (2³¹−1) is accepted on decode** by `cpp` + `dart` (skipped as an unknown id → `A`) where the other 11 reject (`R`, §6.2) — the decoders check ID_MAX only on **encode**, not decode | corelib-cpp + corelib-dart (decoders); **corelib-only, not codegen** | verdict | 🔴 **OPEN** — [corelib-cpp#47](https://github.com/sofa-buffers/corelib-cpp/issues/47) + [corelib-dart#14](https://github.com/sofa-buffers/corelib-dart/issues/14). Reproducer `id_over_idmax.bin` = `808080804005` (id 2³¹, wire unsigned, value 5). **Root cause:** both enforce `ID_MAX` in their **encoder** (`corelib-cpp include/sofab/sofab.hpp:475` `putHeader`; `corelib-dart encoder.dart:140`) but the **decoder** reads `header >> 3` with no ceiling check (`sofab.hpp:1410/:1812`; `decoder.dart:221`) → a wire id > ID_MAX is treated as unknown and skipped. `corelib-c-cpp` **does** check it in the decoder (`istream.c:485`), so `cpp-c-cpp` rejects — pinning the gap to the pure-C++ (`cpp`) and Dart decoders. **Attribution — corelib:** ID_MAX is a format constant, not schema; the check is wire mechanics the family (incl. corelib-c-cpp in the same C++ profile) already performs. Control `id_at_idmax_ctl.bin` (id ID_MAX, largest valid) → all 13 accept. **Found 2026-07-23 by the WP-04 framing & ceilings sweep** (`engine/structured/sweep_framing.py`). *(F-0027 is reserved by PR #88 / WP-01, not yet on main.)* |
| [F-0029](../findings/F-0029-ts-cursor-no-maxdepth-limit/NOTES.md) | **nesting past MAX_DEPTH (255) is reported INCOMPLETE** by `typescript` where the other 12 reject (`R`, §4.9/§6.2) — the `cursor` decode path tracks depth for balancing but has no MAX_DEPTH ceiling | corelib-ts (`src/decode/cursor.ts`); **corelib-only, not codegen** | verdict | 🔴 **OPEN** — [corelib-ts#65](https://github.com/sofa-buffers/corelib-ts/issues/65). Reproducer `depth_over_maxdepth.bin` = `06`×300 (300 unclosed sequence-opens). **ts** → `I`, **12 others** → `R`. **Root cause:** corelib-ts's `fast.ts:195-198` and `state.ts:331-335` both enforce `MAX_DEPTH`, but `cursor.ts` (the hit path) increments `depth` (`:170`) only for the stray-end (`:162`) and EOF-incomplete (`:151`) checks, never comparing to `MAX_DEPTH` → 300 opens → EOF depth>0 → `I`. An **internal inconsistency** in corelib-ts. Fix: the one-line guard `if (this.depth >= MAX_DEPTH) throw invalidMsgError(...)` at `cursor.ts:170`, mirroring the other two paths. MAX_DEPTH exceedance is adopted-INVALID (§5.2, [documentation#17](https://github.com/sofa-buffers/documentation/pull/17)), so it dominates INCOMPLETE — **not** the open documentation#15 corner. **Attribution — corelib-ts:** format constant, wire mechanics, already present in its sibling decode paths. Control `depth_ok_ctl.bin` (balanced depth 8) → all 13 accept. **Found 2026-07-23 by the WP-04 framing & ceilings sweep.** |
| [F-0030](../findings/F-0030-c-object-struct-array-trailing-default-not-elided/NOTES.md) | **an all-default array-of-struct is re-encoded as N empty struct frames** instead of the canonical **empty wrapper** — c does not apply §5.1 trailing-default elision to sequence-form (struct) wrapper elements; leaf (string/blob) wrappers elide correctly | corelib-c-cpp (pure-C object API — `c`); **corelib-only, not codegen** | accept_value (round-trip) | 🔴 **OPEN** — [corelib-c-cpp#109](https://github.com/sofa-buffers/corelib-c-cpp/issues/109). Minimal repro: the **empty message** — c emits `d60c 06070e0716071e07260707` (5 `seq[i]()` frames), the other 12 emit `d60c07` (empty wrapper). **Root cause:** `sofab_object_encode`'s `if (field->type != SEQUENCE)` guard (`object.c:302-311`) skips the default-elision check for any sequence field — correct for a standalone all-default struct (§2 always-framed), but it also stops §5.1 trailing-elision from reaching struct *elements* of a `count:N` wrapper, so c frames all N. `cpp-c-cpp` (C++ object layer, same corelib) elides correctly → pure-C `object.c` path (F-0026 neighborhood). **Found 2026-07-23 by the WP-05 array-of-struct integration** — surfaced on every seed the moment `struct_array` was added to `probe`. Blocks folding `struct_array` into the main probe until fixed. |
| [F-0031](../findings/F-0031-fp32-snan-quieted-py-cython-ts-dart/NOTES.md) | **an fp32 signaling NaN (0x7F800001) is quieted to 0x7FC00001** on decode→re-encode (and in the materialized raw-bits walk) by py-cython / typescript / dart, where the other 10 (incl. py-pure) preserve it — §4.6 requires bit-for-bit float round-trip, no normalization | corelib-py (Cython engine) + corelib-ts + corelib-dart; **corelib-only, not codegen** | accept_value (round-trip + materialized) | 🔴 **OPEN** — [corelib-py#49](https://github.com/sofa-buffers/corelib-py/issues/49) + [corelib-ts#66](https://github.com/sofa-buffers/corelib-ts/issues/66) + [corelib-dart#15](https://github.com/sofa-buffers/corelib-dart/issues/15). **Scope:** only fp32 *signaling* NaN — the quiet-payload NaN (0x7FC00001), negative NaN, and fp64 sNaN all round-trip on 13. 0x7F800001 differs from a quiet NaN only in bit 22 (the is-quiet bit); the 3 double-backed fp32 impls set it (classic sNaN-quieting on load into a 64-bit double). **py-pure preserves it** → the sibling split pinning it to the double-backed fp32 path, not all-Python. **Root cause:** the fp32 payload is widened to a double before re-emit/materialize; the corelib must carry raw 32-bit bits (§4.6 'never inspects or normalizes'). **Found 2026-07-23 by the WP-06 float-specials vectors** — the first suite carrying an fp32 sNaN vector (canonical.md:107-109 had flagged it as a known limit). Carved out of the green corpus/structured gate until fixed. |
| [F-0032](../findings/F-0032-schema-bound-invalid-vs-truncation-go-cpp-ts-dart/NOTES.md) | **a schema-bound INVALID (over-maxlen/count/index) that is also truncated is reported INCOMPLETE** by several backends where §5.2 requires INVALID (documentation#15, adopted) — the F-0024 ordering class, still open for schema-bound checks. Split varies by (bound, backend): over-maxlen+trunc → go/cpp/ts/dart `I`; over-count+trunc → 9 `I`; over-index+trunc → cpp `I` | generator (schema-bound check ordering; **codegen**) — G-0018 | verdict | 🔴 **OPEN** — [generator#216](https://github.com/sofa-buffers/generator/issues/216). Structural malformations (reserved subtype, bad array element-word — INVALID at the word) are `R` on all 13; only *schema-bound* violations (checked after reading the payload/elements) split. maxlen/count/id are schema facts → the check + its ordering are generated code (F-0024 was this in the rust backend, generator#190). Fix: reject as soon as the deciding word/header shows the violation, before propagating a truncation Incomplete. **Found 2026-07-23 by WP-09** (broadened malform×truncation). Bound into-payload truncations carved out of the blocking axis (`STRUCTURAL` set) until fixed; structural truncations + `_complete` controls stay blocking. |
| [F-0033](../findings/F-0033-scalar-value-exceeds-declared-width-3way-split/NOTES.md) | **a scalar wire value exceeding its declared width (u8 > 255, u16 > 65535) splits the family 3 ways** — reject (c, cpp-c-cpp) / mask-to-width→255 (go, rust×2, cpp, csharp, zig) / keep-full-value→16383 (py×2, java, ts, dart) | spec hole (documentation) — family-wide, no single impl wrong | accept_value + verdict | 🔴 **OPEN (spec hole)** — [documentation#26](https://github.com/sofa-buffers/documentation/issues/26). §1 says the declared width is a **storage hint**, *the wire carries the integer regardless*; §7:527 says *value-range is outside the wire clause*; §7.1's INVALID list omits scalar over-width. So the format is **silent** — 3 defensible readings, 3 camps (the F-0010/F-0015 arc: hole → clause → converge). In-range control (u8=255) → all 13 agree. **Found 2026-07-23 by the C pacemaker fuzzing round** (34 M execs) — the hand-built value corpus never emits an over-width scalar, so only fuzzing reached it; the differential+cluster reduced 294 diverging inputs to 13 clusters, and this `accept_value` cluster (two distinct re-encoded values) was the new signal. Out of any green gate until a clause lands. |

Divergences are triaged by root cause in [`results/CLUSTERS.md`](CLUSTERS.md)
(generated by `oracle/cluster.py`).

Generated-code (codegen, not corelib) weaknesses carry a `G-00NN` id and are
catalogued in the [Codegen defects](#codegen-defects-g-00nn) section at the end of
this file (G-0001..G-0007 all resolved in sofabgen 0.15.1; the family-wide
invalid-UTF-8 policy continues as F-0004 above).

## Phase 1 note

The loop found F-0001 on its **first run** over hand-written seeds — before any
coverage-guided or structure-aware fuzzing. That is the differential oracle
working as designed: a divergence no single-implementation fuzzer could report,
because no impl crashes — they simply disagree. Phase 2 (adding Rust, C++,
Python, Java, TypeScript, C#, and Zig) grew it from 1-vs-1 into a
7-accept-vs-5-reject **two-camp** split — four independent lineages (Go, Python,
TypeScript, Zig) reject where the C/C++/Rust/Java/C# camp accepts. That is exactly
the extra signal more implementations buy: a lone outlier is ambiguous; four
independent rejects point firmly at the answer — and the split cuts across the
systems/managed line, so it is a genuine per-decoder design difference.

## Codegen defects (G-00NN)

Weaknesses in **generated** code (the sofabgen glue), distinct from corelib bugs:
candidate changes to `sofabgen` (repo: `generator/`). Each entry states what, where,
why it matters for the differential fuzzer, and the proposed fix; status is `open`
until the generator change lands. **G-0001..G-0007 were all resolved in sofabgen
0.15.1** (verified 2026-07-09). A codegen defect that is also a wire divergence has a
paired `F-00NN` row in the table above.

## Tracking issues (generator repo)

| id | issue | status |
|---|---|---|
| G-0001 | [generator#79](https://github.com/sofa-buffers/generator/issues/79) | fixed — PR [#88](https://github.com/sofa-buffers/generator/pull/88) (0.15.1) |
| G-0002 | [generator#80](https://github.com/sofa-buffers/generator/issues/80) | fixed — PR [#91](https://github.com/sofa-buffers/generator/pull/91) (0.15.1); family-wide UTF-8 continues as F-0004 / [#85](https://github.com/sofa-buffers/generator/issues/85) |
| G-0003 | [generator#81](https://github.com/sofa-buffers/generator/issues/81) | fixed — PR [#92](https://github.com/sofa-buffers/generator/pull/92) (0.15.1) |
| G-0004 | [generator#82](https://github.com/sofa-buffers/generator/issues/82) | fixed — PR [#93](https://github.com/sofa-buffers/generator/pull/93) (0.15.1) |
| G-0005 | [generator#83](https://github.com/sofa-buffers/generator/issues/83) | fixed — PR [#89](https://github.com/sofa-buffers/generator/pull/89) (0.15.1) |
| G-0006 | [generator#84](https://github.com/sofa-buffers/generator/issues/84) | fixed — PR [#90](https://github.com/sofa-buffers/generator/pull/90) (0.15.1) |
| G-0007 (= F-0003) | [generator#78](https://github.com/sofa-buffers/generator/issues/78) | fixed — PR [#87](https://github.com/sofa-buffers/generator/pull/87) |
| G-0008 | [generator#105](https://github.com/sofa-buffers/generator/issues/105) | ✅ **fixed** — PR [generator#106](https://github.com/sofa-buffers/generator/pull/106) (sofabgen 0.15.3): status-surfacing `TryDecode`/`tryDecode`; part of §7 epic [#86](https://github.com/sofa-buffers/generator/issues/86) |
| G-0013 | [#142](https://github.com/sofa-buffers/generator/issues/142) + [#149](https://github.com/sofa-buffers/generator/issues/149) | ✅ **fully fixed 2026-07-17.** 0.17.4 (#142): DoS gone (cpp 226 MB → 10 MB) + 9 heap backends reject. 0.17.6 (#149→#151 fixed-capacity C family + #150 no_std): `c`/`cpp-c-cpp`/`rust-nostd` reject too. Re-verified: all 12 `R` on `overindex_clean`; `overindex_clean.bin` in the regression gate. **Original:** ✅ DoS gone (cpp 226 MB → 10 MB) + the 9 heap backends reject. ❌ Residual (#149): `c`/`cpp-c-cpp`/`rust-nostd` still accept + silently drop via `_FixedStrSeq`'s #126 guard — the split flipped to a verdict split (9 `R` vs 3 `A`); §7/§7.1 require both camps to reject. **Original:** The heap backends (go, rust-std, cpp, py×2, java, ts, cs, zig) emit an **unbounded** container + fill for an index-keyed array, so the schema's `count: N` is enforced nowhere: an element at index ≥ N is **kept** (the 3 fixed-capacity profiles drop it — G-0011's #126 guard), and the `while (len <= id) push(default)` fill materializes `id+1` elements, so a **9-byte** input at index 2,000,000 costs cpp **226 MB** / go **122 MB** vs ~8 MB fixed — an unbounded-allocation DoS (the half of F-0008 that #126 left unfixed). Crucible finding **F-0013** |
| G-0012 | [generator#128](https://github.com/sofa-buffers/generator/issues/128) | ✅ **fixed in sofabgen 0.17.1** (commit `25d5853`, sized blob descriptor; re-verified 2026-07-16 — short blobs round-trip in `c`). Was: C backend generates a `blob` field as a bare `uint8_t[maxlen]` + the plain fixed-full-capacity `SOFAB_OBJECT_FIELD(...BLOB)` descriptor, with **no length member**. A blob is opaque bytes (no NUL recovery), so the object API pads a sub-`maxlen` blob to `maxlen` and drops an all-zero one — round-trip data loss. Fix: emit `{ uintX field_len; uint8_t field[N]; }` + `SOFAB_OBJECT_FIELD_BLOB_SIZED` (the corelib already provides it, byte-identical wire; the C++ backend already uses `FixedBytes<N>`). Crucible finding **F-0009** (found by the cross-encode oracle) |
| G-0011 | [generator#126](https://github.com/sofa-buffers/generator/issues/126) | ✅ **fixed in sofabgen 0.17.1** (commit `483c281`, bounded fill loop; re-verified 2026-07-16 — `c6 0c c6 07` → `I`, no hang). Was: C++ backend's generated `_FixedStrSeq`/`_FixedBlobSeq` (fixed-capacity string/blob arrays) do `while (out->size() <= id) out->emplace_back()`, but the corelib's fixed-capacity `InlineVector::emplace_back` is a no-op once full, so a wire element index `id ≥ N` (capacity) **loops forever** — a 4-byte DoS (`c6 0c c6 07`). Fixed-capacity C++ profile only; heap `std::vector` grows/terminates. Crucible finding **F-0008** (first mis-filed corelib-c-cpp#84, redirected via crucible#16). Fix: bound the fill by `N`, drop an over-capacity index (like the C/Zig backends) |
| G-0010 | [generator#120](https://github.com/sofa-buffers/generator/issues/120) | ✅ **fixed in sofabgen 0.16.2** (commit `26f1f4c`, PR #121): the generated zig `decode` now binds `feed(chunk)→Status` and surfaces `.incomplete` as `error.IncompleteMessage`. **Crucible driver.zig updated** to match (`error.Incomplete` → `error.IncompleteMessage`, two sites). **Re-verified 2026-07-15:** zig builds, F-0001 `80` → `I`, and the full 12-driver box is green. Was: sofabgen 0.16.1's zig backend `try`-discarded the new `Error!Status` return (compile error) — the zig analogue of G-0008. |
| G-0009 | [generator#112](https://github.com/sofa-buffers/generator/issues/112) | ✅ **fixed in sofabgen 0.16.1** (commit `7899c4b`, "heap unbounded array -> std::vector, not std::array<T,0>"). **Re-verified in Crucible 2026-07-15:** repro `03 03 07 08 09` → cpp decodes `[7,8,9]` (was `[]`) matching the family; cpp rejoined the limit-mode `arr` dimension (`scripts/run-limits.sh`), green. Was: sofabgen 0.16.0 C++ heap backend emitted a schema-*unbounded* array as `std::array<T, 0>`, silently dropping every element of an *accepted* array (the `max_dyn_array_count` cap itself still fired). Sibling of [generator#104](https://github.com/sofa-buffers/generator/issues/104) (C backend) |

---

## G-0001 — generated Rust `decode` is infallible (discards the decode error)

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#88](https://github.com/sofa-buffers/generator/pull/88), fixes #79) · **Lang:**
rust (both corelibs) · **Where:** `generator/generators/rust/visitor.go`

The generated decoder *was*:

```rust
pub fn decode(data: &[u8]) -> Self {
    let mut m = Probe::default();
    { let mut v = V { .. }; let mut is = IStream::new(); let _ = is.feed(data, &mut v); }
    m   // <- feed's Result<()> is thrown away
}
```

`IStream::feed` returns `Result<()>` and the corelib *does* detect malformed
input (`Error::InvalidMsg`, …), but the generated wrapper drops it and always
returns a (best-effort) value. So the **generated Rust API can never reject** —
a real user gets silent best-effort decoding, and a differential driver cannot
read the corelib's accept/reject decision through the public API.

**Former impact on Crucible:** the Rust driver used to run a **two-pass**
workaround — call `Probe::decode` for the value, then re-run `IStream::feed`
against a null visitor to recover the verdict. Faithful but wasteful (decoded
twice) — and, because the null visitor skipped the generated per-field checks, it
also missed the over-count-array rejection (see F-0003 / generator#100).

**Fix (shipped):** the Rust backend now emits a fallible entry point alongside
the back-compat `decode`:
`pub fn try_decode(data: &[u8]) -> Result<Self, sofab::Error>` (PR
[#88](https://github.com/sofa-buffers/generator/pull/88); `backend.go:303`,
`visitor.go:226`). Verified in the generated `message.rs` for both corelibs.
**Driver follow-up done** (crucible#10, 0.16.0 bump): `drivers/rust/driver.rs` is
now **single-pass** on `try_decode` — the two-pass workaround is **removed** —
mirroring the cs/java G-0008 fix. `Ok`→`A <hex>`, `Err(Incomplete)`→`I`, else
`R <class>`. Because `try_decode` runs the real generated visitor, rust now also
applies the over-count-array check (F-0003 / generator#100 re-triage — see
STATUS.md). The C (`sofab_ret_t`), Go (`error`), Python (`Probe.decode` raises),
and C++ (G-0005) backends all surface the result the same way.

## G-0002 — std vs no-std Rust diverge on invalid UTF-8 in a string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#91](https://github.com/sofa-buffers/generator/pull/91), fixes #80) · **Lang:**
rust · **Where:** `generator/generators/rust/visitor.go`

Same wire bytes *used to* decode to a different string across the two Rust
corelibs:

```rust
// std (corelib-rs)   — WAS:
String::from_utf8_lossy(&chunk[..total]).into_owned()   // invalid UTF-8 -> U+FFFD replacements
// no-std (corelib-rs-no-std):
core::str::from_utf8(&chunk[..total]).unwrap_or("")      // invalid UTF-8 -> empty string
```

A fuzzer produces non-UTF-8 bytes in a string field; the two ports then decoded
it to **different values** (replacement chars vs empty) — a generated-code
divergence, not a wire-format one.

**Fix (shipped):** both profiles now agree — std was changed to
`core::str::from_utf8(&chunk[..total]).map(|s| s.to_owned()).unwrap_or_default()`
(empty on invalid), matching no-std (PR
[#91](https://github.com/sofa-buffers/generator/pull/91); `visitor.go` UTF-8 emit
+ `backend_test.go:81`). **Verified empirically:** the F-0004 reproducer
`invalid_utf8.bin` now yields byte-identical driver output for `rust-std` and
`rust-nostd` (`A 5607a606560707c60c07`).

**Consequence for F-0004:** rust-std moved from the *U+FFFD* camp to the *empty*
camp. This closes the intra-Rust half; the **family-wide** invalid-UTF-8 split
(raw / U+FFFD / empty / reject across all ten corelibs) is finding **F-0004**,
resolved in spec §8 and tracked as epic [#85](https://github.com/sofa-buffers/generator/issues/85)
(corelibs adopting the opt-in strict check) — still open.

## G-0003 — std vs no-std Rust diverge on a chunked (multi-feed) string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#92](https://github.com/sofa-buffers/generator/pull/92), fixes #81) · **Lang:**
rust · **Where:** `generator/generators/rust/visitor.go`

The std visitor accumulates a string split across `feed` chunks (has an `acc`
buffer); the no-std visitor bails on any non-initial chunk:

```rust
// no-std:
fn string(&mut self, id, total, offset, chunk) {
    if offset != 0 || chunk.len() < total { return; }   // drops chunked strings entirely
    ...
}
```

Under incremental/streaming feed, a string delivered in pieces is reconstructed
by std but yields the default (empty) in no-std — divergence. (Not reachable in
single-shot decode, but Crucible's coverage engine will feed in chunks.)

**Fix (shipped):** the no-std visitor now accumulates chunked string/blob into
`self.acc` like std (PR [#92](https://github.com/sofa-buffers/generator/pull/92),
commit `b8e0693`). Verified: the generated no-std `message.rs` reads
`core::str::from_utf8(&self.acc[..total])`. Combined with G-0004, an over-capacity
accumulation is surfaced as an error rather than silently dropped.

## G-0004 — no-std silently drops an over-capacity string

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#93](https://github.com/sofa-buffers/generator/pull/93), fixes #82) · **Lang:**
rust (no-std) · **Where:** `generator/generators/rust/visitor.go`

The over-capacity fill *was* discarded silently:

```rust
(_Loc::Root, 3) => { self.m.s.clear(); let _ = self.m.s.push_str(_s); }
```

`heapless::String::push_str` is fallible (returns `Err` past capacity), and the
result was discarded. A string longer than the field's `maxlen` was **silently
dropped to empty** instead of rejected. Combined with G-0001 the caller got no
signal at all.

**Fix (shipped):** the fill now flags capacity overflow, e.g.
`... let _ = self.m.nested.str.push_str(_s); if self.m.nested.str.len() != _s.len() { self.err = true; }`,
and `err` is surfaced through the new fallible `try_decode` (G-0001) as an
`Error` (PR [#93](https://github.com/sofa-buffers/generator/pull/93), commit
`d56a1a7`). Verified in the generated no-std `message.rs`.

## G-0005 — generated C++ `decode` is infallible (same gap as G-0001)

**Status:** **fixed** in sofabgen 0.15.1 (PR
[#89](https://github.com/sofa-buffers/generator/pull/89), fixes #83) · **Lang:**
cpp (both corelibs) · **Where:** `generator/generators/cpp/backend.go`

```cpp
static Probe decode(const std::uint8_t *data, std::size_t len) {
    sofab::IStreamObject<Probe> in;
    in.feed(data, len);   // Result discarded
    return *in;
}
```

Same shape as G-0001: `IStreamObject::feed` returns a `Result` (with `.ok()` /
`.code()`), but the generated convenience `decode` throws it away and always
returns a value. A user of `Probe::decode` cannot tell a malformed message from a
valid one.

**Impact on Crucible:** smaller than Rust — the C++ driver simply uses
`IStreamObject` directly and reads `feed`'s returned `Result` (one pass, no
workaround). But the public convenience API still can't reject.

**Fix (shipped):** the C++ backend now emits a fallible form alongside `decode`:
`static sofab::IStreamImpl::Result try_decode(const std::uint8_t *data, std::size_t len, Probe &out)`
(PR [#89](https://github.com/sofa-buffers/generator/pull/89); `cpp/backend.go:221`).
Verified in the generated `probe.hpp`. C++, Rust (G-0001), Go, and C now all
expose the decode verdict. The Crucible C++ driver already read `feed`'s Result
directly, so no driver change is required.

## G-0006 — generated Go `types.go` uses `bytes.Equal` without importing `bytes`

**Status:** **fixed** in sofabgen 0.15.2 (PR
[#90](https://github.com/sofa-buffers/generator/pull/90), fixes #84) · **Lang:**
go · **Where:** `generator/generators/golang/` (per-file import collection for
named/nested types) · **Severity:** was build-breaking

A blob field inside a **named/nested** struct lands its marshal in `types.go`,
which emits:

```go
if !bytes.Equal(m.BytesField, nil) { e.WriteBytes(3, m.BytesField) }
```

but `types.go`'s import block only has the corelib — **no `"bytes"`**. Go
imports are per-file, so `go build` fails:

```
types.go:140:6: undefined: bytes
```

`probe.go` (which also uses `bytes`) *does* import it, so the top-level message
compiles — but any schema with a blob in a nested struct (e.g. the full-scale
message's `nested.bytes_field`) breaks. Reproduced with sofabgen 0.15.0 against
the arena full-scale schema unchanged.

**Impact on Crucible:** blocked the Go driver for the full-scale schema.
Previously worked around in `drivers/go/build.sh` (inject `"bytes"` into any
generated file that referenced `bytes.` but did not import it); that workaround
was **removed** once 0.15.2 emitted the import correctly — verified: generated
`types.go` now carries its own `"bytes"` import, so the injection no longer
fires.

**Proposed fix:** collect imports per emitted file, not per message — every file
that references `bytes.` (or any std package) must import it.

## G-0007 — generated Rust array fill has no bounds check (crashes)

**Status:** fixed (PR [generator#87](https://github.com/sofa-buffers/generator/pull/87)) ·
**Lang:** rust (both corelibs) · **Where:**
`generator/generators/rust/visitor.go` (native-array element fill) ·
**Severity:** crash / DoS on untrusted input

The generated Rust visitor writes native-array elements by an unchecked running
index:

```rust
(_Loc::Root_arrays, 0) => { self.m.arrays.u8[self.ai] = value as u8; self.ai += 1; }
```

`self.ai` is not bounded against the array length, so a wire message with more
elements than the declared count panics (`index out of bounds`). The **C and Zig
backends already guard this** — Zig's `_put` drops excess elements
(`if (i.* >= s.len) return;`), C's fill is equivalently bounded. Rust is the
outlier and it crashes rather than clamping.

This is the codegen root cause of **F-0003** (found by the C pacemaker → the
differential loop). It panics in release too (Rust bounds-checks indexing), so it
is a real DoS in any Rust consumer of the generated code.

**Fix (shipped):** mirrored the Zig/C behavior — the fill index is now guarded
(`if self.ai < N { ... ; self.ai += 1; }`), dropping excess elements per
MESSAGE_SPEC §5.1. Applied in `emitNativeArrayStore` so it covers every
native-array element arm (unsigned, signed, enum, bool, bitfield, float) across
both the std and no_std profiles. PR
[generator#87](https://github.com/sofa-buffers/generator/pull/87). Verified via
F-0003's `array_overflow.bin`: the rebuilt Rust driver goes from panic (exit 101)
to clean accept (exit 0) on both the `rs` and `rs-no-std` variants.

## G-0008 — generated one-shot decode discards the INCOMPLETE status (C#, Java)

**Where:** the generated `Probe.Decode`/`Probe.decode` for the *status-returning*
corelibs — C# (`Message.cs`) and Java (`Probe.java`).

**What:** under MESSAGE_SPEC §7 (finish-less three-valued decode), those corelibs
surface `INCOMPLETE` as a **returned status**, not a thrown error:
`IStream.Feed(...)` returns `DecodeStatus.Incomplete` (C#) and `IStream.status()`
returns `DecodeStatus.INCOMPLETE` (Java) — `feed` does *not* throw on a truncated
message. But the generated one-shot decode calls `feed` and **throws the status
away**:

```csharp
public static Probe Decode(byte[] data) {
    var m = new Probe(); var v = new ProbeVisitor(m);
    new IStream().Feed(data, 0, data.Length, v);   // DecodeStatus DISCARDED
    return m;
}
```

So a truncated message decodes without error and is indistinguishable from a
COMPLETE one — the generated decode **collapses INCOMPLETE into ACCEPT**, the
exact F-0001 bug the verdict axis exists to catch. Confirmed empirically: a lone
`0x80` re-encoded byte-identical to the empty message (`A 5607...`) before the
driver workaround.

**Why it matters:** this is the INCOMPLETE-dimension analogue of G-0001/G-0005
(which fixed the *reject* dimension — a fallible decode — but not the
*accept-vs-incomplete* dimension). The generated glue hides a real outcome the
corelib computes correctly.

**Former driver workaround (now removed):** `drivers/cs/Driver.cs` and
`drivers/java/Driver.java` used to take the **verdict** from a direct
`IStream.Feed`/`feed` + status read (a no-op visitor), and the **value** from the
generated decode — the same two-pass pattern the Rust driver uses for G-0001.

**Fixed** in sofabgen 0.15.3 (PR
[generator#106](https://github.com/sofa-buffers/generator/pull/106), closes
generator#105, under the §7 epic
[#86](https://github.com/sofa-buffers/generator/issues/86)): the generated
one-shot decode for the status-returning corelibs now surfaces the terminal
`DecodeStatus` via a status-returning entry point — C#
`DecodeStatus TryDecode(byte[] data, out T msg)` and Java
`DecodeStatus tryDecode(byte[] data, T out)` — so a caller can tell COMPLETE from
INCOMPLETE without re-running `feed`. The exception-throwing corelibs (Go, Rust
via feed, C++, C, Python, TS, Zig) already propagate INCOMPLETE through the
generated decode — only the status-returning pair needed the codegen change.

**Driver follow-up done** (crucible#10, sofabgen 0.16.0 bump): the two-pass
workaround is **removed** — `drivers/cs/Driver.cs` and `drivers/java/Driver.java`
now take both verdict and value from a single `TryDecode`/`tryDecode` call
(`Complete`→`A <hex>`, `Incomplete`→`I`, malformed throw→`R <class>`). Verified:
lone `0x80` still reports `I` (not the pre-fix `A`), and both drivers agree with
the family on the F-0001 seeds.

## G-0009 — generated C++ emits a schema-*unbounded* array as `std::array<T, 0>`

**Status:** ✅ **fixed in sofabgen 0.16.1** (commit `7899c4b`, the count-less array
now generates `std::vector<T>`) — [generator#112](https://github.com/sofa-buffers/generator/issues/112).
Sibling of the C-backend [generator#104](https://github.com/sofa-buffers/generator/issues/104).
Surfaced adopting the limit-mode probe (`schema/probe-dyn.sofab.yaml`, crucible#10 /
generator#102) at sofabgen 0.16.0; **re-verified fixed in Crucible 2026-07-15** —
cpp decodes `03 03 07 08 09` → `[7,8,9]` (was `[]`) and rejoined the limit-mode
`arr` dimension (green). The rest of this entry documents the original 0.16.0 bug.

**Where:** the C++ backend, generated `probe.hpp` for a count-less `array` field.

**What:** the limit probe carries one schema-*unbounded* field of each kind — a
count-less array, a maxlen-less string, a maxlen-less blob:

```yaml
dyn_arr: { id: 0, type: array, items: { type: u32 } }   # no count -> unbounded
dyn_str: { id: 1, type: string }                        # no maxlen -> unbounded
dyn_blb: { id: 2, type: blob }                           # no maxlen -> unbounded
```

Every other backend maps the unbounded array to a **growable** type
(`uint[]` C#, `list[int]` Python, `number[]` TS, `[]const u32` Zig), and the C++
backend itself maps the unbounded **string**→`std::string` and **blob**→
`std::vector<std::uint8_t>`. But the unbounded **array** is emitted as a fixed
**zero-length** container:

```cpp
std::array<std::uint32_t, 0> dyn_arr = {};   // cannot hold any element
```

A count-less array should be `std::vector<std::uint32_t>` (the heap `cpp`
profile), mirroring the string/blob it sits next to. It looks like the backend
defaults a missing `count` to `0` and takes the fixed-`std::array<T,N>` path
meant for *bounded* arrays, instead of the dynamic-vector path.

**Why it matters (a value divergence on accepted arrays):** at decode,
`IStream::read` takes the span branch, reads `count_` varints off the wire but
writes only `min(sp.size(), count_) = 0` of them (`sofab.hpp` ~L1526). So a
**non-over-cap** array that C++ *accepts* decodes to **empty** while the family
decodes the real elements. Reproduced end-to-end: bytes `03 03 07 08 09`
(array id0 = `[7,8,9]`, under the cap) → Python/family `[7,8,9]`, C++ `[]`.

The `max_dyn_array_count` **cap itself is unaffected**: the corelib enforces it at
the array's count header (keyed on the generated `SOFAB_MAX_DYN_ARRAY_COUNT`
macro), *before* the broken container is touched — so an over-cap array still
yields `L`, agreeing with the family. The divergence is confined to the **value**
axis on accepted arrays; the verdict axis (`A`/`I`/`R`/`L`) is correct.
Confirmed on the limit-mode corpus vectors (caps baked at 8):

   | vector | family | C++ (this bug) | axis |
   |---|---|---|---|
   | `under_arr` (4 elems) | `A` `[1,2,3,4]` | `A` `[]` | **value divergence** |
   | `at_arr_8` (8, at cap) | `A` `[0..7]` | `A` `[]` | **value divergence** |
   | `over_arr` (16, over cap 8) | `L` (limit) | `L` | agree ✓ |

The maxlen-less **string** and **blob** are unaffected — only the array path is
broken — so C++ still exercises `max_dyn_string_len` / `max_dyn_blob_len` fully
and correctly.

**Proposed fix (generator):** in the C++ backend, a schema array with no `count`
must generate `std::vector<T>` (and the vector read/cap path), exactly as the
count-less string/blob already do — not `std::array<T, 0>`.

**Crucible disposition (resolved 2026-07-15):** with the 0.16.1 fix, the `cpp`
target **rejoined the array dimension** of limit mode — `scripts/run-limits.sh`
runs the full heap roster (incl. cpp) on the arr vectors and is green; the `NO_CPP`
hold-out was removed. While the bug was open, cpp was held out of *only* the array
dimension (it always ran the correct string/blob dimensions). The bug was never
worked around in generated code or masked in the comparator: a silent zero-length
array is exactly the kind of value divergence Crucible exists to catch. Repro:
`03 03 07 08 09` → cpp now `[7,8,9]` (was `[]`), and the `corpus/limits/arr/`
vectors all agree.

## G-0010 — generated zig `message.zig` discards the new finish-less decode `Status`

**Status:** ✅ **fixed in sofabgen 0.16.2** (generator [#120](https://github.com/sofa-buffers/generator/issues/120),
commit `26f1f4c` / PR #121) + a Crucible `drivers/zig/driver.zig` update. Surfaced
2026-07-15 pulling corelib-zig `main` (`0f861e4`, "decode: replace finish() with
feed(chunk)→status", plan §5/§6.1); fixed the same day. **Lang:** zig · **Where:**
the generator zig backend (generated `message.zig`), plus the Crucible
`drivers/zig/driver.zig`. The rest of this entry documents the original break.

**Fix as shipped:** the generated `Probe.decode` now returns `DecodeError!Probe`
where `DecodeError = sofab.Error || error{IncompleteMessage}`; it binds the corelib's
`feed(chunk)→Status` and returns `error.IncompleteMessage` when the terminal status
is `.incomplete` (generated `message.zig` L146-158). The Crucible driver maps that
error to the `I` verdict — `drivers/zig/driver.zig` changed `error.Incomplete` →
`error.IncompleteMessage` at both the verdict test and the reject-class switch.
Verified: zig builds `-OReleaseSafe`, `80` → `I`, empty → `A`, and the full
12-driver seed + limit box is green.

**What:** corelib-zig adopted the finish-less MESSAGE_SPEC §7 model — its `decode`
and `feed` now return `Error!Status` where `Status` is `{ complete, incomplete }`,
and **INCOMPLETE is a returned `Status`, not an error** (`istream.zig`: `pub fn
decode(buf, visitor) Error!Status`). sofabgen 0.16.1's zig backend predates this and
still emits:

```zig
try sofab.decode(data, &v);   // Error!Status now — the Status is ignored
```

which fails to compile: `error: value of type 'istream.Status' ignored`. And the
Crucible zig driver still switches on `error.Incomplete`, which is no longer a
member of the corelib's error set (`error: 'error.Incomplete' not a member of
destination error set`).

**Why it matters:** this is the **zig analogue of G-0008** (which fixed the same
INCOMPLETE-as-returned-status gap for C# and Java via status-surfacing
`TryDecode`/`tryDecode`). The corelib moved correctly to §7; the generated glue and
the driver must catch up or a zig consumer cannot tell COMPLETE from INCOMPLETE (and
here, cannot even build).

**Fix:** (1) generator zig backend surfaces the terminal `Status` from the generated
one-shot decode (a `tryDecode`-equivalent), mirroring the cs/java G-0008 fix; (2)
`drivers/zig/driver.zig` reads the `Status` and maps `.complete`→`A <hex>` /
`.incomplete`→`I`, dropping the `error.Incomplete` arm. Until both land, zig is held
out of `scripts/run.sh` / `run-limits.sh` (the box runs over the other 11 drivers).

## G-0011 — generated fixed-capacity C++ string/blob-array fill infinite-loops (DoS)

**Status:** open — [generator#126](https://github.com/sofa-buffers/generator/issues/126).
Surfaced 2026-07-15 by the structure-aware mutator + the comparator per-driver
timeout (Crucible finding **F-0008**). **Lang:** cpp (fixed-capacity / `c-cpp`
profile) · **Where:** the generator C++ backend, generated `_FixedStrSeq` /
`_FixedBlobSeq` in `probe.hpp`.

**What:** the generated element handler for a fixed-capacity string/blob array grows
the destination up to the wire element index, then writes at that index:

```cpp
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();   // id = wire element index
auto &s = (*out)[id]; ...
```

On the fixed-capacity profile `out` is the corelib's `InlineVector<T, N>`, whose
`emplace_back()` is a **no-op once full** (intentional — no heap growth):
`std::size_t i = len_ < N ? len_++ : N - 1;`. So a wire element index `id ≥ N` makes
`out->size()` stick at `N`, `size() <= id` stays true, and the `while` **never
terminates** — a 4-byte DoS (`c6 0c c6 07`: the nested `SEQUENCE_START` is element id
120 into the count-5 `string_array`). The heap profile (`std::vector`) grows and
terminates, so only the fixed-capacity C++ target hangs.

**Why it matters:** ships to any consumer of the fixed-capacity C++ profile (the
embedded target) — an unbounded loop on 4 untrusted bytes. Not a corelib bug (the
`InlineVector` cap is correct/intentional) and not a Crucible driver bug (single
`feed()`); purely the generated fill loop assuming `emplace_back()` always grows.

**Proposed fix:** bound the fill by the fixed capacity `N` and drop/ignore (or reject)
an element index `≥ N`, so the loop cannot spin on a full `InlineVector`
(`if (id < N) { while (out->size() <= id) out->emplace_back(); ... }`). Mirrors the
C/Zig backends dropping excess native-array elements (MESSAGE_SPEC §5.1). Harmless on
the heap profile.

> **Follow-up 2026-07-16 — "harmless on the heap profile" was too generous; see G-0013.**
> The fix landed on the fixed-capacity profile only, which left the heap profile as the
> lone outlier on the *value* (it **keeps** an over-index element where the fixed profile
> now drops it) and left its fill loop **unbounded** — the memory-amplification DoS this
> section's own text anticipated ("heap `std::vector` grows/terminates *or OOMs for a huge
> id*"). The hang was treated as the whole bug; it was half. Crucible finding **F-0013**.

**Correction note:** F-0008 was first mis-filed against corelib-c-cpp#84 (closed — the
corelib maintainer correctly showed `sofab_istream_feed` terminates and redirected via
crucible#16). The differential symptom (only `cpp-c-cpp` hangs) was real; the fix is
codegen.

## G-0012 — C backend generates a blob field without a length (round-trip data loss)

**Status:** open — [generator#128](https://github.com/sofa-buffers/generator/issues/128).
Surfaced 2026-07-15 by the cross-encode / structured-value oracle (Crucible finding
**F-0009**). **Lang:** c · **Where:** the generator C backend, generated `probe.h`
struct + `probe.c` field descriptors.

**What:** a `blob` field (e.g. `nested.bytes_field`, `maxlen: 4`) is generated as a
bare fixed array with the plain, fixed-full-capacity descriptor:

```c
typedef struct { … char str[33]; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD(3, message_probe_nested_t, bytes_field, SOFAB_OBJECT_FIELDTYPE_BLOB)
```

There is **no length member**, and a blob is opaque bytes (can contain `\0`), so the
object API cannot tell how many bytes are live. On re-encode it emits the full
`maxlen` (zero-padded); an all-zero sub-`maxlen` blob collapses to empty. A producer
on the C object API therefore cannot faithfully carry a blob shorter than `maxlen` —
silent round-trip data loss (`[0x01]` → `01 00 00 00`; `[0x00]` → dropped). `str`
round-trips because it is `char[maxlen+1]` and NUL-terminated; a blob can't be
NUL-recovered.

**Why it matters:** ships to every consumer of the generated C object API. Not a
corelib bug — the C `ostream`/`istream` take an explicit length (the C++ wrapper
`cpp-c-cpp`, using `FixedBytes<N>`, round-trips correctly over the *same* C sources).

**Proposed fix:** the corelib already offers the sized variant. Emit a companion
length member immediately before the buffer and use it:

```c
typedef struct { … uintX bytes_field_len; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD_BLOB_SIZED(3, message_probe_nested_t, bytes_field_len, bytes_field)
```

`SOFAB_OBJECT_FIELD_BLOB_SIZED` stores the received length on decode and "produces
byte-identical wire to a plain blob of the same actual length" (`object.h`), so the C
object API then matches the rest of the family byte-for-byte.

## G-0013 — the heap backends never enforce an index-keyed array's schema `count`

**Status:** open — **filed [generator#142](https://github.com/sofa-buffers/generator/issues/142)**
(2026-07-17; spec target = reject per §7). Crucible finding **F-0013** (found
2026-07-16 while building `corpus/regression/`). Affects every **heap** profile: go,
rust-std, cpp, py-cython, py-pure, java, typescript, csharp, zig. The fixed-capacity
profiles (c, cpp-c-cpp, rust-nostd) are correct.

`schema/probe.sofab.yaml` declares `string_array` as `items: {type: string, count: 5}`.
That `count` reaches the fixed-capacity backends as a container capacity — and is then
**enforced**, because G-0011's fix bounded the fill by it. The heap backends emit an
**unbounded container** and an **unbounded fill**, so `count` is enforced nowhere:

```cpp
// c-cpp (fixed): the G-0011 / #126 guard — drops an over-index element
if (static_cast<std::size_t>(id) >= out->capacity()) return;
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();

// cpp (heap): no guard — grows to id+1 and keeps it
while (out.size() <= static_cast<std::size_t>(id)) out.emplace_back();
out[id] = std::move(_s);
```

Same shape in Rust, where the container type shows the cause directly — `rust-std` gets
`Vec<String>`, `rust-nostd` gets `heapless::Vec<heapless::String<64>, 5>`:

```rust
(_Loc::Root_string_array, _) => { while self.m.string_array.len() <= id as usize { self.m.string_array.push(Default::default()); } self.m.string_array[id as usize] = _s; }
```

**Two consequences.** (1) A **value divergence**: a `string_array` element at index 120
is dropped by the 3 fixed profiles and kept by the 9 heap profiles — all 12 *accept*, so
no accept/reject oracle sees it. (2) A **memory-amplification DoS**: the fill materializes
`id+1` elements and `id` is an unbounded varint, so a **9-byte** input at index 2,000,000
costs cpp **226 MB** / go **122 MB** where the fixed profiles stay at ~8 MB — raise the
index until OOM.

**Fix:** emit the schema `count` as a guard in *every* backend's index-keyed fill, not
only where the container happens to be fixed-capacity — the count is already known at
generation time (it is what produces `InlineVector<...,5>` / `heapless::Vec<_,5>`). The
C++ heap `_BlobSeq` has the identical unguarded shape, so index-keyed blob arrays are
almost certainly affected too (untested — `probe` has no blob array). If the spec instead
makes an over-index element `INVALID`, the guard becomes a reject; the allocation must be
bounded either way. See `findings/F-0013-overindex-string-array-element-kept-vs-dropped/`.

## G-0014 — generated TypeScript decode ignores the header wire type (stream mis-framing)

**Status:** ✅ **fixed in sofabgen 0.18.0** — [generator#160](https://github.com/sofa-buffers/generator/issues/160),
PR [#161](https://github.com/sofa-buffers/generator/pull/161) ("frame each decoded field by
header wire type"). **Re-verified 2026-07-18:** isolate `05 00 01` → **all 12 `R invalid_msg`**
(ts was `I`); `F0017_ts_wiretype_iso.bin` promoted into the regression gate. Found 2026-07-17
by the 3 h differential fuzz on sofabgen 0.17.7 (cluster 2; minimized 127 B → 24 B → a 3 B
isolate). Finding [`F-0017`](../findings/F-0017-ts-decode-ignores-header-wire-type/NOTES.md).

The **TypeScript backend**'s generated pull-decoder dispatches on the field **id alone**
and calls the schema-typed reader **without checking the header's wire type** (`c.wire`).
When a field header carries a wire type ≠ the field's declared type, the generated code
reads the bytes as the *schema* type and **desynchronizes from the wire framing** —
consuming the wrong byte count and mis-reading everything after the field. Only the
`default:` (unknown id) branch dispatches on the wire type (`c.skip(c.wire)`), so unknown
fields validate correctly and known fields do not.

```js
// generated Probe.decodeFrom — every known-field case, no c.wire guard:
case 0: o.u8 = Number(c.readUnsigned()); break;   // header wire could be anything
case 2: { const _s = c.readString(); ... }
case 10: o.nested = ProbeNested.decodeFrom(c);    // no c.wire === SequenceStart check
default: c.skip(c.wire); break;                    // the ONE branch that frames by wire
```

**Isolate `05 00 01`** — header `05` = `(id 0 << 3) | ArrayFixlen(5)`; field id 0 is
declared `u8` (wire Unsigned, 0). The other 11 impls frame it as an array-fixlen and
reject the malformed element word `01` (fp64 size 0 ≠ 8) → `INVALID`. TS ignores the wire
type, reads `00` as `u8 = 0`, then treats `01` as a new header (id 0 / Signed) → runs off
the end → `INCOMPLETE`. **Proof `05 07`** → TS decodes `u8 = 7` and round-trips `00 07`,
confirming it read the ArrayFixlen header as an unsigned scalar.

The corelib is **not** at fault: driving `Cursor` directly (bypassing the generated
dispatch) on `05 00 01` throws `INVALID_MSG` ("invalid fixlen array element type"). The
corelib readers assume they are only called for the matching wire type — a contract the
generated dispatch violates. The other backends drive the corelib feed/visitor, which
frames by wire type, so they cannot desync — this is a TS-backend codegen defect.

**Fix:** guard the header wire type per field before reading — reject a mismatch as
`INVALID` (matching how the family frames `05 00 01`), or at minimum route a mismatched
header through `c.skip(c.wire)` so the cursor stays framed by the wire. Upstream of the
resolved corelib-ts precedence family (F-0012/F-0014/F-0016): the wrong reader is selected
before any INVALID-vs-INCOMPLETE precedence question arises.

## G-0015 — ~~generated C object descriptor stores a `string` as NUL-terminated~~ (WITHDRAWN)

**Status:** ⛔ **WITHDRAWN 2026-07-18 — not a codegen defect.** Reclassified as a **by-design
allowed divergence**, not a bug (`oracle/policy.yaml`; finding
[`F-0018`](../findings/F-0018-c-embedded-nul-string-truncation/NOTES.md)).

Original hypothesis: the C backend emits `SOFAB_OBJECT_FIELDTYPE_STRING` (NUL-terminated), so
an embedded U+0000 in a `string` is lost on re-encode (`A\0B` → `A`) — the string analogue of
G-0012's unsized blob. **Why it is *not* a codegen bug:** the C object API deliberately models
a `string` as a C string (`char[]` + `strlen`), and a C string's length *is* "up to the first
NUL" — `sofab_ostream_write_string`'s `strlen` is correct, not defective. The corelib also
receives the value in full (the istream fills the buffer and the strict-UTF-8 check validates
all bytes); the projection to first-NUL is a property of the NUL-terminated representation, and
the lossless path is the byte/length (visitor) API. Forcing a sized-string object field would
de-idiomatize C strings for a pathological input. So this is a **type-representation projection**,
tolerated in `policy.yaml` (axis `accept_value`, spec basis MESSAGE_SPEC §8), not a generator
change. G-0015 is retired and the number is not reused.

## G-0016 — generated Rust `try_decode` discards INVALID via `?` when the message is also truncated

**Status:** ✅ **fixed in sofabgen 0.19.4** ([generator#190](https://github.com/sofa-buffers/generator/issues/190), 2026-07-21). Finding
[`F-0024`](../findings/F-0024-rust-trydecode-incomplete-over-invalid/NOTES.md). Generator-only
(sofabgen **Rust backend**); no corelib change. **Re-verified:** the generated `try_decode` now emits
the ordered form below (`message.rs:235/242/246`); the 4 isolates → 0 divergences across all 12, and
the malform×truncation sweep (§5.2) is green — all 18 malformed×{complete,trunc} → `R`, 0 conformance
failures. The axis was promoted from report-only to blocking and the vectors into `corpus/regression/`
(`F0024_*`). Below is the original defect (0.19.3).

The emitted `probe_dec::try_decode` (generated `message.rs`) does:

```rust
is.feed(data, &mut v)?;                          // (~234)  ← `?` returns feed's Err(Incomplete) here
invalid = v.inv;                                  // (~236)  ← skipped under truncation
…
if invalid { return Err(sofab::Error::InvalidMsg); }   // (~240)  ← skipped
```

The generated visitor sets the sticky `v.inv = true` for every **schema-bound** violation the corelib
cannot know: invalid UTF-8 (`from_utf8 => Err => self.inv = true`), over-count arrays (`else { self.inv
= true }`), over-length string/blob (`if total > N`), `string_array` element id ≥ 5. But `IStream::feed`
returns `Err(Error::Incomplete)` whenever the bytes end mid-item, and the **`?`** propagates that
*before* `v.inv` is consulted. Net effect: an input that is **both** malformed **and** truncated decodes
to `Incomplete` (`I`) instead of `InvalidMsg` (`R`) — a MESSAGE_SPEC §5.2 precedence violation (INVALID
must dominate INCOMPLETE).

**Established as codegen, not corelib:** corelib-rs `feed` correctly reports only the *structural*
outcome (`istream.rs:170-176`); `deliver_payload` returns `usize` (no error) and the `string` visitor
callback is default-empty (`istream.rs:57`) — UTF-8 and schema bounds are the generated visitor's job.
The other shared-callback backends (csharp/java/zig) and all non-callback backends emit `R` on the same
input, so the mis-ordering is specific to the Rust backend's template.

**Fix (symmetric, one template for `rs` + `rs-no-std`):**

```rust
let r = is.feed(data, &mut v);
if v.inv { return Err(sofab::Error::InvalidMsg); }   // §5.2: INVALID dominates INCOMPLETE
r?;                                                   // only then surface a clean truncation
```

Found by the 8 h pacemaker round (2.24 G execs) as the dominant divergence class (63 % of sampled
verdict-splits); delta-debugged to an 11-byte reproducer with a four-vector control set that isolates
ordering from validation.

## G-0017 — sofabgen provisions the rust-nostd corelib features from the schema's *used* wire types, so the decoder can't §7.3-skip an array / fp64 field

**Status:** 🔴 **OPEN** — [generator#215](https://github.com/sofa-buffers/generator/issues/215). Finding
[`F-0027`](../findings/F-0027-nostd-feature-gated-skip-rejects-array-fp64/NOTES.md). Generator-primary,
**corelib-rs-no-std implicated** (the F-0010 "occasionally both" shape). Found 2026-07-22 by the WP-01
union pass of the wiretype (§7.3) sweep — the first sweep run against a schema (`probe-union`) that
declares **no array and no fp field**.

corelib-rs-no-std is a streaming push-parser whose wire-type support is **cargo-feature-gated** (an
intentional embedded code-size knob — `vendor/corelib-rs-no-std/Cargo.toml` `[features]`: `array`,
`fixlen`, `fp64`, `sequence`, `value64`). The gate covers **parsing/skip**, not merely field storage:
in `src/istream.rs::on_header` the array arms are `#[cfg(feature = "array")]` and fall through to
`_ => Err(Error::InvalidMsg)` (:331) when off; the fp64 fixlen arm is `#[cfg(feature = "fp64")]`
(:386-392) and its subtype otherwise fails `FixlenType::from_raw` (:352). One dispatch serves both
decode-into-field and read-and-discard, so a build without a feature **cannot skip** that wire type.

sofabgen (`--lang rust`, `drivers/rust/build.sh:53`) writes the driver `Cargo.toml` and selects the
`sofab` dependency's feature list from the wire types the **schema declares**:

| schema | generated `features = [...]` | skip an array / fp64 field |
|---|---|---|
| `probe` (arrays + fp present) | `["array","fixlen","fp64","sequence","value64"]` | ✅ `A` (skipped, §7.3) |
| `probe-union` (no array, no fp) | `["fixlen","sequence"]` | ❌ `R invalid_msg` |

(The feature list is sofabgen's, not `build.sh`'s — `build.sh` only appends the `limit` feature,
lines 83-88.) **Why it is a bug:** §7.3 skip-ability is **schema-independent** — a field can receive
*any* wire type as a mismatch, and an *unknown* id can carry *any* construct, both of which MUST be
skipped. Provisioning the corelib with only the wire types the schema *uses* therefore compiles a
**§7.3-non-conformant decoder**: it rejects (`InvalidMsg`) a well-formed skippable array/fp64 field that
all 12 other drivers — including `rust-std`, whose corelib is not feature-gated this way — skip. Minimal
isolate `0300` (a 2-byte empty `VARINTARRAY_U` at id0).

**Established as generator (with corelib implicated), not decode-logic codegen:** the generated decode
logic is identical for `rs` and `rs-no-std` (one `driver.rs`), and `rust-std` accepts — so it is not the
emitted decode template. The two-way sibling split (CLAUDE.md diagnostic step 3) — `rust-std` agrees with
the family, `rust-nostd` on `probe` (features on) skips fine, only `probe-union` + no-std rejects — pins
it to the **feature configuration**, which only codegen derives from the schema and only codegen writes.
Per the triage's step-2 test, the corelib was *handed* a feature config and faithfully rejected → the
caller (codegen) is the bug.

**Fix (sofabgen):** for the **decoder**, emit the full wire-type feature set
(`array` + `fixlen` + `fp64` + `sequence`, keeping the existing `value64`/width policy) regardless of
which wire types the schema declares — a skip path must exist for every wire type. **Corelib-side
alternative (implicated other end):** make corelib-rs-no-std's skip path feature-independent
(read-and-discard any wire construct even when its decode-into-field arm is compiled out), so a
`--features fixlen,sequence` build stays §7.3-conformant. Either closes the divergence; the sofabgen
change is the smaller, schema-driven one and is where attribution says to start.


## G-0018 — schema-bound INVALID + truncation reported INCOMPLETE (§5.2; the F-0024 class, still open across backends)

**Status:** 🔴 **OPEN** — [generator#216](https://github.com/sofa-buffers/generator/issues/216). Finding
[`F-0032`](../findings/F-0032-schema-bound-invalid-vs-truncation-go-cpp-ts-dart/NOTES.md). Generator; the
F-0024/G-0016 ordering class, resolved only for some (bound, backend) pairs.

A message that is both a schema-bound violation (over-maxlen / over-count / over-index / invalid-UTF-8)
and truncated is reported `INCOMPLETE` by several backends where §5.2 (documentation#15, adopted) requires
`INVALID` — INVALID dominates INCOMPLETE. `count`/`maxlen`/`id` are schema facts, so the bound check and
the decision to check it **at the deciding word/header** (before propagating a truncation `Incomplete`)
are generated code. The split varies by bound: over-maxlen+trunc → go/cpp/ts/dart `I`; over-count+trunc →
9 backends `I` (even Rust — F-0024's fix covered UTF-8/over-len, not the compact-array count path);
over-index+trunc → cpp `I`. **Fix:** apply the F-0024 pattern (generator#190) to every schema-bound check
in every backend — reject as soon as the word/header shows the violation.
