# improvements.md — test-coverage work packages

Result of the 2026-07-22 coverage audit: the suites that exist are strong (the six sweep
axes enumerate real position spaces; truncation cuts at every byte offset), but coverage
is **not** complete. Three gap classes: (1) spec features present in **no schema**,
(2) the **union schema living entirely outside the generated pipeline**, and (3) value /
wire corners **no generator ever produces**.

This document is the implementation plan for closing those gaps. It is written for an
implementing agent with **no prior session context**. Each work package (WP) is
self-contained and independently landable — one WP per session/PR is the intended
granularity. All `file:line` references are as of 2026-07-22; **verify before relying on
them**, the code moves.

---

## Ground rules (read first, apply to every WP)

1. **Orient first.** Read `docs/STATUS.md`, `docs/ARCHITECTURE.md`, and `CLAUDE.md`
   before touching anything. `docs/PLAN.md` is the intended design — never edit it to
   match new code; as-built changes go to `ARCHITECTURE.md` **in the same change**
   (including a dated "Deviations from PLAN" entry when applicable).
2. **Bootstrap before any run.** `./scripts/bootstrap.sh` (latest green sofabgen CI
   build, corelibs → `origin/main`). Never test against a stale toolchain.
3. **Never call `oracle/comparator.py` directly against `drivers/*/build/` binaries.**
   Always go through `scripts/run.sh` (or the suite wrapper) — a prior suite run may
   have left binaries built against a *different* schema (`probe-dyn`, `probe-union`),
   and run.sh is what rebuilds them for the right one.
4. **New axes start report-only, never blocking.** Project precedent (wiretype §7.3,
   malform×truncation §5.2): a new axis is wired into `scripts/sweep.sh` as
   **report-only** and is promoted to blocking only once it is green — or once every
   divergence it surfaces is catalogued as a finding.
