# Crucible TODO

Open work **on Crucible itself**. Fixes for the corelib/generator bugs Crucible found are
**not** here — they live in the owning repos (catalog: [`../results/FINDINGS.md`](../results/FINDINGS.md),
codegen defects: the `G-00NN` rows in [`FINDINGS.md`](../results/FINDINGS.md), spec clauses: adopted upstream in `documentation` (MESSAGE_SPEC/CORELIB_PLAN)).
Crucible's job is to catalog, attribute, and **verify** them.

**Blob-array integration 2026-07-21 (F-0013 blob-path follow-up):** a `blob_array` (id 201, the blob
analogue of `string_array`) was added to `schema/probe.sofab.yaml` and wired through all six sweep axes
+ `gen.py` + the truncation rich message. Drivers rebuilt schema-agnostically (no driver change). Two
results: (1) the **over-bound §7.1 blob path is GREEN** — over-index / over-maxlen blob elements → all
12 reject, so `_BlobSeq` enforces its `count`/`maxlen`; the long-open F-0013 blob-path re-check is
**answered**. (2) A **new finding, F-0026** — the §7.4 `blob_array` wrapper **re-open** keeps a stale
zeroed element on the C object API (corelib-c-cpp `sofab_object_init` never resets a sized blob's
companion length); `string_array` is uniform. Corelib-only, minimal isolate. *(The carve-out this described is
gone: `engine/structured/sweep_repeated_id.py:97` records that blob-wrapper reopens agree
across all drivers, and the CI sweep of 2026-08-18 reads `[sweep_repeated_id] 159 vectors —
0 divergence(s)`. Corrected 2026-08-18; the sentence had outlived the exclusion.)*

