# F-0054 — the `ID_MAX` ceiling and a **sequence-end** header's id


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
> **✅ RESOLVED 2026-08-03 — specified (`main@acd27a4`, Option B) and fixed in all three repos
> the same day.** The attribution moved twice before landing here, so the slug is deliberately
> neutral; the divergence, the isolate and the controls never changed — only which camp was
> conformant. See [History](#history) for what was filed against whom, since two earlier
> positions were communicated upstream.

## Resolution

| repo | fix | what it did |
|---|---|---|
| corelib-go | [#70](https://github.com/sofa-buffers/corelib-go/pull/70) | deleted the `t != TypeSequenceEnd &&` exception in `cursor.go` — a removal, no new branch. This also made its two decode surfaces agree, so the self-contradiction below is **closed**, not deferred |
| corelib-py | [#60](https://github.com/sofa-buffers/corelib-py/pull/60) | bounded the id in **both** engines |
| corelib-ts | [#86](https://github.com/sofa-buffers/corelib-ts/pull/86) | bounded the id on **all three** decode surfaces |

**Verified by verdict, not by agreement.** The differential run reports `5 inputs: 5 agree, 0
diverge`, which on its own proves nothing here: had the family over-tightened onto Option C, the
three controls would have flipped to `R` *together* and the run would look identical. So the
verdicts were read out per driver — the isolate is `R invalid_msg` on all 13, and id 0, id 3 and
id `ID_MAX` are `A` on all 13. Exactly one test point moved.

corelib-go's own suite additionally pins the **normalization half** this isolate structurally
cannot show: on `0x87 0x00` the visitor sees `seqbegin/14`, `seqend` — the id is provably
discarded, not carried through — and it asserts that on both decode surfaces.

All five inputs are now in the green `corpus/regression/` gate as `F0054_*`, **controls
included**, and the camp signature is removed from `results/known-clusters.txt` so a regression
is reported as NEW rather than matched as known.

**Found 2026-08-03** in the first review of the nightly's accumulated corpus. Cluster of
**4 inputs**, minimized 56 B → 31 B → rebuilt as a **6-byte** isolate.

**Re-measured 2026-08-03** against every corelib's current `main`: verdicts unchanged,
**4 accept / 9 reject**, all three controls unanimous.

## The isolate

`76 87 80 80 80 40` (6 B):

- `76` — field id 14 (undeclared at root), wire type **SequenceStart** → skipped, §5.2;
- `87 80 80 80 40` — a header varint whose wire type is **7 (SequenceEnd)** and whose field id
  is **2³¹**, one past `ID_MAX`.

| verdict | drivers |
|---|---|
| `A` — accepted, re-encodes to the empty message | go, py-cython, py-pure, typescript (4) |
| `R invalid_msg` | c, cpp, cpp-c-cpp, csharp, dart, java, rust-no-std, rust-std, zig (9) |

Under **Option B** the rejecting camp is correct and the four accepters carry the defect.
Under the currently merged Option A it is the other way round.

## The boundary is exact, and the wire type is the whole story

| control | id | wire type | result |
|---|---|---|---|
| `ctl_seqend_canonical` | 0 (`0x07`) | SequenceEnd | all 13 accept |
| `ctl_seqend_id_small` | 3 | SequenceEnd | all 13 accept |
| `ctl_seqend_id_at_IDMAX` | `2³¹ − 1` | SequenceEnd | all 13 accept |
| **`r2_seqend_id_over_IDMAX`** | **2³¹** | SequenceEnd | **4 vs 9** |

All three controls stay accepting under both A and B — only Option C would have moved them, and
C was abandoned. Exactly **one** test point separates A from B, and it is this isolate.

A field header carrying an id over `ID_MAX` with wire type **0 (unsigned)** is rejected by all
13, inside a skipped subtree or at the top level — verified separately, and correct under every
option. The split is specific to **wire type 7**.

## Spec basis — `CORELIB_PLAN.md` at `main@acd27a4`

§4.9 keeps the encoder rule (a sequence end MUST be written as exactly `0x07`) and
adds, for the decoder: the id is **discarded**, but *"discarded is not unvalidated"* — the header
is an ordinary field header and its id is bounded by `ID_MAX` exactly as every other header's is,
so an id above the ceiling is `INVALID`. §6.2 states the ceiling binds **every** field header
without exception, the end marker included.

That bound is on the id's **value**, not its spelling: §4.1 is untouched, so a non-minimal
encoding of an in-range id — `0x87 0x00` for id 0, or an id of 3 — decodes as an ordinary
sequence end and re-encodes as `0x07`. This is what separates B from the abandoned Option C,
which would have made those `INVALID` too.

§5.2 and §6.3 now also name an over-ceiling **id** in the §5.2 and §6.3 `INVALID` enumerations. They listed
only *"a length or count above its maximum"*; the id ceiling lived in §6.2 alone, which is a
large part of why this case stayed arguable — the enumeration a reader checks did not list it.

## Attribution under B — `corelib-go`, `corelib-py`, `corelib-ts`

Parsing a field header and enforcing a format ceiling is wire mechanics with no schema
involvement, so this is the corelib reader on each of the three (py-cython and py-pure share
`corelib-py`). But the three did **not** make the same mistake, and the earlier write-up's claim
of *"three independent corelibs sharing one gap"* was too glib:

| repo | site | what it actually does |
|---|---|---|
| corelib-ts | `src/decode/fast.ts:92-101`, `cursor.ts:160`/`:171` and `:435`/`:440`, `state.ts:136-141` — **three** surfaces | the sequence-end branch precedes `const id = this.upper()`, so the id is **never computed** for an end marker and never reaches `if (id > ID_MAX)`. Same shape in all three |
| corelib-py | `src/sofab/decoder.py:309-317` **and** `_speedups.pyx:1683-1690` — both engines | `field_id` **is** computed, then the `SEQUENCE_END` block returns `Field(0, …)`, and only *after* it comes `if field_id > ID_MAX`. Identical branch order in the pure and Cython engines, which is why both py drivers are affected |
| corelib-go | `cursor.go:272` | `if t != TypeSequenceEnd && (h>>3) > uint64(IDMax)` — a **deliberate, written-out exception**, not an oversight |

corelib-go is the interesting case: it had coded Option A's rule before anyone wrote it down.
That is evidence the exemption arises naturally when writing a decoder — and it is the strongest
thing that can be said for A.

### A separate defect this exposed — `corelib-go` contradicts itself

`cursor.go:272` carries the wire-type exception; `decoder.go:65` has the same check **without**
it. Two decode surfaces of one corelib disagree about this input, and only the one the Crucible
driver exercises is measured. That is the §6.5 defect class ("a guard added to one surface but
not another"). **Closed by corelib-go#70**: removing the exception from `cursor.go` was the
F-0054 fix *and* the reconciliation, so the two surfaces now agree. Under A the fix would have
had to go the other way, into `decoder.go`.

## Untested residual — the normalization half

The isolate proves only the *verdict*. Both A and B also require an accepting decoder to
**re-encode the marker as `0x07`**, and this isolate cannot show that: the end marker closes a
*skipped* unknown subtree, so the whole message re-encodes to the empty byte string and the
discarded id is unobservable. A vector placing an in-range non-zero id (e.g. 3) on an end marker
closing a **declared** sequence is needed. `docs/TODO.md` carries it.

## Reachability

The whole construct sits inside a **skipped** subtree, so it needs no valid schema context at
all — an undeclared id opened as a sequence and closed by an oversized end marker. Forward
compatibility requires every decoder to accept unknown ids, so this is reachable by any sender.

## Why no gate caught it

`sweep_framing` sweeps `ID_MAX` — `id_at_ID_MAX_ctl` and `id_over_ID_MAX` — but both place the
id on an **unsigned scalar** header, and its stray/unbalanced-sequence-end vectors all use the
canonical single-byte `0x07`. The product cell (an id over the ceiling *on a sequence-end
header*) is empty. Same shape as the gaps behind F-0044, F-0048 and F-0053.

The episode added a second, larger gap: Crucible has **no tolerance axis** (§7.2 class 5b). A
decoder that is *uniformly* too strict produces no divergence, so the differential oracle cannot
see it. Sweep vectors carry an absolute expectation (`add(..., "accept")`), so the class is
testable; it is simply not swept. Both are in `docs/TODO.md`.

## History

Three positions on one clause, all on 2026-08-03. The **encoder** rule — a sequence end is
written as exactly `0x07` — was never in dispute; only the decoder's treatment of the id was.

| | decoder | id 0 | id 3 | id `ID_MAX` | id `ID_MAX + 1` |
|---|---|---|---|---|---|
| **C** — proposed, abandoned | only id 0 is legal | accept | `INVALID` | `INVALID` | `INVALID` |
| **A** — documentation#34, merged then reverted | any id accepted, `ID_MAX` does not apply | accept | accept | accept | accept |
| **B** — documentation#35, **merged `acd27a4`** | `ID_MAX` applies, then the id is discarded | accept | accept | accept | `INVALID` |

1. **Filed** against the four accepters on the reading that `ID_MAX` binds every header —
   [corelib-go#67](https://github.com/sofa-buffers/corelib-go/issues/67),
   [corelib-py#58](https://github.com/sofa-buffers/corelib-py/issues/58),
   [corelib-ts#83](https://github.com/sofa-buffers/corelib-ts/issues/83). All three were closed
   `COMPLETED` the same day on **Option C**, with a spec proposal to follow.
2. That proposal, documentation#34, **reversed itself to Option A** before merging: C would have
   constrained the *spelling* (`0x87 0x00`, a non-minimal id 0, would have become `INVALID`),
   the format's first exception to §4.1's accept-and-normalize. So the three closures rest on a
   rule that never became normative.
3. This finding was **rewritten against the nine rejecters** and re-filed:
   [corelib-c-cpp#128](https://github.com/sofa-buffers/corelib-c-cpp/issues/128),
   [corelib-cpp#68](https://github.com/sofa-buffers/corelib-cpp/issues/68),
   [corelib-cs#51](https://github.com/sofa-buffers/corelib-cs/issues/51),
   [corelib-dart#30](https://github.com/sofa-buffers/corelib-dart/issues/30),
   [corelib-java#60](https://github.com/sofa-buffers/corelib-java/issues/60),
   [corelib-rs#45](https://github.com/sofa-buffers/corelib-rs/issues/45),
   [corelib-rs-no-std#66](https://github.com/sofa-buffers/corelib-rs-no-std/issues/66),
   [corelib-zig#33](https://github.com/sofa-buffers/corelib-zig/issues/33). Each drew a draft PR.
4. **Option B was raised** — bound the id's *value* like every other header's, discard it after.
   The §4.1 objection that killed C does not reach B, and B is the only option that **removes**
   branching: the nine already carry one unconditional `if (id > ID_MAX)` before the wire-type
   dispatch, A makes each of them grow an exception there, B leaves them untouched and lets
   corelib-go delete the one it has. Filed as
   [documentation#35](https://github.com/sofa-buffers/documentation/pull/35), which reverts #34.

5. **Cleaned up 2026-08-03.** The eight A-issues and all eight draft PRs are **closed**
   (`not planned`), each with a note that #35 reverts the rule they implement. The three from
   step 1 stay closed but are marked superseded — they carried *two* obsolete instructions, C's
   in the closure and A's in my later comment. F-0054 is now filed fresh on B, against this
   finding's sites: [corelib-go#69](https://github.com/sofa-buffers/corelib-go/issues/69),
   [corelib-py#59](https://github.com/sofa-buffers/corelib-py/issues/59),
   [corelib-ts#85](https://github.com/sofa-buffers/corelib-ts/issues/85). Each states up front
   that #35 was still open at filing time.
6. **#35 merged** as `acd27a4` the same day. The three issues are unblocked and the basis is no
   longer provisional: Option B is the normative rule.
