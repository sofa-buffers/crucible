# F-0054 — the `ID_MAX` ceiling is not applied to a **sequence-end** header's id

**Found 2026-08-03** in the first review of the nightly's accumulated corpus. Cluster of
**4 inputs**, minimized 56 B → 31 B → rebuilt as a **6-byte** isolate.

## The isolate

`76 87 80 80 80 40` (6 B):

- `76` — field id 14 (undeclared at root), wire type **SequenceStart** → skipped, §5.2;
- `87 80 80 80 40` — a header varint whose wire type is **7 (SequenceEnd)** and whose field id
  is **2³¹**, one past `ID_MAX`.

| verdict | drivers |
|---|---|
| `R invalid_msg` (**correct**) | c, cpp, cpp-c-cpp, csharp, dart, java, rust-no-std, rust-std, zig (9) |
| `A` — accepted, re-encodes to the empty message | **go, py-cython, py-pure, typescript** (4) |

## The boundary is exact, and the wire type is the whole story

| control | id | wire type | result |
|---|---|---|---|
| `ctl_seqend_id_at_IDMAX` | `2³¹ − 1` | SequenceEnd | **all 13 agree** |
| `ctl_seqend_id_small` | 3 | SequenceEnd | all 13 agree |
| `ctl_seqend_canonical` | 0 (`0x07`) | SequenceEnd | all 13 agree |
| **`r2_seqend_id_over_IDMAX`** | **2³¹** | SequenceEnd | **9 vs 4** |

So the ceiling itself is right everywhere — `ID_MAX` is accepted, `ID_MAX + 1` splits. What is
missing on the four is the check *on this wire type*.

A field header carrying an id over `ID_MAX` with wire type **0 (unsigned)** is rejected by all
13, inside a skipped subtree or at the top level — verified separately. The gap is specific to
**wire type 7**: a sequence-end header is evidently treated as an early exit before the header's
id is validated, so the id never reaches the ceiling check.

## Spec basis

CORELIB_PLAN §6.2 lists `ID_MAX` = 2,147,483,647 among the **format-wide ceilings** —
*"properties of the wire format itself, identical for every implementation, and exceeding one is
`INVALID` (§5.2)"*. §5.2 lists an oversized id among the conditions that are malformed
**regardless of what follows**.

Nothing in the format carves out the sequence-end marker: it is an ordinary field header whose
wire type happens to be 7. Its id is not *used* for anything — which is presumably why the check
was skipped — but "unused" is not "unvalidated"; §6.2's ceiling is stated over headers, not over
headers whose id the decoder happens to consult.

## Attribution — `corelib-go`, `corelib-py`, `corelib-ts`

Parsing a field header and enforcing a format ceiling is wire mechanics with no schema
involvement, so this is the corelib reader on each of the three (py-cython and py-pure share
`corelib-py`, and both are affected, which is consistent with a single shared reader rather than
an engine-specific quirk).

Three independent corelibs sharing one gap is unsurprising here: "see wire type 7 → close the
current sequence and return" is the natural shape of that branch, and validating an id nobody
reads looks like dead work until a conformance ceiling says otherwise.

## Reachability

The whole construct sits inside a **skipped** subtree, so it needs no valid schema context at
all — an undeclared id opened as a sequence and closed by an oversized end marker. Forward
compatibility requires every decoder to accept unknown ids, so this is reachable by any sender.

## Why no gate caught it

`sweep_framing` sweeps `ID_MAX` — `id_at_ID_MAX_ctl` and `id_over_ID_MAX` — but both place the
id on an **unsigned scalar** header, and its stray/unbalanced-sequence-end vectors all use the
canonical single-byte `0x07`. The product cell (an over-ceiling id *on a sequence-end header*)
is empty. Same shape as the gaps behind F-0044, F-0048 and F-0053: two axes each correct, the
cell where they meet untested. `docs/TODO.md` carries it.
