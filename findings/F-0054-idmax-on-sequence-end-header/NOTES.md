# F-0054 — the `ID_MAX` ceiling and a **sequence-end** header's id


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
> **✅ RESOLVED AGAIN 2026-08-06, after regressing twice in two days.** Specified 2026-08-03
> (`main@acd27a4`, Option B) and fixed in go/py/ts the same day; then the abandoned **Option A**
> was merged into **corelib-zig** on 08-05 and into **corelib-java** on 08-06, each time making
> that one driver the lone accepter. Both are reverted — corelib-zig at `c139250`, corelib-java
> by [#67](https://github.com/sofa-buffers/corelib-java/pull/67) at `9befe46` — and the five
> `F0054_*` regression vectors are unanimous again (15 drivers, 0 divergences), with the
> `sweep.sh` tolerance axis green at all seven positions.
>
> **The two regression sections below stay.** They are not history for its own sake: the cause
> was the same in both cases — Option-A branches from 2026-08-03 that outlived the rule and still
> read as current — and until those branches are gone this can return a third time. Whoever sees
> `F0054_*` diverge again should read them before re-deriving anything.
>
> The attribution moved twice before landing here, so the slug is deliberately
> neutral; the divergence, the isolate and the controls never changed — only which camp was
> conformant. See [History](#history) for what was filed against whom, since two earlier
> positions were communicated upstream.

## Resolution

**Impls:** **corelib-go, corelib-py, corelib-ts** (4 drivers, 3 repos) · **Axis:** verdict

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

## Regression 2026-08-06 — corelib-java, the same stale branch one repo over

zig's revert landed 2026-08-05 22:50 (its ceiling check sits before the wire-type dispatch again,
`istream.zig:290`). The next morning **corelib-java** merged [#66](https://github.com/sofa-buffers/corelib-java/pull/66)
(`1eb6f12`, 06:05) and took its place as the lone accepter — same two regression vectors, same
seven tolerance positions, same controls untouched.

| gate | camps |
|---|---|
| `CORPUS=corpus/regression ./scripts/run.sh` | `R invalid_msg` ×14 · **`A` java** |
| `./scripts/sweep.sh` — tolerance axis | all 7 `*_end_id_over_ID_MAX` vectors, `R` ×14 · **`A` java** |

**The difference from zig's, and the reason this keeps happening.** zig's change rode inside a PR
described as "README only, no code". java's does the opposite — it argues from the spec and quotes
§4.9 and §6.2 at length. But the quoted wording is `f52e51e` (documentation#34, Option A), removed
the same day by `872d479` and documentation#35 (`acd27a4`). The commit is authored 2026-08-03
15:37, *before* Option B merged, and #66 states the provenance itself: *"restores a commit that
never got a PR and whose branch was pruned from origin. It is not obsolete — it is what the current
spec requires, and `main` today violates it."* Every clause of that is true against the revision it
was written for, and false against the tip. `1eb6f12` also cites "Closes #60", which was closed
`not planned` on 2026-08-03 for exactly this reason.

So the mechanism is **not** carelessness in either repo: the Option-A branches from that day are
still reachable and still read as internally consistent. Filed as
[corelib-java#68](https://github.com/sofa-buffers/corelib-java/issues/68), which asks for the
branch deletion alongside the revert and the removal of `SequenceEndIdToleranceTest` (292 lines
pinning Option A). A sweep of all eleven corelibs found no other such branch and no open PR
touching it.

## Regression 2026-08-05 — corelib-zig implemented the abandoned Option A

Caught by the regression gate on a full-box re-run against freshly pulled corelib tips. This is
exactly what `corpus/regression/` exists for: **a divergence there means a resolved bug came
back** (`docs/CI.md`).

`zig` is now the lone accepter — the mirror image of the camp this finding was resolved on:

| gate | vectors that diverge | camps |
|---|---|---|
| `CORPUS=corpus/regression ./scripts/run.sh` (188 inputs) | `F0054_r1_seqend_id_huge`, `F0054_r2_seqend_id_over_IDMAX` | `R invalid_msg` ×14 · **`A` zig** |
| `./scripts/sweep.sh` — tolerance axis (§7.2 class 5b), 49 vectors | all 7 `*_end_id_over_ID_MAX` vectors, at every schema position (`root_id10/100/200/201/202`, `100_id10`, `202_id0`) | `R invalid_msg` ×14 · **`A` zig** |

The three controls (`F0054_ctl_seqend_canonical`, `_id_small`, `_id_at_IDMAX`) still agree
unanimously on `A`. That is the Option-A signature precisely: the ceiling is not applied to wire
type 7 at all, so only the over-ceiling id moves and nothing below it does. Both blocking gates
are red on this one cause and nothing else.

### The cause — a withdrawn instruction, merged anyway

`vendor/corelib-zig/src/istream.zig:276-289` (at `26bab0c`) now short-circuits wire type 7
**before** the ceiling check:

```zig
// §4.9/§6.2: the `ID_MAX` ceiling binds only *value-bearing*
// headers. A sequence-end (wire 7) discards its id, so it is
// exempt — accept any id, close the sequence, [...] (F-0054).
if (wire == types.T_SEQUENCE_END) { ... continue; }

if (id_raw > types.ID_MAX) return Error.InvalidMessage;
```

That is Option A, verbatim — the position [History](#history) step 2 records as *reverted before
merging*. The commit message says "Fixes #33. Crucible finding F-0054", but
[corelib-zig#33](https://github.com/sofa-buffers/corelib-zig/issues/33) was **closed
`not planned` on 2026-08-03** together with its draft PR, precisely because #35 reverts the rule
it asks for (History step 5). The instruction it implements was withdrawn two days before it
landed.

**How it slipped in:** it rode along inside
[corelib-zig#36](https://github.com/sofa-buffers/corelib-zig/pull/36), a README PR whose body
states *"## Changes (README only, no code)"* — while its first commit changes `src/istream.zig`
by 61 lines, including a test that **pins** the wrong behaviour
(`test "over-ID_MAX id on a sequence-end is accepted and discarded (F-0054)"`, `istream.zig:662`).
So the code change was never reviewed against the PR's own description.

### The spec is unambiguous at the tip

`vendor/documentation/CORELIB_PLAN.md:388-395` at `bec1fa8`, re-read for this run rather than
quoted from the finding:

> **Discarded is not unvalidated.** The header is an ordinary field header, and its id is bounded
> by `ID_MAX` exactly as every other header's is (§6.2): an id above the ceiling is `INVALID`
> (§5.2), on a sequence end as anywhere else. […] There is deliberately **no exception** for wire
> type 7.

The zig comment's own citation (§4.9/§6.2 "exempt the end marker") is what that sentence exists to
deny.

### Attribution — corelib-zig

The decode path, the ceiling and the wire-type dispatch are all corelib code
(`src/istream.zig`); no schema fact participates, and the other 14 drivers — including
`rust-nostd`, the closest architectural sibling — get it right with the same generated code. File
against **corelib-zig**: revert the wire-7 short-circuit (a deletion, restoring the single
unconditional `if (id_raw > types.ID_MAX)`) and delete the test that pins Option A.

**Filed 2026-08-05** as [corelib-zig#38](https://github.com/sofa-buffers/corelib-zig/issues/38),
carrying the camp tables, both §4.9 and §6.2 quoted at the tip (the two sections the offending
comment cites, both of which state the opposite), the withdrawal history of #33, and the three
boundary test points that separate Option B from A and C.

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