5. **A divergence a new test surfaces is a finding, not a test bug.** Follow the full
   workflow: minimize → attribute (**generated code vs corelib** — the CLAUDE.md triage
   table; the deciding question is *"does the fix need knowledge only the schema
   has?"*) → catalog as `F-00NN` in `results/FINDINGS.md` → file in the **owning** repo
   with `file:line` evidence and a minimal isolate. Never silently carve it out.
6. **Expected behavior must cite spec.** Every conformance assertion cites a
   `MESSAGE_SPEC.md` / `CORELIB_PLAN.md` clause (specs live in
   `vendor/documentation/`). If the spec is **silent** on a case, that is a spec hole:
   record it (pattern: `oracle/policy.yaml` notes + `docs/spec-proposals.md`), file it
   upstream against `documentation`, and keep the axis **agreement-only** (drivers must
   merely agree; no accept/reject conformance) until a clause is adopted. This is the
   F-0015 arc — hole → clause → adoption → verify — and it is deliberate.
7. **Regression-gate admission** (`corpus/regression/README.md`): a vector enters the
   gate only when it is green *for the reason it exists*, and controls guarding the
   counter-direction (must-still-accept) are promoted alongside.
8. **The roster is 13 drivers** (c, go, rust-std, rust-nostd, cpp, cpp-c-cpp,
   py-cython, py-pure, java, typescript, csharp, zig, dart). Several older comments
   still say "12" — do not propagate that.
9. **Keep CI green.** `replay.yml` runs seven blocking gates. A WP that adds a suite
   also wires it into `replay.yml` only at promotion time (rule 4), not while
   report-only.

---

## WP-01 — Union under the structural sweeps  *(P1, the single biggest gap)*  ✅ LANDED 2026-07-22

**Status (2026-07-22).** ✅ **Landed, report-only** (as the DoD's second branch prescribes — a
divergence was found and catalogued). `schema.py` learned the `union` kind (probe descriptor
byte-unchanged); `sweep_positions.UNION_POSITIONS` is **schema-derived** from that descriptor (took the
doc's *first-listed* step-2 path — parameterize by schema — not the parallel-`UNION_POSITIONS` escape
hatch, to avoid seeding the third position model WP-11 exists to remove); five axes gained `emit_union`;
`sweep_run.py --union` + a report-only `scripts/sweep.sh` pass (rebuild→probe-union→run→rebuild-back).
130 union vectors. **repeated-id / over-bound / reserved-subtype / truncation → green across 13; the
wiretype §7.3 pass surfaced F-0027** — `rust-nostd` rejects a §7.3-skippable array/fp64 field that
`probe-union` never declares (sofabgen provisions the no-std corelib's cargo features from the schema's
*used* wire types; skip-ability is schema-independent). Catalogued: `results/FINDINGS.md` F-0027 +
`results/SOFABGEN.md` G-0017 (generator-primary, corelib-rs-no-std implicated), reproducers under
`findings/F-0027-*`. Not promoted to blocking / not in the regression gate until the generator fix lands.
Follow-ups deferred as noted in the steps below: WP-02 (union cross-encode + materialized oracle) and the
over-bound-magnitude / merge-value semantic assertions remain open.

**Problem.** `engine/structured/schema.py` raises `ValueError: unhandled schema type
'union'` (schema.py:56), so the union feature is invisible to every generator: none of
the six sweep axes, no cross-encode, no materialized oracle. Union coverage is exactly
11 hand-written static seeds (`corpus/union/`), run as a plain differential with **zero
conformance assertions** (`scripts/run-union.sh`). The project's own history
(F-0020→F-0025, five consecutive "isolate-green ≠ axis-green" findings) says this is
where residual bugs live. Spec: MESSAGE_SPEC §4.2 (:223-237), §7.3 (:517-538), §7.4
(:540-569 — union **merge** semantics; a §7.3-skipped occurrence does not count,
:557-558).

**Steps.**
1. Teach `engine/structured/schema.py` the `union` kind: a descriptor node carrying
   `default_id` and the typed option list (`probe-union.sofab.yaml:10-18` — as_u16 u16
   id0, as_i32 i32 id1, as_text string maxlen16 id2, as_blob blob maxlen8 id3). Keep
   the single-message assumption (schema.py:68).
2. Build a union position model. Do **not** bolt union entries onto the probe-only
   `sweep_positions.POSITIONS`; instead parameterize the position model by schema (or
   add a parallel `UNION_POSITIONS` for `probe-union`): the union sequence itself
   (id 1), each of its four member positions, plus the `tag`/`trailer` scalars for
   controls.
3. Extend each sweep axis with a probe-union pass generating vectors over those
   positions:
   - **wiretype (§7.3):** each member fed every mismatching construct → expect skip
     (union stays at `default_id` per §4.2 when no valid member lands) — mirror the
     existing 11-construct table (`wiretype_sweep.py:52-64`).
   - **repeated-id (§7.4):** member repeated (last-wins), two *different* members
     (merge — spec :540-569; `corpus/union/10_two_members` pins the family behavior:
     re-encode both in id order), union sequence re-opened, and the currently untested
     **"§7.3-skipped occurrence doesn't count"** cross vector (mistyped member first,
     valid same-id member second → the valid one must win).
   - **over-bound (§7.1):** `as_text` maxlen16 and `as_blob` maxlen8 at bound / bound+1.
   - **reserved-subtype (§4.6):** reserved fixlen subtypes at member positions.
   - **truncation (§7):** one rich union message (tag + member + trailer), truncated at
     every byte offset, expect not_reject — same shape as `sweep_truncation.py:59`.
4. Wire into `scripts/sweep.sh` as a second, clearly-labeled pass: rebuild drivers with
   `SCHEMA=probe-union` (run-union.sh:10-11 shows the mechanism), run the union axes,
   then **rebuild back to `probe`** (or make the probe rebuild the last step) so the
   binaries are never left in a mixed state (see ground rule 3).
5. Report-only first; promote per ground rule 4. Promote green isolates of anything
   found into `corpus/regression/` per its README.

**Definition of Done.**
- `python3 -c "from engine.structured.schema import descriptor"` (or equivalent entry
  point) succeeds for `probe-union.sofab.yaml`.
- `./scripts/sweep.sh` runs the union pass over all 13 drivers; vector counts logged.
- Either green → axes promoted to blocking + `replay.yml` updated, or every divergence
  is a catalogued finding with an upstream issue.
- `ARCHITECTURE.md` updated (new pass, position model, schema-switch handling).

**Pitfalls.** Union member expectations differ from struct fields (empty union →
`default_id` value, §4.2 :230-236) — don't copy struct conformance expectations
blindly. `corpus/union/11_unknown_member` pins unknown-id → skip → empty union; keep
new vectors consistent with those two pinned behaviors. sofabgen must regenerate all 13
drivers for probe-union — that already works (run-union.sh is green), so a build
failure here means your harness change, not codegen.

---

## WP-02 — Union value corpus, cross-encode, materialized oracle  *(P2, depends on WP-01 step 1)*  ◑ PART A LANDED 2026-07-23

**Status (2026-07-23).** ◑ **Part A (cross-encode) landed; Part B (materialized) scoped as a follow-up.**
- **Part A — union cross-encode (DONE, green):** `gen.py` gained `encode_union` + `union_vectors` (18
  value-rich vectors: each member at boundary values — u16 0/1/max, i32 min/-1/1/max, as_text
  empty/ascii/unicode/maxlen16, as_blob 1-byte/maxlen8/binary — the default_id case, and tag+member+trailer
  combos), written to `corpus/structured-union/` via `gen.py --union`. `scripts/cross-encode.sh` now runs a
  second **union pass** (rebuild → probe-union → differential → restore probe). **18 × 13 → 0 divergences**
  — the union value space round-trips identically across all 13. Blocking (green), gated by `replay.yml`
  (which runs `cross-encode.sh`).
- **Part B — union materialized (FOLLOW-UP, scoped):** the C anchor materializes a union out-of-the-box
  (sofabgen object descriptor) → the target form `{opt_id:value}` for every member (active = value, inactive
  = default; e.g. `{0:u5;1:{0:u0;1:s42;2:t0:;3:b0:};2:u12}`). But the other 12 walkers do **not** handle the
  `union` descriptor node: the **6 runtime walkers** (go, py-cython, py-pure, java, ts, cs) emit no output,
  and the **6 generated walkers** (rust-std, rust-nostd, cpp, cpp-c-cpp, zig, dart) emit an empty payload.
  Part B = extend `materialize.py` (a union reference) + the 6 runtime walkers + the 4 `materialize_gen.py`
  generators to walk a union node, add a materialized union pass, and update `oracle/materialized.md` — a
  ~12-walker sub-project across 10 languages, deferred to its own change. (The union *value space* is
  already cross-checked by Part A; Part B adds the element-access dimension.)


**Problem.** `engine/structured/gen.py` and `engine/structured/materialize.py` are
probe-only; union values are never cross-encoded and never materialized. Also, the only
union variants tested anywhere are 2 scalars + string + blob, while §4.2 (:230-231)
allows struct/array/nested-union options (that larger hole is WP-05's schema work; here
we cover the *existing* union schema).

**Steps.**
1. Add a union vector family to `gen.py` (behind a schema switch, not mixed into the
   probe corpus): each member with boundary values (u16 0/1/max; i32 min/-1/1/max;
   as_text empty/ascii/unicode/exactly-maxlen16; as_blob 1-byte/exactly-maxlen8),
   default_id case, member + both siblings set.
2. Extend `materialize.py` + the descriptor consumer to walk a union (member id +
   member value; absent union → default_id, per §4.2). Mind the hardcoded
   `ARR_COUNT = 5` (materialize.py:32) and `_MSG_KEY` map (materialize.py:40-51) —
   extend or (better) fold into WP-12's de-hardcoding.
3. New corpus dir (e.g. `corpus/structured-union/`) + a `cross-encode.sh`/
   `materialize.sh` union pass (same `SCHEMA=probe-union` rebuild discipline as WP-01
   step 4).
4. Driver materialize-walkers are descriptor-driven (C via object descriptor;
   go/ts/java/cs/py at runtime; rust/cpp/zig/dart generate walker source at build —
   `drivers/<lang>/materialize_gen.py`). Adding the union node type to the descriptor
   may require extending those walkers/generators — check each; the CI conformance
   check vs the reference will catch a walker that silently ignores the node.

**Definition of Done.** Union cross-encode and materialized differentials green
(13 drivers, 0 divergences) or findings filed; wired report-only → promoted;
`ARCHITECTURE.md` + `oracle/materialized.md` updated.

---

## WP-03 — Non-minimal varint axis  *(P1, cheap, classic differential candidate)*

**Problem.** `gen.varint` (gen.py:36-45) always emits minimal encodings, and no suite
contains a non-minimal varint that still fits 64 bits (e.g. a zero-padded continuation
form of a small value). F-0016 covered only the >64-bit overflow case
(`corpus/regression/F0016_*`). Whether all 13 decoders agree on accepting /
normalizing / rejecting non-canonical varints is untested — exactly the class where
implementations silently differ.

**Steps.**
1. Read the varint wire definition (`gen.py:36-45` + CORELIB_PLAN varint section) and
   determine what the spec actually says about non-minimal encodings. Expected outcome:
   the spec is **silent** → ground rule 6 applies (agreement-only axis + upstream spec
   hole filed against `documentation`, drafted in `docs/spec-proposals.md`).
2. Hand-build byte vectors (do **not** change `gen.varint` — it is the canonical
   reference encoder). Place a non-minimal varint at each distinct varint role: field
   id, fixlen length word, array count word, array element value, and a varint inside a
   skipped (unknown-id) field. Include the boundary form (maximal padding that still
   encodes ≤64 bits) next to the F-0016 overflow vectors as contrast controls.
3. New axis module (e.g. `engine/structured/sweep_varint.py`) registered in
   `sweep_run.py` `AXES` and `scripts/sweep.sh` (report-only).
4. If drivers agree on *accept*: also check the **re-encode** side in the round-trip —
   an accepted non-minimal input must re-encode minimally on all 13 (single canonical
   encoding, MESSAGE_SPEC §2:73-76), which the existing round-trip comparison gives for
   free.

**Definition of Done.** Axis runs 13×N; either green → blocking, or finding(s) filed
with attribution; spec-hole issue filed if the spec is silent. `ARCHITECTURE.md`
updated.

---

## WP-04 — Framing & ceilings axis: stray SEQUENCE_END, ID_MAX, FIXLEN_MAX, ARRAY_MAX  *(P1)*

**Problem.** Two related holes with zero dedicated coverage:
- **Stray / unbalanced `SEQUENCE_END`** → INVALID (`oracle/canonical.md:33`,
  CORELIB_PLAN:697). `sweep_truncation.py` only produces *open* sequences (→ `I`),
  never a surplus end marker. The mutator DESIGN plans this ("end marker with nothing
  open") but the grammar mutator is not built.
- **Format-wide ceilings** (CORELIB_PLAN:640-646): field id > ID_MAX (2³¹−1), fixlen
  length > FIXLEN_MAX, count > ARRAY_MAX — only reachable by fuzzer luck today.

**Steps.**
1. Vectors, hand-built with `gen.py` primitives:
   - end marker at top level with nothing open; balanced struct close followed by one
     extra end; extra end inside a wrapper array; end as the first byte after a valid
     scalar field. Expect **R** (INVALID) per canonical.md:33.
   - field id at ID_MAX (control, must not reject *for the id*), ID_MAX+1 (expect R);
     fixlen length word just over FIXLEN_MAX (expect R) — **keep declared-length-huge
     vectors small in actual bytes** so the harness never allocates real memory;
     count word over ARRAY_MAX likewise.
2. New axis module (e.g. `engine/structured/sweep_framing.py`), registered in
   `sweep_run.py` + `sweep.sh`, report-only first.
3. Ceiling-over vectors interact with §5.2 precedence (a huge declared length also
   makes the message "truncated"): expected verdict is **R** — INVALID dominates
   (documentation#17, the adopted §5.2 clause); cite it in the vector comments. But
   keep any vector that is *only* over-count-and-truncated out (that corner is the
   open documentation#15 hole — see `corpus/regression/README.md` exclusions).

**Definition of Done.** Axis green → blocking (+ regression-gate promotion of
representative vectors + controls), or findings filed. Runtime sane (no vector may make
a driver allocate per its declared length — watch the comparator's per-driver timeout
and memory; F-0013 is the precedent for declared-size amplification).

---

## WP-05 — Composite-element array schema: array-of-struct (map pattern)  *(P2)*  ⏸ HELD 2026-07-23 (blocked on corelib-c-cpp#109)

**Status (2026-07-23).** ⏸ **Started, then held.** `engine/structured/schema.py` learned the
composite-element wrapper (the `struct_wrapper` descriptor kind), and sofabgen generates array-of-struct
for all 13 languages. Adding `struct_array` (id 202) to `probe` immediately surfaced **F-0030 /
[corelib-c-cpp#109](https://github.com/sofa-buffers/corelib-c-cpp/issues/109)** — the C object encoder
does not apply §5.1 trailing-default elision to *sequence-form* wrapper elements, re-encoding an
all-default array-of-struct as N empty struct frames instead of the canonical empty wrapper (breaking the
base round-trip on *every* message). Per the decision to fold the feature in cleanly rather than run a red
gate or a separate schema, `struct_array` is **held out of `probe`** (id 202 reserved via a NOTE) until
the fix lands; then the field is added and wired through the axes below. The `schema.py` support is landed
and dormant. `results/FINDINGS.md` F-0030; tracked in `docs/TODO.md`. Remaining steps unchanged below.



**Problem.** MESSAGE_SPEC §5.2 (:323-346) defines array-of-struct, array-of-union,
array-of-array, and the map pattern (array of struct{k,v}); §5.1 (:309-321) defines
trailing-elision of **sequence-form** elements in fixed-count wrappers. No Crucible
schema contains any composite-element array — `sweep_positions.py` models only leaf
(string/blob) wrappers. This is the F-0013/F-0026 class one level deeper, and history
says integrating a missing schema feature surfaces findings immediately (the
`blob_array` integration found F-0026 the same day, `docs/TODO.md` 2026-07-21 entry).

**Steps.** Mirror the documented blob_array integration pattern (TODO.md:8-16):
1. Add to `schema/probe.sofab.yaml` a `struct_array` (next free id, e.g. 202): array of
   struct{k: u32, v: string maxlen16}, `count: 5` — one field, covers array-of-struct
   **and** the map pattern. (Array-of-union and array-of-array can be follow-ups once
   this lands; note them in TODO.md.)
2. Confirm sofabgen supports it (spec §6 table :332-335 says the format does); if
   codegen fails or generates wrong code, that itself is a `G-00NN` entry in
   `results/SOFABGEN.md` + a `generator` issue — the WP then blocks on upstream.
3. Wire the new positions through **all six** sweep axes + `gen.py` values (elements
   full/partial/sparse/last-index; k/v boundary values) + `schema.py`/`materialize.py`
   (descriptor gains a struct-element wrapper node — walkers per WP-02 step 4).
4. Dedicated §5.1:309-321 vectors: fixed-count wrapper with trailing all-default
   struct elements elided (encode side MUST elide; decode side MUST materialize N).
5. Drivers rebuild schema-agnostically — no driver change expected (that was the
   blob_array experience).

**Definition of Done.** All six axes + cross-encode + materialized green over the
extended probe (or findings filed); regression seeds promoted; `ARCHITECTURE.md` +
schema comment (why the field exists) updated.

**Pitfalls.** Extending `probe` invalidates byte-hardcoded artifacts? No — seeds are
sparse and ids are new, existing corpora stay valid; but the materialized reference and
the committed `oracle/materialized-schema.json` must be regenerated (materialize.sh
`cmp`-checks it). The hardcoded `ARR_COUNT=5`/`_MSG_KEY` (materialize.py:32,40-51) and
`sweep_positions` bounds must learn the new field — coordinate with WP-12.

---

## WP-06 — Float specials & integer value gaps in the cross-encode corpus  *(P2)*  ✅ LANDED 2026-07-23

**Status (2026-07-23).** ✅ **Landed.** `gen.py` gained raw-byte fp support (`f32b`/`f64b`, exact bit
patterns that survive Python float canonicalization) + vectors: min/max subnormal f32+f64, quiet-payload
NaN, negative NaN, fp64 sNaN, explicit +0.0, unsigned mid values; `materialize.py` handles raw-byte fp
(element-access compares raw bits); `gen.py` clears stale corpus files before regenerating. Corpus 75→90.
Cross-encode + materialized **green (90×13 each)** for all the green vectors. **F-0031** surfaced: an fp32
*signaling* NaN is quieted (`0x7F800001`→`0x7FC00001`) by py-cython/typescript/dart (double-backed fp32),
violating §4.6 bit-for-bit; the other 10 (incl. py-pure) preserve it. Corelib →
[corelib-py#49](https://github.com/sofa-buffers/corelib-py/issues/49) /
[corelib-ts#66](https://github.com/sofa-buffers/corelib-ts/issues/66) /
[corelib-dart#15](https://github.com/sofa-buffers/corelib-dart/issues/15); `f32_snan` carved out of the
green gate (`findings/F-0031-*`) until fixed. The other new vectors are in the gate.


**Problem.** `gen.py:161-164` covers ±0.0/±1.0/±inf/one quiet NaN/big/small — but
"small" is min-**normal** (1.2e-38 f32 / 2.2e-308 f64), so **subnormals are untested**;
there is only **one NaN bit pattern** (no signaling NaN, no payload NaN, no negative
NaN). Unsigned scalars get only `1` and type-max (gen.py:157-158) — no explicit 0 or
mid values. The materialized oracle compares floats as **raw bits**, so NaN-payload
divergence would be directly visible — the vectors just don't exist.

**Steps.**
1. Add to `gen.py`: min-subnormal + max-subnormal f32/f64 (by bit pattern), sNaN,
   quiet NaN with nonzero payload, negative NaN, explicit +0.0 vector; unsigned 0 and a
   mid value per width; signed already has 1/max/min/-1 (gen.py:152-155) — leave as is.
2. Bit-exactness ground truth: CORELIB_PLAN:263-267 (fp values bit-exact incl.
   NaN). Known caveat: py/ts NaN-payload fidelity is flagged in
   `oracle/canonical.md:107-109` — read that note first; if a payload-NaN vector splits
   the family, that's either a finding or (if the spec sanctions it) a
   `policy.yaml` allowed-divergence entry with spec citation — decide per ground
   rules 5/6, don't drop the vector.
3. Mind the encoder omission rule: `-0.0 == 0.0` compares equal to the default in
   Python — check how gen.py's omit-if-default handles the existing `-0.0` vector
   (gen.py:97-135) and keep the new +0.0/-0.0 pair consistent; `materialize.py:83-85`
   normalizes -0.0→+0.0 for the same reason.
4. Regenerate `corpus/structured/` (`cross-encode.sh` without `REGEN=0`), run
   cross-encode + materialize.

**Definition of Done.** Both suites green at the larger vector count (update the counts
in STATUS/ARCHITECTURE), or findings/policy entries filed. The regenerated corpus is
committed (CI replays it with `REGEN=0`).

---

## WP-07 — Over-bound magnitude: beyond bound+1  *(P2, small)*

**Problem.** `sweep_overbound.py` tests exactly `bound+1` per position and over-index
exactly `id == count` (sweep_overbound.py:44-86). F-0013 showed large indices are the
memory-amplification class (9 B at index 2,000,000 → 226 MB pre-fix); that shape lives
only as a static reproducer (`engine/structured/isolates.py:88-94` → `findings/`), not
in any sweep.

**Steps.** Extend `sweep_overbound.py` with, per bounded position: a mid-magnitude over
(e.g. 2×bound) and a large-but-harness-safe over (e.g. index/len 100_000 — declared,
not materialized in input bytes). Expect **R** per §7.1 (:483-499). Assert wall-time
stays within the existing per-driver timeout (sweep_run.py:69) — a timeout or OOM here
is a DoS finding, per the F-0008/F-0013 precedent.

**Definition of Done.** Axis still green at the larger count (it is already blocking —
so land behind a local run first: `python3 engine/structured/sweep_run.py <axis>` per
sweep.sh usage), counts updated in docs.

---

## WP-08 — §2/§3 canonicality conformance seeds  *(P3, small)*

**Problem.** Three §2/§3 rules are only incidentally covered:
(a) an all-default nested struct still emits an **empty frame**, never dropped
(§2:77-86); (b) the decoder MUST **accept** a non-canonical trailing-default-run array
encoding even though encoders MUST NOT emit it (§3:185-195); (c) explicit `[]`
overrides a **non-empty** field default (§2:112-121) — untestable today because no
schema field has a non-zero default.

**Steps.** (a)+(b): hand-built vectors into a small seed set (new
`corpus/conformance/` run via `CORPUS=... ./scripts/run.sh`, or fold into the WP-04
axis module); for (b) the round-trip oracle also checks the re-encode is canonical
(trailing run trimmed — the F-0010 rule). (c): needs a schema field with a non-empty
`default:` — add one to the WP-05 schema extension rather than perturbing existing
fields (note the dependency).

**Definition of Done.** Vectors green on 13 drivers with conformance expectations cited
(§2/§3 lines above), promoted into the regression gate or the new axis; (c) explicitly
marked blocked-on-WP-05 if landed separately.

---

## WP-09 — Broaden malform×truncation  *(P3)*

**Problem.** `sweep_malform_truncate.py` is the only sweep that samples instead of
enumerating: 9 hardcoded malformations (sweep_malform_truncate.py:84-100) × **one**
truncation shape (a single tail byte `0x8a`, :48). No blob_array over-id malformation,
no array-fixlen-word malformation, one truncation offset.

**Steps.**
1. Extend malformations: blob_array over-id, array element-word malformation (the
   F-0014 class), non-minimal varint (after WP-03 clarifies its status), reserved
   subtype at the wrapper-element scope.
2. Extend truncation shapes: for each malformation, truncate at each byte from the
   malformation point to end-of-message (bounded, not a single byte).
3. **Respect documentation#15:** the over-count+truncated corner is an *open* spec
   hole — vectors of that exact shape stay out of the blocking set (see
   `corpus/regression/README.md` "deliberately NOT here"); park them report-only with a
   comment citing the issue.

**Definition of Done.** Axis green at the larger count (blocking axis — same local-run
discipline as WP-07), or findings filed; the documentation#15 carve-out is explicit in
code comments, not silent.

---

## WP-10 — UTF-8: more positions, and the STRICT_UTF8=OFF configuration  *(P3, investigation-first)*  ◑ PART A LANDED 2026-07-23

**Status (2026-07-23).** ◑ **Part A (positions) landed; Part B phase-1 audit done; phase-2 deferred.**
- **Part A (DONE, green):** `utf8_seeds.py` now parameterizes each malformed-UTF-8 vector over **position**
  — `nested.str` (id 2) **and** a `string_array` element (id 200, element 0) — via a shared `_probe(...)`
  framer, so the strict-UTF-8 reject is proven at the wrapper element too. Also **fixed stale framing**
  (the old framer predated `blob_array` id 201, so its `gen.encode` self-check would have failed). 28
  F0004 seeds (14 × 2 positions), regression gate green (95×13, 0 divergences); malformed → all 13 `R` at
  both positions, valid controls → all 13 `A`.
- **Part B phase-1 audit (STRICT_UTF8=OFF reachability):**

  | profile class | profiles | OFF reachable? | mechanism | §8 OFF behavior |
  |---|---|---|---|---|
  | byte-container | `c`, `cpp-c-cpp` | ✅ | drop `-DSOFAB_ENABLE_STRICT_UTF8` (build.sh) | **raw bytes** |
  | byte-container | `cpp` (pure) | ✅ | define `SOFAB_STRICT_UTF8=0` (defaults 1) | **raw bytes** |
  | byte-container | `zig` | ✅ | `build_options.strict_utf8 = false` (build.sh) | **raw bytes** |
  | Unicode-string | `rust-std/nostd`, `java`, `cs`, `ts`, `dart`, `go`, `py` | ⚠️ unclear | check is corelib-internal / codegen (sofabgen 0.18.0 call sites; gen#85 config audit) — the native string type may **always** validate, so "OFF" may only mean *reject*, not *raw* | reject or raw, **never silent-lossy** |

  So there are **≥4 comparable OFF-capable byte-container profiles** (c, cpp-c-cpp, cpp, zig) — phase 2 is
  feasible for that class; the Unicode-string class needs a deeper per-backend codegen audit to know
  whether OFF is even expressible.
- **Part B phase-2 (opt-in strict-OFF suite): DEFERRED (reason recorded).** It requires an env-gated
  build variant (like `SOFAB_MATERIALIZE`) recompiling the 4 byte-container drivers strict-OFF, plus a
  Unicode-string codegen audit, plus `policy.yaml` per-profile-class allowances citing §8:601-614 — a
  substantial suite for a **non-default** configuration. The value is bounded (OFF is opt-in and the ON
  path is fully covered by Part A / F-0004), and it needs the gen#85 Unicode-string config audit first.
  Scoped as a follow-up; any *silent-lossy* OFF outcome (mutation / U+FFFD) would be a finding regardless
  of class.

**Problem A (positions).** `utf8_seeds.py` embeds the malformed forms only at
`nested.str` (id 2); a `string_array` element never carries malformed UTF-8. The
vectors themselves come from `vendor/corelib-c-cpp/assets/test_vectors.json`
(utf8_seeds.py:66-72) — coverage is as good as that upstream list.

**Problem B (OFF mode).** Everything runs strict-ON (`-DSOFAB_ENABLE_STRICT_UTF8` for
c/c-cpp, zig `build_options`, codegen call sites elsewhere — see the F-0004 entry in
STATUS.md 2026-07-18). MESSAGE_SPEC §8:601-614 / CORELIB_PLAN:762-773 define OFF-mode
behavior ("raw or reject, **never** silent-lossy") — completely untested, and the
legal outcomes differ by profile class (byte-container vs Unicode-string languages),
so a naive differential would flag legal divergence.

**Steps.**
- **A:** parameterize `utf8_seeds.py` over position (`nested.str` + one
  `string_array` element); rerun; promote green vectors into the gate (F0004-adjacent
  naming).
- **B, phase 1 (audit, no harness change):** for each of the 13 profiles, establish
  from driver `build.sh` + corelib source whether an OFF configuration is *reachable*
  at all and what its documented behavior is (the gen#85 config audit referenced in
  STATUS.md 2026-07-17 is the starting point). Deliverable: a table in this file or
  ARCHITECTURE.md.
- **B, phase 2 (only if phase 1 shows ≥2 comparable OFF-capable profiles):** an
  opt-in suite (env-gated, like `SOFAB_MATERIALIZE`) building those drivers strict-OFF
  and running the malformed-UTF-8 vectors with per-profile-class expectations encoded
  as `policy.yaml` allowances citing §8:601-614. Any *silent-lossy* outcome (mutation,
  U+FFFD substitution) is a finding regardless of profile class.

**Definition of Done.** A green (or findings); B phase-1 table committed; B phase-2
either implemented, or explicitly rejected with the reason recorded here.

---

## WP-11 — Harness hygiene: one position model, schema-derived constants, doc drift  *(P2 — prevents silent desync; coordinate with WP-01/05 to avoid conflicts)*

**Problem.** Pure-drift risks, no new coverage:
1. **Two position models.** `wiretype_sweep.py` carries its own 29-entry list
   (wiretype_sweep.py:70-89) including wrapper-**element** positions
   (`([200],0,"FIX_str")`, `([201],0,"FIX_blob")`) that the shared
   `sweep_positions.POSITIONS` (27 entries, sweep_positions.py:59-81) lacks — so
   wrapper elements are swept for §7.3 but not for reserved-subtype. A schema change
   must be mirrored twice.
2. **Hardcoded bounds.** `materialize.py:32` (`ARR_COUNT = 5`) assumes every count
   is 5; `_MSG_KEY` (materialize.py:40-51) hardcodes the field-path map;
   `sweep_positions.py` hardcodes counts/maxlens (:59-81). A schema `count`/`maxlen`
   change silently desyncs them — ironic, given `schema.py` →
   `oracle/materialized-schema.json` was built precisely to make the reference
   schema-derived.
3. **`STRUCT_CHILDREN`** (sweep_positions.py:120-124) uses only 2 of the 8 numeric
   array children for §7.4 reopen (its own comment admits it).
4. **Doc drift:** multiple comments/docs still say "12 drivers" (13 since dart);
   `sweep_run.py:42-56` roster comments among them.

**Steps.** Move the wrapper-element positions into `sweep_positions.py` and make
`wiretype_sweep.py` consume the shared model (its per-axis construct table stays
local); derive counts/maxlens in `sweep_positions.py` and `materialize.py` from the
`schema.py` descriptor instead of literals; extend `STRUCT_CHILDREN` to all 8 (or
document why sampling is sufficient — decide, don't leave the ambiguity); sweep the
"12 drivers" mentions.

**Definition of Done.** `./scripts/sweep.sh` and `./scripts/materialize.sh` green with
**identical or higher** vector counts than before (log both; a count *drop* means the
refactor lost positions — hard fail); reserved-subtype now also covers wrapper-element
positions (count increases accordingly); no behavior change otherwise.

---

## Suggested order

| order | WP | why |
|---|---|---|
| 1 | WP-01 | biggest untested feature surface; historical hit-rate of axis-completion is high |
| 2 | WP-03, WP-04 | cheap, independent, classic differential-bug classes |
| 3 | WP-11 | do before further schema growth so WP-05 lands on one position model |
| 4 | WP-05 | schema growth; unlocks WP-08(c) |
| 5 | WP-02, WP-06, WP-07 | value-space depth on the now-complete structure |
| 6 | WP-08, WP-09, WP-10 | remaining conformance corners + investigation |

After each landed WP: update `docs/STATUS.md` (dated entry, per its format),
`docs/ARCHITECTURE.md`, and tick the corresponding gap here. When every WP is landed or
explicitly rejected-with-reason, fold the residue into `docs/TODO.md` and delete this
file.