**Array-of-struct integration (WP-05) — DONE 2026-07-27** on the `poc/omit-all-default-sequences`
family (F-0030 / corelib-c-cpp#109 fixed there): `struct_array` (id 202, `struct{k: u32, v: string
maxlen 16}`, count 5) is in `schema/probe.sofab.yaml`; `gen.py` encodes it canonically (§2/§5.1 **as amended by
documentation#31**: interior all-default element = id **gap**, the last element always written —
as an empty frame when all-default — and an *empty* array omits the wrapper) with 8 `sw_*` value
vectors; the `struct_wrapper` node landed in all 9 walkers (5 runtime:
py/go/ts/java/cs; 4 generated: cpp-shared/rust-shared/zig/dart; C is descriptor-generic) +
`materialize.py`; `sweep_positions.py` carries the new positions (`seq_swrapper` wrapper, element-0
`seq_struct`, element k/v leaves) so the position-driven axes sweep them, and
`sweep_empty_frame.py` pins the element rules (interior gap / last element kept).
Array-of-union / array-of-array remain follow-ups (below).

**docs/improvements.md work packages — COMPLETE 2026-07-23 (all 11 landed or deferred-with-reason).**
The 2026-07-22 coverage-audit backlog is cleared: WP-01/02A/03/04/05/06/07/08/09/10/11 all merged (PRs
#88,#94,#90,#91,#93,#95,#96,#97,#98,#99,#92). Surfaced findings **F-0027..F-0032** (+ spec hole
documentation#24), 10 upstream issues. `docs/improvements.md` is retired; the **deferred residue** lives
here:
- [ ] **WP-02 Part B** — union *materialized* (element-access) oracle: the C anchor materializes a union
  out-of-the-box (form `{opt_id:value}` per member), but the 6 runtime + 6 generated walkers need the
  `union` descriptor node + a `materialize.py` union reference (~12 walkers across 10 langs). Part A
  (union cross-encode) is green and gated.
- [x] **WP-05 completion** — DONE 2026-07-27 (see the dated entry above).
- [x] **WP-08(c) — DONE 2026-08-17: measured, and the family is correct in every cell.** The
  vectors this item asked for now exist — `def_arr` (`array of u32`, `default: [7, 9]`) in
  `schema/probe-dyn.sofab.yaml`, five isolates in `corpus/limits/default/`, swept by
  `run_dim default` in `scripts/run-limits.sh`. **0 divergences over the 10 heap drivers.**
  What the item got wrong is its framing: it called this "the only §2 case with no vector", but
  the *compact* array form is what carries an explicit empty array here, not the wrapper frame —
  **§3 (~line 236) states that a length of `M = 0` is the explicit empty array**, and every
  driver keeps it rather than falling back to `[7, 9]`. Measured cells: absent → `[7,9]`;
  `1b 00` (compact, `M=0`) → `[]`, preserved; `1b 02 05 06` → `[5,6]`; `1b 02 07 09` (the
  declared default) → omitted on re-encode.
  **Two further vectors turned out to be a §7.3 case, not a §2 one**, and were nearly filed as a
  finding before the clause was read: a `SEQ_BEG` wrapper at a *compact numeric* array carries a
  wire type the declared type does not map to, and **§7.3 says such a field MUST be skipped** — a
  decoder MUST NOT report `INVALID` and MUST NOT decode the payload into the declared field. All
  ten drivers skip it and keep the default, i.e. they are conformant. Empty wrappers at the
  *wrapper* arrays (`string_array`/`blob_array`/`struct_array`, main schema, 15 drivers) normalize
  away correctly, as §2's empty-frame table requires.
  **What is still untested** (a test gap, not a spec question — the behaviour is fully specified):
  a **wrapper** array carrying a non-empty declared `default`. There the empty frame is the
  right wire type, §7.3 does not apply, and §2's table makes it the explicit `[]`. No schema
  declares that combination. Original note below.
  ~~the explicit `[]` that overrides a **non-empty** declared array `default`~~: still
  the only §2 case with no vector, and it needs a schema field carrying `default:` (any array now has
  an empty value — the 2026-07-27 "fixed-count has none" reasoning died with documentation#31). Add a
  defaulted array to `schema/probe-dyn.sofab.yaml` (heap roster), vectors = {absent → declared default;
  explicit empty wrapper → `[]`; framed non-default}. `sofabgen` accepts `default:` (verified).
- [x] **The materialized oracle vs §5.1 wrapper length** — RESOLVED 2026-07-28 by
  [documentation#31](https://github.com/sofa-buffers/documentation/pull/31): `count` is a
  capacity, so *highest present id + 1* is the spec's own rule and the oracle was right.
  The contradiction was in §5.1's "N for every target", now gone.
- [x] **Dynamic-array last-element rule untestable** — RESOLVED 2026-07-28: #31 generalized
  the rule from *dynamic* to **every** wrapper array, so probe's `count: 5` wrappers test it
  (`corpus/conformance/e_wrapper_*`, the `cap_sa_*` cross-encode vectors).
- [x] **The family still ships trim-on-encode / fill-on-decode** (documentation#31) —
  **DONE 2026-08-02: it does not, and no upstream issue was needed.** Both halves of this item
  had already converged and the item was simply never re-checked:
  - *The generator rollback.* `_trim_tail` / `_pad_to` are gone from **every** backend.
    `corpus/conformance/b_array_*` are **green**, not the "expected red" this item predicted:
    `[1,2,3,0,0]` and `[1,2,3]` each round-trip to themselves, so they are the two distinct
    values #31 requires rather than collapsing onto one wire form.
  - *corelib-c-cpp for F-0036.* Already resolved in sofabgen 0.21.0 (generator#248) and
    re-verified 2026-07-29; re-verified again 2026-08-02 — `c` itself round-trips all three
    reproducers byte-identically, keeping the `0e 07` trailing empty frame and the `[{}]`
    single all-default element. Nothing to file.

  Both were checked on the **value**, not on agreement alone (c / go / rust-nostd read out
  individually — C object API, heap and fixed-capacity profiles), because a family-wide wrong
  answer is invisible to a differential oracle.
- [ ] **Lazy-depth divergence sweep** (POC CORELIB_PLAN §6): the bounded hold-back
  (`SOFAB_LAZY_SEQ_DEPTH` = 8 in corelib-c-cpp; rs-no-std likewise) only becomes observable with
  all-default sequence chains nested deeper than 8 — `probe` nests 3. A dedicated deep schema + suite
  would pin the legal non-canonical frames (policy carve-out
  `bounded-lazy-seq-depth-noncanonical-frames` is already in `oracle/policy.yaml`, dormant).
- [ ] **WP-10 Part B phase 2** — an opt-in `STRICT_UTF8=OFF` suite (env-gated build variant + per-profile-class
  `policy.yaml` allowances citing §8): deferred as a non-default-config follow-up; needs the gen#85
  Unicode-string config audit first. Phase-1 reachability audit is done (byte-container profiles OFF-capable
  → raw bytes; audit table was in improvements.md WP-10, mirrored in git history).


---

## Open — engine & oracles

- [x] **DONE 2026-08-16 — enforced, and the input it names is now in a gate.** Decision: keep
      the block and teach `comparator.py` to read it, rather than delete it. A difference on the
      named axis for the named input now prints `[allowed] … <id>` and does not fail the run.
      **Matching is by bytes, not by path** — a path-bound allowance would have stopped applying
      the moment the file was promoted into a corpus, which is precisely what one wants to do
      with it; a path that no longer resolves is reported on stderr instead of silently
      legalising nothing. F-0018's reproducer is now in `corpus/regression`, so the by-design
      difference is **exercised** on every push instead of only described, and its Guard says so.
      The dormant lazy-depth entry stays where it is, still matching nothing by design.
      Original note below.
      ~~`oracle/policy.yaml`'s `allow:` block is not enforced — decide: implement or drop.~~
      `oracle/comparator.py:load_policy` reads the `comparison:` axes and nothing else; no consumer
      in the repo reads `allow:` or `notes:` (verified repo-wide 2026-08-16). So the two entries —
      `bounded-lazy-seq-depth-noncanonical-frames` (dormant by design, `applies_to: []`) and
      `c-embedded-nul-string-projection` (F-0018) — document a tolerated divergence without granting
      it. The consequence is silent: the input an entry names must be kept *out* of every gate
      corpus, or the gate goes red despite the entry, which is precisely why F-0018's reproducer is
      the one resolved finding deliberately absent from `corpus/regression`. Two honest ways out —
      teach the comparator to match `applies_to` (by content hash, not path, so a promoted copy still
      matches), or delete the block and let the finding write-ups carry the reasoning. Both beat the
      present state, where the file reads as policy and behaves as a comment.

- [x] **DONE 2026-08-18 — the chunked gate replays `corpus/regression`, and the guard is
      proven able to fail.** `replay.yml` gained a second chunked step,
      `CORPUS=corpus/regression ./scripts/run-chunked.sh --modes chunk`. Measured before
      wiring it, not after: **239 inputs x 6 chunkings x 14 drivers, 0 mismatches**, the
      whole step ~10s once the drivers are built — and they already are by that point in the
      workflow, so it costs the budget almost nothing.
      `--modes chunk` rather than the full sweep, deliberately: the split sweep is O(maxlen)
      *per driver* and does not fit over 239 inputs (that is the separate scaling item
      below). Fixed-size chunking still crosses every internal boundary at six offsets,
      which is what these three findings need.
      **The guard bites.** Breaking chunk invariance in one driver on purpose — a byte
      appended only when `SOFAB_CHUNK` is set — turned the step red with **522 mismatches**,
      naming `F0058_r2_realloc_rebases_first.bin` among them. So the finding vectors are
      genuinely re-fed rather than merely present in a directory the step points at.
      Three `**Guard:**` lines and `corpus/regression/README.md` said "half a guard, stated
      plainly" and now say what is actually gated. Original note below.
      ~~The chunked gate does not replay `corpus/regression`.~~ F-0058, F-0060 and F-0061 were
      promoted there on 2026-08-16, which holds their *one-shot* verdict — but all three are
      chunk-boundary findings, and `scripts/run-chunked.sh` runs `corpus/seeds` by default. So the
      half that matters is unguarded, and both the write-ups and `corpus/regression/README.md` say
      so rather than implying a guard they do not have. **Work:** add a CI step running the chunked
      gate over `corpus/regression` in `--modes chunk` (the split sweep over 238 inputs would not
      fit the budget), or move those vectors into a corpus that gate already replays.

- [x] **DONE 2026-08-16 — every closed finding now declares what re-checks it.** Was: 19 resolved
      findings with no standing regression guard. Fixed in three parts. (1) `check-catalog.py` gained
      the `**Guard:**` assertion, so the state is no longer reachable: a finding cannot be closed
      without naming a gate corpus, a sweep axis, or `none — <reason>`, and the declaration is
      verified rather than believed. (2) Five were already guarded under descriptive filenames and
      only looked unguarded (F-0027, F-0030, F-0049, F-0057, F-0059) — which is why the check
      matches **bytes or finding-named vector**, since a name test alone would have called them
      unguarded and a content test alone would have failed F-0003's cleaner isolate. (3) 50 vectors
      from 13 findings promoted into `corpus/regression` (188 → 238 inputs, gate green: 0
      divergences across all fifteen drivers). F-0018 stays out with a written reason — its
      divergence is by design and would turn the gate red while `policy.yaml`'s `allow:` block is
      unenforced. Original note below.
      ~~19 resolved findings have no standing regression guard.~~ Their reproducers live in
      `findings/<id>/` and are fed to the *fuzzer* as seeds, but no gate replays them:
      F-0008, F-0012, F-0018, F-0027..F-0032, F-0035..F-0037, F-0043, F-0049, F-0057..F-0061
      (42 of 61 F-findings are in `corpus/regression`; these 19 are not). Some are covered
      indirectly — the chunked findings by `run-chunked.sh` over a corpus, several by a sweep axis
      that now owns the rule — but that is an argument per finding, and nobody has made it per
      finding. Two of them are newly closed today (F-0043) or were closed with their vectors never
      promoted. **Work:** for each, either promote the vectors into `corpus/regression` or record in
      its `NOTES.md` which gate owns the rule now; F-0018 is the one case that cannot be promoted
      until the `allow:` item above is settled.

- [x] **DECIDED 2026-08-16 — stays a hand-run tool, not a gate. The reasoning lives in the file's
      own header** (`engine/structured/audit_canonical.py`), which now states what it is for, the 4
      of 10 statically checkable rules it covers, the six it does not, and the two reasons it is not
      a gate — the coverage, and the missing executable self-test. Deliberately not repeated here:
      the file owns it. Original note below.
      ~~`engine/structured/audit_canonical.py` is wired to nothing.~~ A static canonicality audit of
      the committed corpora, independent of `gen.py` (it re-derives the properties from the bytes, so
      it can catch a reference encoder that is itself wrong) — exactly the check that would notice a
      corpus drifting away from §2/§3. Nothing calls it, no CI job runs it, and it is absent from
      `ARCHITECTURE.md`'s component table. Run by hand 2026-08-16: `corpus/structured` 108 files and
      `corpus/structured-union` 16 files are **clean**; the hits in `seeds`/`conformance`/`regression`
      are the deliberately non-canonical inputs those corpora exist to carry. **Work:** gate it on the
      canonical corpora only (`structured`, `structured-union`), where a hit is unambiguous.

- [x] **DONE 2026-08-16 — the minimizer never applies a deletion it did not observe.** Three
      defects, all in the same direction: an unanswered slot (a driver that hung earlier in the
      batch) compared equal to a TIMEOUT target, so deletions "held" that were never measured; the
      single-deletion fallback was applied without being checked on its own; and a target resting on
      a hang was never re-confirmed. All three closed — unanswered now matches nothing, the fallback
      is verified, and a TIMEOUT target is re-measured (`--confirm`) with the run refusing rather
      than shrinking against something that has gone away. Verified with two fake drivers: a stable
      hang minimizes to the byte that causes it, a flaky one exits 3 and writes no file. Original
      note below.
      ~~`oracle/minimize.py` silently changes target on a TIMEOUT camp.~~ The contract
      (`run.sh:37`) is "shrink one input while its camp partition holds". It does not hold when the
      camp is defined by a `TIMEOUT`: a stall is not a property of the bytes, so the timeout stops
      reproducing after the first deletion, and the minimizer keeps shrinking against whatever camp
      the residue still lands in. Observed 2026-08-15 — both reproducers of two `TIMEOUT` camps
      (2534 B and 8461 B) minimized to the *same* 1-byte input `06`, which is the representative of
      the long-known java camp; a minimized artifact that names a different bug than the one you
      started from is worse than none. **The change:** pin the *target* camp partition at the start
      and require the exact partition to hold for a deletion to be kept, and if the very first
      candidate loses it, fail loudly rather than drift. A `TIMEOUT`-defined camp should additionally
      be re-confirmed (N replays) before minimizing at all — see the nightly `TIMEOUT` note in the
      dated 2026-08-16 STATUS-LOG entry.

- [x] **The encode oracle's flush carve-out lost its spec basis — DONE 2026-08-06.** Landed once
      corelib-ts#94 closed and the flush sweep came back clean: a refused `SOFAB_FLUSH` size is now
      a conformance failure, the `flush_na`/`flush_ok` counters and the "every size was
      inapplicable" guard are gone with the hatch they guarded, and `drivers/common/CONTRACT.md`
      states the one-byte floor. Gate re-run green, 14 drivers × 9 configs, **0 `n/a`**. Original
      note below.
      ~~`oracle/encode_invariance.py:128-137` treats~~
      exit 3 on a `SOFAB_FLUSH=n` config as *not applicable*, on the stated reasoning that
      "corelib-ts's OStream needs `n` contiguous bytes for a single write […] a real difference
      between backends, not a defect in either". **documentation#39 (`1c5f8e7`) removed that
      latitude:** §5.1 now sets a normative floor — the output buffer may be "arbitrarily smaller
      than the message — down to a single byte", and an encoder "**MUST** be able to split a single
      write across a flush; it may not require any write to land contiguously". §7.2 item 4 asks
      for the matching 1-byte encode test by name.
      Today's gate printed the evidence and passed anyway:
      `[typescript] … surfaces=stream, 5 flush size(s) n/a — 0 mismatch(es)  [OK]` — five of the six
      `FLUSH_SIZES` were skipped, so only `n=16` ever ran. The existing guard only fires when *every*
      size is inapplicable, which is why one usable size hid the rest.
      **The change:** an inapplicable flush size is a conformance failure, at minimum at `n=1`;
      keep the exit-3 escape hatch for a missing *surface* only, and say so in
      `drivers/common/CONTRACT.md` (which owns the contract prose). This turns the encode gate red
      on `typescript` until [corelib-ts#94](https://github.com/sofa-buffers/corelib-ts/issues/94)
      closes, so it needs the quarantine decision first — either hold it out of
      `SOFAB_ENCODE_DRIVERS` naming that issue, as `run-chunked.sh` does for F-0061, or accept the
      red. **Do not land the tightening without that call.**

- [x] **RESOLVED 2026-08-16 — both camps converged; nothing to attribute.** Both representatives
      are still in `corpus/interesting` (`ee44aadf12f6…`, `e59d05a8b2a6…`) and were re-measured directly:
      **0 divergences across all fifteen drivers**, and neither forms a camp in the 243-input pass over
      every finding reproducer. The `known-clusters.txt` header already recorded them as gone; this is the
      measurement behind that claim. The cause is the fixlen-header hook that closed F-0043 (generator#267)
      — both camps were the verdict-timing shape that item predicted. Original note below.
      ~~Two unattributed cluster camps from nightly 31074707585 (2026-08-06).~~ The run produced
      five new camps over the merged 9502-input corpus; three were existing baseline rows with one
      driver moved (measured the same day on the F-0043 vectors) and are now in
      `results/known-clusters.txt`. These two are **not explained and deliberately not baselined**,
      so the gate keeps failing on them:
      - `I:java | reject:<the other 14>` — 4 inputs, rep `ee44aadf12f6` (56 B,
        `09 01 76 76 05 05 20 ff ff …`). java emits an incomplete_value payload `0901`. Distinct
        from the benign java incomplete_value row, where the *verdict* is unanimous — here java is
        alone in reporting `I` at all.
      - `I:typescript,zig | reject:<the other 13>` — 2 inputs, rep `e59d05a8b2a6` (22 B,
        `c6 0c 0a 02 0a 02 … 02 92 06 07`) — a `string_array` wrapper of one-byte string elements
        followed by an element declaring a 98-byte string that never arrives.
      Both smell like the F-0043 axis (verdict timing) but neither matches a catalogued row, and
      all five push corelibs gained the fixlen header hook the night before, so the camps on that
      axis are in motion. Minimize each representative and attribute before baselining.

- [x] **MOOT 2026-08-16 — F-0043 is closed and the axis is green.** With the carve-out removed,
      `sweep_malform_truncate` runs 96 vectors with 0 divergences, so typescript is in no late camp on
      any row; the widening comment for generator#267 is no longer needed (the issue closed 2026-08-11).
      ~~typescript moved in BOTH directions on the F-0043 axis in one night (2026-08-06).~~ It left
      the late camp on the declared-width row (an improvement) and joined it on the
      over_len_string-further-offset row (a regression). generator#267's title names
      `rust, rust-no-std, java, csharp, zig` — typescript joining the late camp **widens that
      issue to a sixth backend** and is worth a comment there once the two camps above are
      attributed, since they may share a cause.

- [x] **DONE 2026-08-16 — measured, and there is no finding in it.** `r1_entangled_with_doc33.bin`
      run through the current family: **0 divergences across all fifteen drivers**. The 8-vs-7 split that
      made it unusable is gone, so there is no losing camp to promote into a finding of its own. The file
      stays in `findings/F-0061/` as the record of why it was set aside. Original note below.
      ~~Re-read F-0061's `r1` now that documentation#33 is closed.~~ `eb2311a`
      (documentation#40) turned §6.4's mid-payload UTF-8 `MAY` into a `MUST NOT` — a decoder may not
      report `INVALID` before the declared length is reached. `r1_entangled_with_doc33.bin` was set
      aside as unusable because the family split 8-vs-7 on it under that latitude; the split is now
      a conformance question. Worth measuring the whole-feed camps on it again and deciding whether
      the losing camp is a finding of its own. (Noted on generator#300.)

- [x] **DONE 2026-08-16 — the cluster baseline survives a roster change.** Rows are matched on the
      drivers a row actually names (`oracle/cluster.py:camp_matches`): the current partition and the
      baseline row are both projected onto the drivers they have in common, so a signature written
      before a driver existed still matches and the file no longer has to be re-recorded when the
      roster grows. The `# roster:` stamp added earlier the same day stays as context and is no
      longer a gate. **What still turns a camp NEW, deliberately:** a driver the row names landing on
      the other side of the split (real movement), and a driver the row does *not* name sitting alone
      in a camp — the first cut of the matching swallowed that second case, reporting "joined an
      existing camp" about a driver agreeing with nobody, which is exactly the masking this item
      warned about. Verified on four cases: unchanged baseline (accounted), a baseline predating three
      drivers that joined existing camps (accounted, with a per-camp note naming them), a driver moved
      between camps (NEW), a driver alone in a new camp (NEW).

