# F-0054 — an over-`ID_MAX` id on a **sequence-end** header is wrongly rejected

> **Inverted 2026-08-03.** This finding was first written the other way round — the four
> *accepters* were reported as buggy, and three issues were filed against them. The spec
> then settled the question in the opposite direction: **accepting is correct**. The
> divergence, the isolate and the controls are unchanged; only the attribution moved.
> The original issues are stale — see [History](#history).

**Filed 2026-08-03** against the nine rejecters:
[corelib-c-cpp#128](https://github.com/sofa-buffers/corelib-c-cpp/issues/128),
[corelib-cpp#68](https://github.com/sofa-buffers/corelib-cpp/issues/68),
[corelib-cs#51](https://github.com/sofa-buffers/corelib-cs/issues/51),
[corelib-dart#30](https://github.com/sofa-buffers/corelib-dart/issues/30),
[corelib-java#60](https://github.com/sofa-buffers/corelib-java/issues/60),
[corelib-rs#45](https://github.com/sofa-buffers/corelib-rs/issues/45),
[corelib-rs-no-std#66](https://github.com/sofa-buffers/corelib-rs-no-std/issues/66),
[corelib-zig#33](https://github.com/sofa-buffers/corelib-zig/issues/33)

**Found 2026-08-03** in the first review of the nightly's accumulated corpus. Cluster of
**4 inputs**, minimized 56 B → 31 B → rebuilt as a **6-byte** isolate.

**Re-measured 2026-08-03** against every corelib's current `main` (go, py and ts had moved —
F-0053 fixes and perf work, no seq-end change): verdicts unchanged, **4 accept / 9 reject**, all
three controls unanimous.

## The isolate

`76 87 80 80 80 40` (6 B):

- `76` — field id 14 (undeclared at root), wire type **SequenceStart** → skipped, §5.2;
- `87 80 80 80 40` — a header varint whose wire type is **7 (SequenceEnd)** and whose field id
  is **2³¹**, one past `ID_MAX`.

| verdict | drivers |
|---|---|
| `A` — accepted, re-encodes to the empty message (**correct**) | **go, py-cython, py-pure, typescript** (4) |
| `R invalid_msg` (**the defect**) | c, cpp, cpp-c-cpp, csharp, dart, java, rust-no-std, rust-std, zig (9) |

## The boundary is exact, and the wire type is the whole story

| control | id | wire type | result |
|---|---|---|---|
| `ctl_seqend_id_at_IDMAX` | `2³¹ − 1` | SequenceEnd | **all 13 agree** (accept) |
| `ctl_seqend_id_small` | 3 | SequenceEnd | all 13 agree (accept) |
| `ctl_seqend_canonical` | 0 (`0x07`) | SequenceEnd | all 13 agree (accept) |
| **`r2_seqend_id_over_IDMAX`** | **2³¹** | SequenceEnd | **4 vs 9** |

All three controls are **conformant as they stand** and need no change: §4.9 requires every
id on a sequence end to be accepted, so a small id, `ID_MAX` and `ID_MAX + 1` must all decode
alike. The nine hold the first three only by staying under a bound that does not belong here.

A field header carrying an id over `ID_MAX` with wire type **0 (unsigned)** is rejected by all
13, inside a skipped subtree or at the top level — verified separately, and that behaviour is
**correct**: §6.2's ceiling does bind a value-bearing header. The gap is specific to
**wire type 7**.

## Spec basis — `CORELIB_PLAN.md` at `main@51c777d`

**§4.9** states the rule in both directions and marks them asymmetric. An encoder MUST emit a
sequence end as exactly `0x07`; a decoder

> **MUST accept** a sequence-end header (wire type `0b111`) carrying **any** id, **discard**
> that id, and re-encode the marker as `0x07`. A non-zero id is **not** `INVALID`: it is
> normalized away, exactly as a non-minimal varint is (§4.1).

with the reason given as: the id sub-field exists only to keep the header format uniform, *"on
a sequence end it carries no information and never will, so there is nothing for a decoder to
validate."*

**§6.2** carves the marker out of the ceiling explicitly. `ID_MAX` and the Field ID range

> bound the id of a **value-bearing** field header — unsigned, signed, fixlen, the array
> types, and sequence *start*. They do **not** apply to the **sequence-end** marker, whose id
> is discarded rather than used (§4.9) […] an over-`ID_MAX` id on a sequence end is accepted
> and normalized away like any other.

Only §4.1's 64-bit varint bound survives here — a constraint on the *encoding*, not on an id.
The isolate's header is 5 bytes, well inside it.

**§5.2 / §6.3** — the `INVALID` enumeration does **not** list a non-zero sequence-end id. Its
only sequence-end condition is *"a sequence-end with no open sequence."* Nothing in the merged
document makes this input malformed.

**§7.2** adds test class **5b, tolerance tests**, which names this exact case:

> a **sequence-end header carrying a non-zero id** (§4.9) […] must decode as an ordinary
> sequence end and re-encode as `0x07`. These are the cases where a decoder is *stricter* than
> the format allows […] and the ones a majority-vote conformance check cannot catch, since an
> implementation may be uniformly too strict.

## Attribution — the nine rejecters, 8 corelib repos

Parsing a field header and deciding a format-level verdict is wire mechanics with no schema
involvement, so this is the corelib reader on each. Nine drivers map onto eight repos:

| driver | repo |
|---|---|
| `c`, `cpp-c-cpp` | corelib-c-cpp (one reader, both API profiles) |
| `cpp` | corelib-cpp |
| `csharp` | corelib-cs |
| `dart` | corelib-dart |
| `java` | corelib-java |
| `rust-std` | corelib-rs |
| `rust-no-std` | corelib-rs-no-std |
| `zig` | corelib-zig |

The fix is a removal, not an addition: stop applying the `ID_MAX` guard when the header's wire
type is 7, and discard the id instead.

## Untested residual — the normalization half

The isolate proves only the *verdict*. §4.9 also requires an accepting decoder to **re-encode
the marker as `0x07`**, and this isolate cannot show that: the end marker closes a *skipped*
unknown subtree, so the whole message re-encodes to the empty byte string on all four
accepters and the id's disappearance is unobservable. A vector placing a non-zero-id end
marker on a **declared** sequence is needed to test the round-trip half. `docs/TODO.md`
carries it.

## Reachability

The whole construct sits inside a **skipped** subtree, so it needs no valid schema context at
all — an undeclared id opened as a sequence and closed by an oversized end marker. Forward
compatibility requires every decoder to accept unknown ids, so this is reachable by any sender.

## Why no gate caught it

`sweep_framing` sweeps `ID_MAX` — `id_at_ID_MAX_ctl` and `id_over_ID_MAX` — but both place the
id on an **unsigned scalar** header, and its stray/unbalanced-sequence-end vectors all use the
canonical single-byte `0x07`. The product cell (an id over the ceiling *on a sequence-end
header*) is empty. Same shape as the gaps behind F-0044, F-0048 and F-0053: two axes each
correct, the cell where they meet untested.

The inversion adds a second, larger gap: Crucible has **no tolerance axis** at all (§7.2 5b).
A decoder that is *uniformly* too strict produces no divergence, so the differential oracle
cannot see it — this one surfaced only because the family happened to split 4-vs-9. Sweep
vectors carry an absolute expectation (`add(..., "accept")`), so the class is testable; it is
simply not swept. Both are in `docs/TODO.md`.

## History

Filed 2026-08-03 as the mirror image of this write-up — that `ID_MAX` binds every header
including wire type 7, hence the four accepters were at fault:
[corelib-go#67](https://github.com/sofa-buffers/corelib-go/issues/67),
[corelib-py#58](https://github.com/sofa-buffers/corelib-py/issues/58),
[corelib-ts#83](https://github.com/sofa-buffers/corelib-ts/issues/83). All three were closed
`COMPLETED` the same day on a proposed rule (a sequence-end id fixed at 0, non-zero →
`INVALID`) that **never became normative**: the spec change it deferred to landed the opposite
rule, quoted above. Those closures — and the announcement in them that the two `ctl_seqend_*`
controls would flip to `R` — do not describe the merged document and must not be acted on.

**All three were commented 2026-08-03** with the merged §4.9/§6.2 text, stating that their current
accepting behaviour is correct, that the `ID_MAX` guard must **not** be added on wire type 7, and
that the two controls stay accepting — plus a pointer to the eight re-filed issues and to §7.2's
new tolerance class 5b, which each of them should pin with a test. Left closed: there is nothing
in those three repos to fix.