- [x] **Two unspecified streaming contracts — FILED 2026-08-04** as
      [documentation#37](https://github.com/sofa-buffers/documentation/issues/37) (chunk
      lifetime) and [documentation#36](https://github.com/sofa-buffers/documentation/issues/36)
      (minimum caller buffer). Reading the spec at the tip **sharpened** both rather than
      dissolving them: §9.6 turns out to be a **README template**, so its "valid only during
      the callback" is guidance on what a port must *document*, not a rule — and corelib-zig
      borrows further than it, into the decoded message. And §5.1's "far smaller than the
      message" simply lacks the quantifier its decode twin has twice over ("arbitrarily small
      chunks", "one byte at a time"), which is why "conformant" spans a 16x range there. What
      follows is kept as the reasoning.

- [x] **BOTH ANSWERED — closed upstream 2026-08-05, verified against the spec 2026-08-17.**
      This item outlived its questions by twelve days; documentation#36 and #37 are closed and
      the spec repo has **zero** open issues. Neither answer was the compromise this item
      expected, and both went against an implementation:
      - **Chunk lifetime → borrowing is out.** CORELIB_PLAN §6 now carries a normative
        *Chunk lifetime* bullet: a fed chunk is borrowed **only for the duration of the `feed`
        call**, after which the caller may reuse or free it and the decoded message MUST NOT be
        affected; a decoder handing a `string`/`blob` a slice into a chunk has to copy out
        before returning. Only the one-shot `decode(buffer)` is exempt, and a port offering
        that says so (§9.6). The stated reason is exactly the one this item gave — otherwise
        the same message under a different chunking places different obligations on the same
        calling code. corelib-zig's borrow is therefore non-conformant, and was already removed
        by generator#296 (2026-08-04), so nothing is outstanding.
      - **Minimum caller buffer → a declared constant, not a fixed floor.** §5.1 no longer
        fixes one byte for everyone; it **retired that rule explicitly** (`e6c96d5`
        2026-08-07, refined by `5d19b30`/`af50742`). Only a **divisible run** (a string/blob
        payload) MUST be splittable across a flush; **atomic units** MAY be required to land
        contiguously. Every corelib MUST expose a documented `MIN_OUTPUT_BUFFER` — `1` if it
        splits atomic units, else the largest run it reserves, floor 10, **capped at 20** — and
        every buffer at or above it MUST work and produce byte-identical output. So corelib-ts
        was never the outlier this item took it for. Crucible already tracks the rewritten
        clause (`oracle/encode_invariance.py:79`, documentation#46/#48, 2026-08-11); what
        remains of it is the one-size-sweep item in the CI section, which is coverage, not spec.
      Original note below.
      ~~Two unspecified streaming contracts, both found by wiring the axes (2026-08-04).~~ Neither
      is a wire question, so the differential oracle is structurally blind to both — they are
      differences in what the *API* promises, and they only became visible once drivers started
      driving the streaming surfaces. All fourteen drivers are now wired, so the camps below are
      **counted, not estimated** — both are ready to become a `documentation` question.
      - **Chunk lifetime.** corelib-zig documents that a `string`/`blob` arriving whole in one
        chunk is **borrowed** from it and that "a fed chunk must outlive the message". Final tally
        with all fourteen drivers wired: **zig alone borrows**; ten copy; python cannot alias at
        all (its pull `Decoder` reads immutable `bytes` and copies on arrival), so
        `SOFAB_CHUNK_SCRUB` is inapplicable there too — for the opposite reason, and the driver
        says which. Both inapplicable cases exit 3 and are reported as such rather than
        manufacturing a mismatch. The question for the spec: may a decoder borrow from a fed
        chunk, and if so must the caller be told?
      - **Minimum caller buffer for a streaming encode.** corelib-ts's `OStream.ensure(n)` needs
        `n` *contiguous* bytes and only flushes before checking, so a caller buffer below the
        largest single write cannot encode at all: `SOFAB_FLUSH` of 1/2/3/5/8 are all
        inapplicable, 16 works. **Every other backend streams the same 108 values through a
        one-byte buffer** — cpp ×4, rs ×2, c, java, cs, dart, zig, py-cython. (py-pure fails at 1
        too, but that is F-0059, a defect, not a contract.) So corelib-ts is alone. The question:
        is there a minimum, and is it discoverable?

- [x] **Put `py-pure` back in `scripts/run-encode.sh` — DONE 2026-08-04**, same day F-0059 closed
      ([corelib-py#62](https://github.com/sofa-buffers/corelib-py/pull/62)).

- [x] **DONE — `py-pure` is back in `scripts/run-encode.sh`** (F-0059 closed via corelib-py#62;
      verified 2026-08-16: the gate's `SOFAB_ENCODE_DRIVERS` default lists both python engines).
      ~~Put `py-pure` back in `scripts/run-encode.sh` when F-0059 closes~~
      ([corelib-py#61](https://github.com/sofa-buffers/corelib-py/issues/61)). Its pure engine
      keeps writing into the drained buffer after a flush, so everything past the first flush is
      lost. `py-cython` is correct and stays in the roster — which is what makes this an
      engine-parity break rather than a corelib-wide one. Both engines are in the **chunked**
      roster and pass it. Adding the name back is the whole change.

- [x] **Put `typescript` back in `scripts/run-chunked.sh`** — **done 2026-08-11.** F-0061
      ([generator#300](https://github.com/sofa-buffers/generator/issues/300)) closed with
      corelib-ts#141, which stopped the cursor reading a fixlen subtype out of an incomplete
      varint. Verified before re-adding, not on the ticket: 0 mismatches over
      `corpus/interesting` (9502 inputs x 6 chunk sizes), where it had been 5, and the chunked
      gate is green with all fourteen drivers. Two reasons had stacked on one exclusion — F-0060
      first, then F-0061 — and both are now gone. The stale comment claiming `zig` was still held
      out for F-0058 (closed) was corrected in the same change; nobody is held out of that gate.

      **This is the second fix in two days that closed its issue, genuinely repaired the reported
      path, and left the axis red** (after generator#293 → #295 for zig). Both were caught by
      re-running the measurement rather than reading the ticket. Treat a closed upstream issue as a
      reason to re-measure, never as a substitute for it.

- [ ] **The split sweep does not scale to a fuzzed corpus, and that is a real gap.**
      `SOFAB_SPLIT` is swept over every interior `k`, so its cost is O(maxlen) *per driver*: over
      `corpus/seeds` (maxlen 40) that is 311 runs and unnoticeable; over `corpus/interesting`
      (maxlen 12 224) it is ~12 000 runs per driver, about 44 hours for the roster. So the
      fuzzed-corpus pass runs `--modes chunk,scrub` only — and the mode that is *missing* there is
      precisely the one that says **which boundary** broke. Sampling split points (say 64 per
      input, drawn per-input rather than globally) would keep the diagnostic and bound the cost;
      a global sweep is the wrong shape once inputs vary in length by two orders of magnitude.

- [ ] **Wire the fuzzed corpus into the streaming axes routinely.** The 2026-08-04 run was manual
      and immediately produced F-0060 (12 436 mismatches) plus 19 more instances of the F-0058
      residual — on a corpus the hand-written suites had declared green. `nightly.yml` already
      grows `corpus/interesting`; running `--modes chunk,scrub` over it there costs about a minute
      per driver and is where the yield is.

- [x] **Put `zig` back in `scripts/run-chunked.sh` — DONE 2026-08-04.** The story is worth keeping,
      because it is the case *for* re-measuring: generator#293 was fixed and closed, and the
      reassembly path really was repaired — but re-running the axis gave **25 → 14 mismatches, not
      0**. The residual (generator#295) was fixed by generator#296, which removed the borrow from
      the streaming path entirely. Verified over the 9038-input fuzzed corpus: **19 → 0**. Taking
      the first closed ticket as proof would have put zig back into a blocking gate carrying
      fourteen live mismatches.
      *Side effect:* the driver's `SOFAB_CHUNK_SCRUB` exit-3 carve-out is gone too — with no borrow
      left in the streaming path, the scrub axis applies to zig like everywhere else, and it now
      runs rather than reporting n/a. A carve-out that outlives its reason is exactly the silent
      exclusion these mechanisms exist to prevent.

- [x] **DONE — `cpp-c-cpp-dyn` is un-quarantined** (F-0057 closed via corelib-c-cpp#132; verified
      2026-08-16: all fifteen roster rows carry `blocking`, and `docs/ARCHITECTURE.md` was corrected
      in the same pass — it had gone on claiming the quarantine for days).
      ~~Un-quarantine `cpp-c-cpp-dyn` when F-0057 closes.~~ It *was* in `drivers/roster` without
      the `blocking` tag while [corelib-c-cpp#131](https://github.com/sofa-buffers/corelib-c-cpp/issues/131)
      is open: every zero-length array aborts an asserts-enabled build, and a crashing driver
      poisons every subsequent record in its batch, so `sweep_empty_frame` would be permanently
      red. It is still built and still runs under `ROSTER_TAG=`. **Check it on the next family
      bump** — a quarantine that outlives its finding is exactly the silent exclusion the
      mechanism exists to prevent. Removing the tag line is the whole fix.

- [x] **The three untriaged nightly camps — CLOSED 2026-08-03.** Rather than waiting for the next
      nightly, the 2026-08-03 06:09 artifact (still retained) was re-clustered against the
      post-fix family. **17 camps → 11**, and the three resolved as follows:
      - `7f7060b8` (22 inputs) and `8e989f1f` — **gone**. The standing hypothesis (the same root
        cause as F-0055) is confirmed by their disappearance under generator#283's fix.
      - `c5d8b383` — **survives, and is its own defect**: minimized 62 B → 32 B → a 22-byte
        isolate, triaged to **F-0056** (corelib-cpp re-parses a fixlen array's payload as a
        varint on the truncated-resume path). The earlier reconstruction failed because it
        guessed the fp32 *values* mattered; it is the **continuation bit** in the payload bytes.
      Also worth recording: re-clustering surfaced one camp that is new only in *signature* —
      F-0043 at the declared-width bound, whose partition moved when generator#279 pushed `cpp`
      from the `I` camp into the reject camp. Proven with three controls, not a new class.

- [x] **DONE — every driver that can, does.** The headline below ("no driver implements them yet")
      described 2026-08-04 and was never corrected: `scripts/run-chunked.sh` runs **14 drivers**
      today. `go` is the one absence and a declared one — corelib-go has no resumable decoder, so
      `drivers/go/meta` says `chunked_decode=none` and the gate's participant list is derived from
      that rather than typed. Since 2026-08-16 the gate also asserts each driver's stderr
      announcement, so honouring the variables is proven per run instead of assumed.
      ~~Chunked re-feed in the drivers (`SOFAB_SPLIT`, `SOFAB_CHUNK`, `SOFAB_CHUNK_SCRUB`)~~ —
      the oracle and the gate exist and now implement **all three cuts** (`oracle/chunk_invariance.py`,
      `scripts/run-chunked.sh`, wired into `replay.yml`, contract section written); **no
      driver implements them yet**, so the gate skips loudly rather than passing vacuously.
      Raised by [crucible#130](https://github.com/sofa-buffers/crucible/issues/130), which asked
      for exactly two things: a split strategy that cuts at **metadata/payload boundaries**, and
      an assertion that an `I` actually **resumes**. Sweeping every split point delivers the
      first without the harness knowing where the boundaries are; comparing the final line
      against the whole-message line delivers the second.
      *The obstacle is per-language plumbing:* every driver decodes one-shot
      (`DecodeProbe(data)`, `Probe::try_decode(data)`, …), so honouring the variable means
      reaching the corelib's streaming `feed` plus the generated visitor. **Land one driver at a
      time** — chunk invariance is an intra-driver invariant, so a single driver already earns
      its keep and none of this needs the whole roster to be useful.
      *Note it would not have caught crucible#130 itself*: generated code calls the correct
      `readBlob()`, never the broken raw overload. It catches that defect's **class**.
      **2026-08-04:** the contract is now written in full (`drivers/common/CONTRACT.md`,
      "The streaming axes") and adds `SOFAB_CHUNK=n` (fixed-size, `n=1` = byte-at-a-time)
      and `SOFAB_CHUNK_SCRUB=1` (dangling-borrow oracle) beside the two-chunk sweep, with a
      normative verdict-derivation rule so eleven backends cannot drift. `meta` now declares
      per backend what exists to drive (`chunked_decode=push|pull|none`): **push in every
      language but two** — python is pull-shaped (`deserialize(Decoder(reader))`, the driver
      wraps the chunks in a reader) and **go has none at all** (corelib-go has no resumable
      push decoder), so go must be declared absent rather than silently skipped.

- [x] **DONE 2026-08-16 — the whole roster is on this axis.** The note below ("every driver
      re-encodes with exactly one call today") described 2026-08-04. All **15** drivers now run every
      surface their `meta` declares; `go` was the last one plumbed, and needed no corelib change —
      its backend had all three surfaces and even exported the `MIN_OUTPUT_BUFFER` constant the gate
      reads. What remains of this axis is filed separately: a port with a high floor gets a one-size
      flush sweep. Original note below.
      ~~The streaming-encode axis (`SOFAB_ENCODE`, `SOFAB_FLUSH`)~~ — **oracle done 2026-08-04**
      (`oracle/encode_invariance.py`, `scripts/run-encode.sh`, wired into `replay.yml`, skipping
      loudly on an empty `SOFAB_ENCODE_DRIVERS`); the per-driver plumbing is what remains. The
      encode-side twin,
      and the second half of the hole [crucible#132](https://github.com/sofa-buffers/crucible/issues/132)
      named. Every driver re-encodes with exactly one call today, so of the three encode
      surfaces the generated API now offers — allocating `encode()`, caller-buffer
      `encodeTo()`, streaming `serialize(os)` — the round-trip oracle exercises **one**.
      The family is byte-canonical, so all three of one implementation must emit identical
      bytes for the same value, and `SOFAB_FLUSH=n` (an `n`-byte `OStream` buffer) must not
      change them either — it walks the encoder across a buffer boundary at every offset,
      the encode-side mirror of `SOFAB_CHUNK=1`. Contract written; needs
      the per-driver plumbing. `meta`'s `encode_surfaces` records which backend has which:
      TypeScript has only `stream`, C has no allocating encode, rust/python/zig have no
      `encodeTo` — and the oracle reads that key both to choose what to compare and to assert
      the contract's hard-fail on a surface the backend lacks.

- [ ] **A fixlen-payload-as-varint axis** (from F-0056). No axis emits a fixlen element payload
      made of **continuation bytes**, because none had a reason to care what the bytes of a
      well-formed element look like. F-0056 is exactly a reader that mis-seeks into such a
      payload and reads it as a varint — invisible to every value-shaped vector. Cheap to emit:
      a fixlen payload of `0x80`/`0xff` at every fixlen position, followed by a truncated field,
      with a terminator-every-N control alongside.

- [ ] **Sweep the product cells the nightly corpus exposed.** Three of the four camps triaged on
      2026-08-03 live where two correct axes meet and neither sweeps the intersection — the same
      shape as F-0044, F-0048 and F-0053 before them:
      - overlong varint (§4.1) × skipped array with a count outrunning the input → F-0053
      - [x] `ID_MAX` (§6.2) × **sequence-end** wire type → F-0054 — **DONE 2026-08-03**, swept by
        `sweep_tolerance` over all 7 sequence positions *and* the union position, with all three
        cells pinned. What follows is kept as the reasoning. **Expectation is `reject`** — settled by
        [documentation#35](https://github.com/sofa-buffers/documentation/pull/35)
        (`main@acd27a4`): the end marker's id is discarded but still bounded by `ID_MAX`.
        Pin three cells while here — id over `ID_MAX` → `reject`, id *at or below*
        `ID_MAX` → `accept` (including a non-minimal `0x87 0x00`), and a header varint
        over §4.1's 64-bit bound → `reject`.
      - over-index element × truncation **inside** the fixlen word → F-0043's finer offset
      Cheapest home for all three is `sweep_framing`, which already owns both parents.

- [x] **A tolerance axis — DONE 2026-08-03** (`engine/structured/sweep_tolerance.py`, blocking).
      CORELIB_PLAN §7.2 class **5b**: non-canonical but well-formed input MUST decode to the
      value it denotes and re-encode canonically. The class the differential oracle is
      structurally blind to — a family that is *uniformly* too strict is unanimous, and
      unanimity is what green looks like everywhere else. **49 vectors** over all 7 sequence
      positions: a sequence-end id of 3 and of `ID_MAX`, and id 0 spelled non-minimally
      (`87 00`, `87 80 00`), against the over-`ID_MAX` and over-64-bit-varint rejects as the
      strict-side contrast. The varint half of 5b stays in `sweep_varint` (WP-03) rather than
      being duplicated here. Green on all 13.
      **The runner gained `expect="same:<twin>"`** for it — accept *and* normalize, asserted
      against the canonical twin's re-encode. Verified by deliberately breaking a twin: 28
      conformance failures, so the check can fail rather than merely being green.

- [x] **A vector for F-0054's normalization half — DONE 2026-08-03** by
      `engine/structured/sweep_tolerance.py`. The 6-byte isolate closes a *skipped* subtree, so
      its whole message re-encodes to the empty byte string and the discarded id is
      unobservable — it proved the verdict only. Every tolerance vector instead closes a
      **declared** sequence holding a real field and carries `expect="same:<twin>"`, so the
      re-encode is asserted against the canonical twin's bytes. The runner additionally fails a
      `same:` vector whose twin re-encodes to the empty message, so this blind spot cannot come
      back silently.

- [x] **DONE — the carve-out was deleted 2026-08-16 with generator#281, and this entry
      simply never said so.** The prediction it ends with is now the measured state: the CI
      sweep of 2026-08-18 reports `[sweep_overbound] 67 vectors — 0 divergence(s), 0
      conformance failures`, exactly the "67 vectors, 0 divergences" it asked for. The code
      has said it all along (`engine/structured/sweep_overbound.py:62` — *"#279 landed as
      generator PR #281 and the carve-out was removed 2026-08-16"*), and `_F0052_CARVEOUT`
      no longer exists anywhere. The axis is blocking, so every green CI run since has been
      running the full 67 — a carve-out that had outlived its reason only in this file.
      Original note below.
      ~~Over-width vectors at the array-element position — WRITTEN 2026-08-03, carved out
      until [generator#279](https://github.com/sofa-buffers/generator/issues/279) closes.~~
      `sweep_overbound` now derives the declared element width from the schema
      (`Position.itype` + `INT_RANGE`, no literals — WP-11) and emits, per integer array
      position: over-the-top, at-the-top control, and for signed types under-the-bottom plus an
      at-minimum control. 49 → **67 vectors**. Verified: exactly **9 divergences, all `cpp`
      alone** (F-0052), every other impl correct, all at-bound controls green, 0 conformance
      failures. Because the axis is **blocking**, the width block sits behind
      `_F0052_CARVEOUT = True` — the F-0026 pattern: hold the one red cell, not the whole axis.
      **Removing it is a one-line deletion** when #279 lands; re-run and the axis should read 67
      vectors, 0 divergences.
      64-bit widths are skipped by construction — no encodable value exceeds them, the same
      reasoning corelib-cpp's `ElemBound::of<E>()` uses to stay unarmed there.



- [x] **DONE 2026-08-17 — the spec decided it, so the work was to enforce the decision
      rather than invent a taxonomy.** The two-tier grade this item asked for is now in
      `oracle/comparator.py`, but not as a comparison: **the class of each line is judged
      on its own**, whatever the other drivers said. That is the whole point, and it is
      what `reject_class` structurally cannot do — that axis fires on *disagreement*, so a
      forbidden class named by **every** implementation would be unanimous and therefore
      green. Verified with fake drivers rather than reasoned about: `usage` + `usage`
      (unanimous) exits **1**, `usage` + `invalid_msg` exits 1, `other` + `other` exits 0
      with a warning, `invalid_msg` + `invalid_msg` is silent.
      Three groups now, owned by `oracle/canonical.md`: `invalid_msg` / `limit_exceeded`
      are expected; `argument` / `buffer_full` / `other` are **legal but reported** (§6.3
      permits language-specific conditions, but on the decode path each means a generated
      layer erred where the family cleanly rejects — the F-0003 / F-0008 shape); and
      **`usage` is forbidden**, because §6.3 abolished the category outright: *"a
      type-mismatched read is not an error at all […] there is no result code for 'invalid
      usage'"*.
      **Measured before adding the check**, over `corpus/interesting` (6000 inputs),
      `crashes`, `regression`, `conformance`, `seeds`, `union` and `structured` across all
      fifteen drivers: **every reject is `invalid_msg`**. So the check starts green and
      exists to keep it that way. One source stays reachable in principle — `corelib-py`
      still defines `SofaStateError` (`types.py:155`) and `drivers/python/driver.py` maps
      it to `usage`. It never fires, because the generated §7.3 guards skip a mis-typed
      field before any read reaches it, which is exactly what §6.3 says should happen — so
      the fuzzer structurally cannot reach the path, and this came from reading the clause.
      **Filed 2026-08-17 as [corelib-py#96](https://github.com/sofa-buffers/corelib-py/issues/96)**
      once a reproducer existed (4 wire bytes, both engines), **merged the same day** and
      **verified here 2026-08-18** — all four type-mismatched reads now return `None` and
      skip, on the pure and cython engines alike, and `SofaStateError` is a deprecated
      alias of `SofaRangeError`. The verification took two attempts: the first reported the
      pre-fix behaviour because a compiled `_speedups` artifact from before the fix was
      still sitting in `vendor/corelib-py/src/` — a `git checkout` does not remove one, and
      `sys.path` order made it win over the freshly checked-out sources. The stale-build
      rule applies to a corelib's own build outputs, not only to the drivers'. The write-up splits the seven
      throw sites: three encoder ones are genuine caller mistakes and rename to
      `SofaRangeError` — which already *is* §6.3's `InvalidArgument` — while four decoder
      ones must not raise at all. `_take_scalar` is one site guarding both conditions and
      has to be split. corelib-cpp/-java/-cs removed the code and skip per §7.3, so py is
      the last port. Original note below.
      ~~Finer reject-class taxonomy.~~
      Investigated 2026-07-17: the corelibs collapse *all* malformed-wire reasons into one
      `InvalidMessage` (spec §6.3), so a *semantic* taxonomy (truncated / bad-varint / depth /
      …) is **not** available from return codes. The achievable, valuable version is a
      **two-tier grade**: normalise the class mapping across the whole roster, then distinguish
      `invalid_msg` (a clean wire-reject) from `usage`/`argument`/`other` (a generated-layer /
      API error). Make the **cross-tier** case hard — an impl whose generated layer errors
      where the family cleanly rejects is a codegen smell (the F-0003/F-0008 class) — and keep
      within-tier differences soft. Also de-noises the fuzzer clusters (a big share of residual
      "divergences" are reject_class-only, verdict-agreeing).

      **Re-checked against the spec 2026-08-17 (CORELIB_PLAN §6.3, main@dd2866b), and the
      target moved.** The clause now fixes the taxonomy at **five** codes — `None/OK`,
      `BufferFull`, `InvalidArgument`, `InvalidMessage`, `LimitExceeded` — and closes the tier
      question outright: *"A type-mismatched read is not an error at all"* (the §7.3 skip), and
      *"there is therefore **no** result code for 'invalid usage': every remaining caller
      mistake is an out-of-range argument (`InvalidArgument`) and every remaining malformed
      input is `InvalidMessage`."* `oracle/canonical.md:16` still admits `usage` and `other`.
      Those name states the spec says **cannot occur**, so this is no longer "invent a
      taxonomy" — it is an assertion: **a driver emitting `usage` or `other` is reporting a
      conformance defect**, and the class should fail rather than be compared. `reject_class`
      went hard 2026-08-16 and fires zero times, but that measures agreement, not this: a
      family-wide `usage` would be unanimous and green. **Work:** decide what each driver maps
      to `usage`/`other` today (some may be dead branches), then either fail on them or delete
      them from the grammar; keep `limit_exceeded` (§6.2.1 gives it its own code) and
      `buffer_full` (§6.3 keeps it, encode-side).

- [x] **DONE 2026-08-17 — the axis exists, and one port of eleven had anything to test.**
      The static survey the item asked for first, done by reading each corelib rather than
      guessing: **only `corelib-go` implements the permission** (`WithPassThrough(bool)`,
      `limits.go:128`). Eight ports state "no pass-through" in their own README
      (c-cpp, cpp, rs, rs-no-std, zig, dart, py, ts) and `cs`/`java` do not mention it —
      consistent with §5.1, which notes that a UTF-16 port has nothing to hand over because
      its wire bytes do not exist until the encoder produces them. Every driver's `meta` now
      records the answer as `pass_through=yes|no`, `scripts/driver-audit.sh` fails on an
      absent declaration (an absent key is nobody having looked; `no` is somebody having
      checked), and the ledger prints the column.
      **The axis is in the encode gate** (`SOFAB_PASSTHROUGH=1`, contract in
      `drivers/common/CONTRACT.md`), asserting both halves: the bytes must be identical to
      the default path, **and** the permission must actually have been exercised — the
      driver reports `passthrough handovers=<n>` at EOF and a count of **zero fails**.
      Without that second half the axis would be the vacuous green it exists to prevent: a
      port that took the permission and quietly copied anyway emits identical bytes.
      Both failure modes were provoked rather than assumed: corrupting one passed-through
      byte turned it red on exactly the two vectors that hand a run over, and running it
      over `corpus/seeds` (no payload above the threshold) turned it red with "0 handovers".
      *Two facts worth keeping.* Go passes a **blob** run through once it exceeds the output
      buffer but a **string** only past 4096 bytes (`encoder.go:851`) — legal, since §5.1
      lets a port ignore the permission entirely — so only blobs reach this path at
      `probe`'s scale. And the corpus triggered it exactly **once** in 110 vectors until
      `ba_maxlen_full` (five maxlen-64 blob elements) was added, which also exercises the
      wire-order rule — buffered bytes drained before the passed-through run — five times
      per input instead of once. Six handovers now.
      **What is deliberately not covered:** a port declaring `no` is not exercised at all,
      because the other fourteen drivers do not recognise the variable and would exit 0
      having ignored it. Proving the refusal instead of assuming it is per-driver work,
      filed as its own item below. Original note follows.
- [ ] **A driver that cannot pass through should be made to say so.** The pass-through axis
      exercises the one port that implements the §5.1 permission and skips the other
      fourteen, because they do not recognise `SOFAB_PASSTHROUGH` and would exit 0 having
      ignored it — indistinguishable from honouring it, since the output is byte-identical
      either way. That is the same "silent skip" shape the encode gate's surface hard-fail
      and the chunked gate's stderr announcement each exist to close, and it is the reason
      `meta`'s `pass_through=no` is currently believed rather than verified. **Work:** have
      every driver recognise the variable and exit **3** when its backend grants no
      permission, then assert that refusal in `encode_invariance.py` exactly as the missing
      surface is asserted today. Cheap per driver (read one env var, exit 3), fourteen of
      them, and it turns a declaration into a checked property. Until then the gate says
      "pass-through declared absent (not exercised)" on those rows rather than implying
      coverage it does not have.

      ~~The encoder's pass-through path is untested, and Crucible has never heard of it.~~
      CORELIB_PLAN §5.1 gained *"Pass-through of a divisible run (normative, optional)"* on
      2026-08-08 (`27ad9a0`, `c5e318b`, `f0974df`, `e34c78d`) — after Crucible's last spec
      round, and the term appears **nowhere in this repo** (grepped 2026-08-17). An encoder MAY
      hand a `string`/`blob` payload to the sink directly instead of copying it through the
      output buffer, if the caller granted it at installation (off by default), buffered bytes
      are drained first, the run is divisible, and its wire bytes already exist contiguously as
      caller memory. A port MAY always copy and stay conformant.
      **Why the existing gates are structurally blind to it:** the output is byte-identical
      either way, so neither the round-trip oracle nor `encode_invariance.py` can see it — the
      same shape as the chunk-lifetime question, which is exactly the class that produced
      F-0058/F-0060. Two rules *are* assertable:
      - **borrow lifetime** — passed-through memory is borrowed only for the duration of the
        sink call and MUST NOT be retained. That is the encode-side twin of
        `SOFAB_CHUNK_SCRUB`: grant pass-through, have the sink copy, scrub the source buffer
        after every sink return, and require the accumulated output to be unchanged.
      - **mutual exclusion** — a sink granted pass-through MUST NOT call the buffer-set
        operation, and a port SHOULD reject such a call as it rejects an undersized buffer.
      **First step is cheap and static:** find out which backends implement the permission at
      all (a `meta` key beside `min_output_buffer`, the way `encode_surfaces` records the
      three surfaces), because a family where nobody implements it needs no axis yet — but
      nobody has checked, and "off by default" is precisely how an untested path stays quiet.
- [x] **Element-access / materialized-value probe** — **DONE 2026-07-21, all 12 drivers.**
      A second canonical form (`oracle/materialized.md`): `SOFAB_MATERIALIZE=1` makes a driver
      emit a full walk of the **decoded value** (every field + array element, floats as raw bits,
      `len:hex` strings/blobs) as its `A` payload, targeting the round-trip form's recorded blind
      spot (`canonical.md` §Tradeoff — a decode that differs only where the sparse wire elides,
      F-0010's class). Reuses the comparator unchanged (`accept_value` axis); `scripts/materialize.sh`
      runs the 12-driver differential over `corpus/structured` → **75×12, 0 divergences**, every
      driver matching the `engine/structured/materialize.py` reference byte-for-byte; the default
      round-trip path is unchanged. C is the schema-agnostic anchor (object-descriptor walk); the
      other 11 hand-walk with a schema-type table. **Measured design fact:** numeric arrays are
      already materialized to N in memory family-wide, so this form's live signal is the **wrapper
      arrays** + **element-level fidelity** + **regression-proofing**, not F-0010's exact shape
      (resolved). Surfaced nuance: the **Go** corelib leaves an absent numeric array `nil` (its
      driver pads to N for the dump — same logical value, benign).
    - [x] Wired into CI as a standing gate (`replay.yml`, 2026-07-21): the materialized differential
          (agreement, 75×12) + the C-anchor conformance check vs the reference (a family-wide-wrong
          dump is agreement-green but conformance-red).
    - [x] **Generated schema-type table** (2026-07-21, `engine/structured/schema.py` →
          `oracle/materialized-schema.json`): the typed field tree (kinds/ids/counts/nesting) is now
          derived from `schema/probe.sofab.yaml`, not hardcoded. The **reference** (`materialize.py`)
          is driven by it — the ground truth is schema-agnostic, so a schema type/shape change updates
          it automatically. `materialize.sh` regenerates + `cmp`-checks the committed artifact so it
          can't drift. **This also backstops the drivers:** the CI conformance check runs every driver
          against the schema-driven reference, so a hardcoded driver walker that fails to follow a
          schema change now **fails the gate loudly** instead of drifting silently.
    - [x] **Reflection-language walkers consume the descriptor** (2026-07-21): go/ts/java/cs/python
          now load `oracle/materialized-schema.json` at runtime and walk the decoded value generically
          (reflection by field name) — **schema-agnostic**, no hardcoded shape. `materialize.sh` exports
          `SOFAB_MATERIALIZE_SCHEMA`; 75×12 stays 0-divergence. So the schema-agnostic set is now C +
          go/ts/java/cs/python (7 of 12 targets).
    - [x] **rust / cpp / zig generate their walker source** (2026-07-21): no usable runtime reflection,
          so each has a build-time generator (`drivers/<lang>/materialize_gen.py`, run by `build.sh`)
          that unrolls the descriptor into straight-line walker source — regenerated every build. All 12
          drivers are now **schema-agnostic**: a schema change reflows to every walker with zero
          hand-editing. 75×12 stays 0-divergence; the generators run cleanly during the default `run.sh`
          builds too. **The materialized-value oracle is fully complete** — no open refinements.
- [ ] **Encoder-side fuzzing.** The pacemaker is **decode-only**; encoders are only exercised
      via cross-encode's deterministic values. Mutate the *value* (floats, boundary ints, array
      sizes, unicode) and feed all 12 *encoders* → compare bytes. Reaches encoder divergences
      (and encoder UB like the old F-0002) via coverage, not just replay.
- [~] **Multi-impl coverage** (the biggest architectural gap) — **first second engine wired
      2026-08-02; four languages still unwired.** Only the C corelib *steered* the fuzzer, so it
      explored C-complex paths only — F-0012 (a TS bug) was found via the differential, not
      coverage. **Go is now a real second steering engine**: `scripts/fuzz-go.sh` +
      `drivers/go/gocorpus.py` run Go's native coverage-guided fuzzer over corelib-go's decoder,
      seed from the shared corpus and harvest back into it; wired into `nightly.yml` after the C
      pass at a quarter of its budget.
      **It paid off on the first run** — 60 s, 2.99 M execs, 299 new inputs, and the differential
      over the grown corpus went **15 → 17 clusters**: two divergence classes the C-steered
      corpus had never produced (see `results/CLUSTERS.md`; both untriaged). That is the thesis
      of this item, demonstrated rather than argued.
      *Remaining:* entry points exist but are unwired for **ts** (`drivers/ts/fuzz.ts`), **java**
      (`drivers/java/FuzzProbe.java`, Jazzer present), **csharp** (`drivers/cs/Fuzz.cs`, SharpFuzz
      present); **rust** has none at all (cargo-fuzz present) and is the most valuable next one —
      six of the eight open findings involve a rust backend, so its paths are where the family is
      demonstrably weakest. zig/dart remain placeholders.

- [ ] **Differential-cluster A/B** of the grammar vs byte-level corpora — the mutator's real
      "done when". Ideally in the nightly. (Mutator itself is built; `engine/mutator/DESIGN.md`.)

## Open — schemas & corpus

- [x] **blob array** — **DONE 2026-07-21.** Added `blob_array` (id 201) to `probe` + all six sweep
      axes. The over-index / `maxlen` blob paths (§7.1) that F-0013 could not test for lack of a field
      are now **green** (all 12 reject); the §7.4 wrapper re-open surfaced **F-0026** (corelib-c-cpp,
      open). The C++ heap `_BlobSeq` guard held.
- [ ] **More corner-case schemas** beyond the single full-scale `probe`:
  - **recursive types** (`$ref`, trees) to exercise `MAX_DEPTH`, and a **map** (`array of
    struct{k,v}`) — the last format features `probe` doesn't cover.
  - *(update 2026-07-23: `MAX_DEPTH` is already exercised by `engine/structured/sweep_framing.py`
    — the past-`MAX_DEPTH` nesting vector that surfaced F-0029 — but via synthetic bytes, not a
    recursive `$ref` schema. The **map** (`array of struct{k,v}`) is modeled in `schema.py`
    (`struct_wrapper`) yet held out of `probe` pending F-0030 — that is the "WP-05 completion"
    residue item at the top of this file.)*
- [x] **Corpus hygiene — DONE 2026-08-02: 5994 → 579, all 15 clusters intact.** But **not**
      by `-merge` alone, which this item proposed and which turns out to be actively wrong:
      the plain merge gives 503 files and **6 clusters**, silently discarding the corpus
      evidence for F-0045, F-0046, F-0047 and F-0048 among others. It minimizes by **C
      coverage** while the oracle is disagreement among **13** drivers, so two C-equivalent
      inputs can carry different divergences. The rule adopted instead — *coverage-minimal ∪
      every hard-diverging input* (85 of them: verdict split, or agreed accept with differing
      re-encode) — preserves hard divergences **by construction**. Soft splits are not
      force-kept (the coverage set carries 335 anyway). Table and rationale in
      [`../results/CLUSTERS.md`](../results/CLUSTERS.md). Local only — `corpus/interesting` is
      gitignored, CI gates on `seeds`/`regression`/`conformance`, so this buys triage speed
      (~10 min → under a minute per full cluster run) and changes no gate.
      **Re-apply after every fuzz round**, or the corpus regrows redundant.

## Open — waiting on upstream, then verify

- [x] **F-0039 / generator#254 — DONE (generator `main` @ 9c71fde, 2026-07-29).** The java and
      csharp backends no longer size a declared array from a header §7.3 says to skip: the
      generated `arrayBegin` now guards each allocation with `if (kind != ArrayKind.X) break;`.
      `wiretype_sweep` went **30 → 2** divergences.
- [x] **F-0042 — the last two `wiretype_sweep` cells — DONE (2026-08-01).** The corelib
      array-header hook widened to carry the fixlen element **subtype** (all seven issues closed:
      corelib-go#58, -java#53, -cs#45, -dart#23, -rs-no-std#60, -rs#40, -zig#27) and the backends
      consume it in generator#259. The carve-out is deleted; `wiretype_sweep` is **361 → 363
      vectors, green**, and the six reproducers are in `corpus/regression/` as `F0042_*`.

- [x] **File the three open findings upstream — DONE (2026-08-01).** All three went to
      `generator`; each has a G-number in `results/FINDINGS.md`. Now waiting on the fixes:
      - ~~**F-0038's dart residual** → [generator#265](https://github.com/sofa-buffers/generator/issues/265)
        (**G-0025**)~~ — ✅ **FIXED 2026-08-01, verified 2026-08-02.**
        [generator#269](https://github.com/sofa-buffers/generator/pull/269) emits the
        resolve-then-leave override unconditionally, so a string-free scope no longer inherits
        corelib-dart's validating default. **F-0038 is fully resolved** (all 13 agree; vectors
        promoted into `corpus/regression/`, 112 → 117).
      - **F-0033** → [generator#266](https://github.com/sofa-buffers/generator/issues/266)
        (**G-0026**): enforce the declared integer width as a validity bound (documentation#32,
        §1/§7.1 — over-width is INVALID, never masked, never kept). Today only `c` /
        `cpp-c-cpp` are conformant.
      - **F-0043** → [generator#267](https://github.com/sofa-buffers/generator/issues/267)
        (**G-0027**): decide a schema-bound violation **at the word** that carries the violating
        number, not after payload bytes arrive.

- [x] **Triage the two clusters the Go engine found — DONE 2026-08-02.** Neither was what its
      camp suggested at 256 / 374 bytes. Cluster 14 → **F-0050**, a `corelib-c-cpp` off-by-one
      permitting nesting depth 256 against `MAX_DEPTH` 255 (the *closed* 256-deep vector is
      accepted, so not a precedence bug). Cluster 15 → **F-0047's second symptom** (374 B → 5 B):
      the leaked child lands in the wrapper's index scope, so a child id ≥ the schema `count`
      trips §7.1 and flips the verdict; threshold measured exactly at 5, and it adds **cpp** as a
      seventh affected impl whose half may be corelib-cpp rather than codegen.

- [x] **Boundary vectors for the format ceilings in `sweep_framing` — DONE 2026-08-02**, and
      the item's premise was half wrong. `MAX_DEPTH` now has 255-vs-256 vectors, closed and
      truncated, and the axis fails on exactly the two F-0050 vectors and nothing else (14 → 22
      vectors). **Promoted to blocking 2026-08-02** — [corelib-c-cpp#126](https://github.com/sofa-buffers/corelib-c-cpp/issues/126) fixed the same day; axis green (22 vectors).
      *Two corrections to what this item assumed.* (a) The gap was **not only** the boundary: the
      old vector nested through `hdr(0, WT_SEQ_BEG)`, i.e. root id 0 — a scalar opened as a
      sequence, which §7.3 skips — so the whole chain sat inside a skipped subtree and exercised
      a *different depth counter*. Depth 256 built that way is unanimous; only a nest through the
      declared `nested` (id 10) splits. Both constructions are now swept. (b) `FIXLEN_MAX` and
      `ARRAY_MAX` get **no** boundary vectors, deliberately: §6.2 makes them *"up to 2³¹−1 (may
      be 65,535 on constrained profiles)"*, so no single boundary value exists that the family
      must agree on — at 65,536 a constrained profile must reject and a heap profile must accept,
      and that split is legal. Only fixed format-wide ceilings (`ID_MAX`, `MAX_DEPTH`) can be
      swept at their boundary, and `ID_MAX` already was.



- [x] **Triage the 2026-08-01 fuzz round's unattributed clusters** — **DONE**, all 17 clusters attributed (the sub-items below record how). (snapshot + camps in
      [`../results/CLUSTERS.md`](../results/CLUSTERS.md)). Priority order:
      1. [x] **Cluster 3 — DONE 2026-08-01: minimized to F-0044** (128 B -> 6 B, three controls).
         A child of a *skipped unknown sequence* binds into the enclosing scope on the
         flat-visitor backends. Filed as generator#268 (**G-0028**).
      1b. [x] **Clusters 14 / 15 — DONE 2026-08-01.** 14 is the **product of F-0044 and F-0033**,
         not a finding of its own (proven with an in-range control and a no-wrapper control);
         it closes when either does. 15 minimized to **F-0045** (468 B -> 8 B): a §7.3-skipped
         array leaves `afill` armed and the next scalar is absorbed into an array. Filed as
         generator#270 (**G-0029**).
      2. [x] **Clusters 4, 6, 7, 8, 10, 17 — DONE 2026-08-01**, all minimized and attributed:
         **4 + 17** are F-0043 at an uncovered position (a `string_array` element, `maxlen: 64`)
         and demonstrate its off-by-one crisply — 0 payload bytes → 8 impls say `I`, 1 byte → 3.
         Worth appending to generator#267. **6** → **F-0046** (generator#271). **7** is a **legal**
         divergence: CORELIB_PLAN §6.4 grants a `MAY`, raised upstream as documentation#33 —
         re-triage once that rules. **8** is F-0044's second symptom (verdict flip; noted on
         generator#268). **10** → **F-0047** (generator#272).
      3. [x] **Cluster 5 (2026-08-01) = cluster 4 (2026-08-02), 8 inputs — DONE 2026-08-02:
         minimized to F-0048** (305 B → 11 B, 4 controls). **A finding, not the legal
         CORELIB_PLAN §6 bound it resembled** — and not a capacity issue at all: the no-std
         backend's wrapper-array **element** sink appends instead of replacing (generated
         `message.rs` 452/475, no `clear()`), so MESSAGE_SPEC §7.4 last-wins is violated and the
         accompanying guard `_e.len() != _s.len()` misfires into `buffer_full` on any duplicate
         element id at any size. rust-std gets the same position right, which is what pins it to
         codegen (**G-0032** → [generator#273](https://github.com/sofa-buffers/generator/issues/273)). That the rewrite of `istream.rs` left it unmoved is
         explained: the defect was never in the corelib.
         **This closes the 2026-08-01 round's triage — all 17 clusters attributed.**

- [x] **New sweep axis: an unknown *sequence* id carrying children — DONE 2026-08-02.**
      `engine/structured/sweep_unknown_seq.py` (§5.2 / CORELIB_PLAN §4.9), 25 vectors across
      the root and every struct scope: unknown seq × {empty, one scalar child, nested
      sequence child, child colliding with a real field id of the enclosing scope, the same
      with that field established first}. **REPORT-ONLY** in `scripts/sweep.sh` — 14/25 red
      on **F-0044** ([generator#268](https://github.com/sofa-buffers/generator/issues/268)),
      camp {rust-std, rust-nostd, java, csharp, zig} exactly as catalogued. **Promoted to blocking 2026-08-02** — #268 fixed the same day; axis green. The two collide-over-value vectors are sharper than
      F-0044's own reproducer: they show the leaked child *overwriting a live value*, not
      just appearing in an empty slot.

- [x] **New sweep axis: a repeated *element* id inside an array wrapper — DONE 2026-08-02.**
      `engine/structured/sweep_repeated_elem.py` (§7.4 × §5.1), 17 vectors over all three
      wrappers: element id repeated × {differing values, same value, empty-then-value,
      value-then-empty, repeated past `maxlen` if concatenated} + a two-distinct-ids control.
      **REPORT-ONLY** — 8/17 red on **F-0048**
      ([generator#273](https://github.com/sofa-buffers/generator/issues/273)), rust-nostd
      alone. **Promoted to blocking 2026-08-02** — #273 fixed the same day; axis green. Two results worth keeping: the
      `empty_then_value` order **passes** (an appending decoder gets that one right by
      accident — so a suite testing only it would have proved nothing), and `struct_array`
      (id 202) passes throughout, confining F-0048 to the leaf-element wrappers.

- [x] **Re-enable `sweep_malform_truncate`'s broadened truncation — DONE 2026-08-16.** generator#267
      closed on 2026-08-11 (the fixlen-header hook), so the carve-out that restricted the full
      offset sweep to the STRUCTURAL malformations is gone: the axis is back at **43 → 96 vectors**
      and green on all 15 drivers, which is what closed F-0043 / G-0027. Original note below.
      ~~The axis currently applies the full offset sweep only to the STRUCTURAL malformations; the
      schema-bound half is a two-line deletion in `engine/structured/sweep_malform_truncate.py`
      (43 → 96 vectors). The carve-out previously cited F-0032, which is resolved — it is F-0043
      that keeps it, and the boundary offset is precisely what it hides.~~

- [x] **Re-enable the *scalar* `f32_snan` in `engine/structured/gen.py` — DONE 2026-08-02.**
      generator#275 closed the same day it was filed; the generated dart field is now the public
      `int? f32Fp32Bits`. **Crucible's own half had to follow**: the upstream fix only *exposes*
      the bits, and `drivers/dart/materialize_gen.py` was still formatting the widened double, so
      the divergence would simply have become ours. The walker reads the companion now
      (`_f32Scalar`, mirroring the `_f32Elem` array path from the same day). Verified on
      `materialize.sh` — 108 × 13, 0 divergences, C anchor 0/108 — which is the only oracle that
      can see it; `run.sh` was green throughout and proves nothing here. The vector is back in
      `corpus/structured`, i.e. in a blocking gate.


- [x] **fp32 sNaN at the array element position — DONE 2026-08-02.** §6.5 requires
      bit-exactness "at **every** `fp32` position: a **scalar** `fp32` (§4.6) **and** each
      element of an **`fp32` array** (§4.8)"; only the scalar had a vector, so a defect confined
      to the array path was invisible. `arr_fp32_nan_bits` (sNaN / qNaN-payload / −NaN /
      subnormal / 1.0 control, as raw bytes) is in `corpus/structured` and green on all 13.
      Required `arr_fp()` to accept pre-packed bytes, mirroring the scalar `fp32()` escape.

- [x] **F-0022 / generator#188** — **DONE (sofabgen 0.19.4, 2026-07-21).** The generated array-fill
      arm now carries the §7.3 guard (`if self.afill == 0 { return; }`) and `array_begin` arms `afill`
      only at a real array position; a bare scalar at an array id is skipped. All 5 isolates → 0
      divergences across 12; promoted into `corpus/regression/` (`F0022_*`, gate 59 → 64).
- [x] **F-0023 / generator#189** — **DONE (sofabgen 0.19.4, 2026-07-21).** The `string_array`
      wrapper-element loop now emits the same §7.3 guard the struct-field dispatch had (TS
      `message.ts:372`, Py `message.py:446`, C++ `_StrSeq`); a mis-typed element is skipped. All 5
      isolates → 0 divergences across 12; promoted into `corpus/regression/` (`F0023_*`, gate 64 → 69).
- [x] **F-0025 / generator#193** — **DONE (post-0.19.4 sofabgen CI build, 2026-07-22).** §7.3, a
      **scalar fp field** (`nested.f32`/`f64`) receiving an fp **fixlen array** stored the element
      instead of skipping (rust-std/rust-nostd/java/csharp/zig). The **fp analogue of F-0021** (generator#183
      covered integers only): the generated `arrayBegin` now arms `askip` for the fp array kinds too, and
      the `fp32()`/`fp64()` callbacks carry the `askip` guard. **Verified:** `sweep_run.py wiretype_sweep`
      → green (319 vectors, 0 div); both reproducers → all-12-skip. Promoted the wiretype (§7.3) axis
      **report-only → blocking** in `scripts/sweep.sh`; the 2 reproducers + 2 controls into
      `corpus/regression/` (`F0025_*`, gate 73 → 77). generator#193 closed.
- [x] **F-0024 / generator#190 (G-0016)** — **DONE (sofabgen 0.19.4, 2026-07-21).** The generated
      `try_decode` now captures `feed` without `?`, checks `v.inv`, and returns `InvalidMsg` before
      surfacing the Incomplete (`message.rs:235/242/246`) → INVALID dominates a truncated tail (§5.2).
      Verified: 4 isolates → 0 divergences; malform×truncation sweep green (18 malformed×{complete,trunc}
      → `R`, 0 conformance failures). **Sweep axis promoted report-only → blocking**; 4 vectors into the
      gate (`F0024_*`, 69 → 73).
- [x] **F-0004 / generator#85** — **DONE 2026-07-18 (crucible#55).** sofabgen 0.18.0 shipped the
      strict-UTF-8 codegen (generator#162) + per-corelib checks; Crucible built all drivers with
      the check ON (c/c-cpp opt in via `-DSOFAB_ENABLE_STRICT_UTF8`; zig via `build_options`),
      added 11 invalid-UTF-8 seeds + 3 valid controls (`engine/structured/utf8_seeds.py`), and
      confirmed **all 12 `R invalid_msg`** on malformed / **all 12 `A`** on valid. Promoted into
      the regression gate (29 → 43).
- [x] **F-0018** — **CLOSED by-design 2026-07-18 (not a bug).** Embedded U+0000 in a `string`:
      a NUL-terminated C-string profile projects `A\0B` → `A` on re-encode. The corelib receives
      the full value; the projection is inherent to the C-string convenience (`strlen` is correct),
      and the lossless path is the byte/length visitor API. Recorded as an allowed divergence in
      `oracle/policy.yaml` (axis `accept_value`, MESSAGE_SPEC §8); SOFABGEN G-0015 withdrawn. A
      one-line §8 spec note (embedded-U+0000 preservation is implementation-defined for a
      NUL-terminated profile) is the only optional follow-up.
- [x] **F-0013 blob path** — **DONE 2026-07-21.** Added the `blob_array` schema (above); the
      over-index + over-maxlen blob paths (§7.1 over-bound sweep) are **green** — all 12 reject, so
      the 0.17.6 fixed-capacity fix covered `_BlobSeq`, not just strings. (The same integration
      surfaced **F-0026**, a *different* blob path — the §7.4 wrapper re-open reset — now the open
      corelib-c-cpp item below.)
- [x] **F-0026 / [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106)** — **DONE (corelib-c-cpp `2416a2b`, 2026-07-22).** The C object API's §7.4
      `blob_array` wrapper **re-open** kept a stale zeroed element: `sofab_object_init` zeroed a sized
      blob's buffer but not its companion length. The fix resets that length on the replace-init.
      **Verified:** all 4 isolates → all-13-agree; the `elem == "blob"` skip in `sweep_repeated_id.py`
      was dropped and the repeated-id (§7.4) sweep is green with the blob wrapper (16 vectors); the 2
      reproducers + 2 controls promoted into `corpus/regression/` (`F0026_*`, gate 77 → 81). Issue closed.

## Open — CI / infra

- [x] **DONE 2026-08-18 — the evidence this asked for has been arriving all along.**
      `replay.yml` runs its `differential` job **inside** the image
      (`container: ghcr.io/sofa-buffers/crucible-ci:latest`, `replay.yml:56`), so a green run
      *is* the confirmation that the image is seeded and usable — a missing or broken image
      fails the job before the first step. Today's runs (#163, #164) were green there. The
      item was written before the container block existed and was never re-read afterwards.
      This unblocks the devcontainer item below, which named it as its blocker. Original note
      below.
      ~~`image.yml`: confirm the GHCR toolchain image is seeded and the live runs are green.~~
      *(update 2026-07-23: confirmed `replay.yml`/`nightly.yml` **do** consume
      `ghcr.io/sofa-buffers/crucible-ci:latest`; the remaining task is confirming the image is
      seeded and a live run is green.)*
- [ ] **A port with a high `MIN_OUTPUT_BUFFER` gets a one-size flush sweep.** `flush_sizes()`
      (`oracle/encode_invariance.py:79`) returns the declaration plus every standard size *above*
      it — for `go`, which declares 20 (the only port not on 1), that set is exactly `{20}`. So the
      Go encoder is walked across a buffer boundary at a single window size, while every other port
      gets six. Legal per §5.1 and not a defect, but the thinnest coverage on this axis belongs to
      the port whose floor is highest, which is backwards. **Work:** add a couple of sizes above the
      declaration (floor+1, 2x floor, and one odd size) so the boundary lands at different offsets
      within the message; costs one run each and needs no spec change.

- [x] **DONE 2026-08-16 — both gates derive their list from the roster + `meta`.**
      `scripts/roster.sh caps {encode|chunked}` reports the entries whose backend declares the
      capability; `run-encode.sh` and `run-chunked.sh` call it instead of carrying a list. The
      derived lists matched the hand-written ones exactly (encode 15, chunked 14 — `go` absent by
      its declared `chunked_decode=none`), so this changed the mechanism without changing who
      runs. `SOFAB_*_DRIVERS` still overrides for isolating one driver. Original note below.
      ~~The two streaming gates keep their own driver list, by hand.~~ `run-chunked.sh` and
      `run-encode.sh` each hard-code a 14-name `SUPPORTED` default beside `drivers/roster`'s fifteen
      rows — the copied-list shape CLAUDE.md warns about, and it already misleads: the chunked gate's
      comment claimed nobody was held out while `go` was (legitimately — corelib-go has no resumable
      decoder, `chunked_decode=none` in `drivers/go/meta`). Corrected in the comment 2026-08-16, but
      the list is still a copy. **Work:** derive both from the per-driver `meta` (`chunked_decode`,
      `encode_surfaces`) plus the roster, so adding a driver cannot silently skip a gate. Note the
      mapping is not 1:1 — the four `cpp` roster rows share one `drivers/cpp/meta`.

- [x] **DONE 2026-08-16 — `go` is in the encode gate; the `meta` was right all along.**
      The backend had all three surfaces (`Encode`, `EncodeTo(w)`, `Serialize` into a
      `NewEncoderSink`) and corelib-go even exports `MinOutputBuffer` (= 20, which
      `drivers/go/meta` restates) — only `drivers/go/driver.go` never read the variable and
      called `m.Encode()` unconditionally. Plumbed per CONTRACT.md: surface dispatch, the
      §5.1 floor refused with exit 3, stderr announcement. **No corelib change was needed.**
      First run green: 108 inputs x 5 configs, 0 mismatches. Original note below.
      ~~`go` is the last driver outside the encode gate, and its `meta` overstates it.~~
      `drivers/go/meta` declares `encode_surfaces=new,to,stream`, but `drivers/go/driver.go` never
      reads `SOFAB_ENCODE`, so the driver is (correctly) absent from `run-encode.sh` — every other
      roster entry is in. Unlike the chunked axis this is **not** a corelib capability gap: the Go
      backend has all three surfaces. Either plumb it or make the `meta` tell the truth.

- [ ] **Build-reuse in `replay.yml`**: each gate rebuilds the whole roster, so CI
      pays the build 7×. Cache/reuse the built drivers across gates.
- [ ] **Devcontainer image**: verify it builds and every driver builds *inside* it (so far
      spot-verified in the bare workspace + hand-installed clang). *(update 2026-07-23:
      `.devcontainer/{Dockerfile,devcontainer.json,start.sh}` exist and `image.yml` builds them;
      still no CI evidence every driver builds inside the image — blocked on the `image.yml` item above.)*
      **No longer blocked (2026-08-18):** the `image.yml` item above is closed, and in fact
      the evidence is already partly in hand — `replay.yml`'s `differential` job runs inside
      `ghcr.io/sofa-buffers/crucible-ci:latest` and builds **every driver** there on each run,
      so "every driver builds inside the image" is demonstrated for the CI image. What is
      still unverified is the **devcontainer** image specifically (`.devcontainer/Dockerfile`),
      which is a different artifact from the CI one; the remaining work is checking whether
      the two have drifted, and if they are meant to be the same image, saying so in one place
      rather than maintaining two.
- [ ] **OSS-Fuzz** onboarding for continuous fuzzing (eventual).

## Done — key harness milestones (finding history is in `../results/FINDINGS.md`)

- [x] **Structure-aware mutator** (`engine/mutator/`) wired via `LLVMFuzzerCustomMutator` +
      `scripts/fuzz.sh`; 336k-mutation ASan soak clean. **Comparator crash- + hang-isolation**
      (per-driver `--timeout`; `[TIMEOUT]` reported as a DoS finding).
- [x] **Cross-encode oracle** (`engine/structured/gen.py` + `scripts/cross-encode.sh`) — found
      F-0009 + F-0010. **Union suite** (`schema/probe-union.sofab.yaml` + `scripts/run-union.sh`).
- [x] **Regression gate** (`corpus/regression/`, 29 × 12, in `replay.yml`) — every resolved
      finding's reproducer, admitted only when green *for the reason the finding is about*;
      contaminated originals get clean isolates via `engine/structured/isolates.py`.
- [x] **All four spec proposals adopted** — §5.2 precedence (documentation#17), §3/§5.1
      fixed-count fill-to-N (#18), §7.1 declared-bounds-bind-every-target + §6.2.1 receiver
      limits + `LimitExceeded` (#20), §7.3/§7.4 mis-typed-header + repeated-id (#23). Provenance
      migrated into the finding `NOTES.md`; the `spec-proposals.md` draft file is retired.
- [x] **`bootstrap.sh` reworked** — always installs the latest sofabgen **release** binary
      (sha256-verified) and fetches corelibs to `origin/main`; no skip-if-present (a stale
      toolchain once mis-reported the versions compared). Escapes: `SOFABGEN_VERSION=` / `NO_FETCH=`.
- [x] **zig driver unbroken** (G-0010 / sofabgen 0.16.2). **java driver stale-jar fixed**
      (2026-07-17): `drivers/java/build.sh` rebuilds the corelib jar when the source is newer,
      not just when it's missing — a cached jar had once masked an F-0016 corelib fix.
- [x] **F-0001** target met (all 12 emit `I`); the **INVALID-vs-INCOMPLETE precedence family**
      resolved via the adopted clause + per-corelib fixes; **F-0013 / F-0014 / F-0015 / F-0016**
      all filed with precise codegen-vs-corelib attribution and verified fixed.
