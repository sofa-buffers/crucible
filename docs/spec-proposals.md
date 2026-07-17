# MESSAGE_SPEC proposals (from Crucible findings)

Crucible surfaces divergences that are either bugs *or* spec holes (PLAN §8). Two
open findings are spec holes — family-wide, no single impl is "wrong" until the spec
decides. These are drafted clauses to propose upstream in
`documentation/MESSAGE_SPEC.md`. Each cites the finding that motivates it and states
which implementations it validates vs. requires to change.

---

## Proposal 1 — §7: INVALID takes precedence over INCOMPLETE

**Filed:** [documentation#15](https://github.com/sofa-buffers/documentation/issues/15).

**Motivated by:** F-0006 (corelib-py, fixed) and F-0007 (corelib-c-cpp, fixed). Both
decoders reported **INCOMPLETE** for a message that was *both* malformed (a fixlen
fp field whose declared length ≠ its exact width) *and* truncated, because they hit
end-of-input before validating the field header. The rest of the family reported
**INVALID**. The fixes made them validate the header eagerly — this clause records
the rule the fixes implement.

### Proposed clause (add to §7)

> **§7.x — Precedence of INVALID over INCOMPLETE.**
> A decode reports exactly one of `COMPLETE`, `INCOMPLETE`, or `INVALID`. When the
> bytes consumed so far contain a construct that is malformed **independently of any
> bytes that might follow**, the outcome is **`INVALID`**, even if the message is
> *also* truncated (ends mid-field or with an open sequence). Such constructs
> include:
> - an unknown or reserved wire type;
> - a varint whose encoding exceeds 64 bits;
> - a fixed-length field whose declared length is not the exact width its subtype
>   requires (`fp32` → 4, `fp64` → 8);
> - a field length or array count that violates the format or the schema (over-max,
>   or over the schema `count`, see §7.y);
> - a stray sequence-end, or nesting beyond `MAX_DEPTH`.
>
> `INCOMPLETE` is reported **only** when every construct consumed so far is
> well-formed and the bytes simply end before the message is complete. A decoder
> **MUST NOT** report `INCOMPLETE` for a message it has already determined to be
> malformed.
>
> Consequently, a decoder **MUST** validate a construct's well-formedness when its
> header is read — before consuming, buffering, or waiting for its payload. (A
> decoder that defers the check until it consumes the payload can reach end-of-input
> first and mis-report malformed input as `INCOMPLETE`.)
>
> **Rationale.** `INVALID` is defined as "malformed regardless of what follows" — no
> continuation of bytes can make the message valid. Reporting `INCOMPLETE` would
> wrongly invite the caller to supply more bytes for a message that can never
> succeed.

**Impact:** validates the whole family as it stands post-fix (c, go, rust, cpp,
cpp-c-cpp, py, java, ts, cs, zig all now return INVALID on these inputs). Codifies
the F-0006/F-0007 fixes so no future implementation reintroduces the eager-vs-lazy
gap.

---

## Proposal 2 — §5/§3: under-count of a fixed-count array

**Filed:** [documentation#16](https://github.com/sofa-buffers/documentation/issues/16).

**Motivated by:** F-0010. A fixed-count array (schema `count: N`) that receives
`0 < M < N` elements on the wire round-trips to **different values** across the
family — a clean split along the storage model:

| camp | decodes `count 3` of a `count: 5` array to | drivers |
|---|---|---|
| **fill to N** | `[…3 elems…, default, default]` (N elements) | c, rust-std, rust-nostd, cpp, cpp-c-cpp, zig |
| **keep M** | `[…3 elems…]` (M elements) | go, py-cython, py-pure, java, typescript, csharp |

`count == 0` (all-default array, omitted) and `count == N` already agree; `count > N`
is `INVALID` (§3, F-0003). Only `0 < M < N` is undefined today.

### Proposed clause (add to §5, arrays)

> **§5.z — Fixed-count array element count.**
> A field declared `count: N` is a **fixed-length** array of exactly `N` logical
> elements. On the wire its element count `M` **MUST** satisfy `0 ≤ M ≤ N`; `M > N`
> is **`INVALID`** (§7). A wire count `M < N` denotes an array whose last `N − M`
> elements are the **element default** (a trailing-default run, elided for
> compactness — the same sparse principle by which a default scalar field is omitted
> entirely). A decoder **MUST** materialize exactly `N` elements, default-filling
> positions `[M, N)`.
>
> **Canonical encoding.** An implementation **MUST** emit `M` = one past the index of
> the last non-default element (`0` when every element is default, in which case the
> whole array field is omitted — it is a default field). That is, trailing default
> elements are **not** emitted.
>
> **Rationale.** The schema fixes the count, so the array always has `N` elements;
> the on-wire count is a compaction of a trailing-default run, exactly analogous to
> omitting a default scalar field. Defining decode as "fill to `N`" makes the
> round-trip well-defined regardless of the receiver's storage model (fixed array
> vs. growable list).

**Impact & alternative.** This resolution (the **sparse / fill-to-N** reading)
requires:
- the *keep-M* camp (go, py, java, ts, cs) to **default-fill to `N` on decode**;
- the *fill-to-N* camp (c, rust, cpp, zig) to **omit trailing default elements on
  encode** (they currently emit all `N`, including trailing defaults).

A simpler **always-`N`** alternative — "a present fixed array always carries exactly
`N` elements on the wire" — changes only the keep-M camp (decode + encode fill to
`N`) and matches the fill-to-N camp's current encoding, but forgoes the compaction of
trailing defaults. The maintainers should pick; Crucible will enforce whichever lands
(the `arrays` value vectors in `corpus/structured/` are ready, and the F-0010
reproducers become a regression gate once the family converges).

---

## Proposal 3 — §7/§6.2: a declared bound binds **every** target; unbounded fields; receiver limits

**Filed:** [documentation#19](https://github.com/sofa-buffers/documentation/issues/19).

**Motivated by:** **F-0015** — a `string`/`blob` whose wire length exceeds its schema
`maxlen` splits the family **three ways**, on every maxlen field in the schema
(`nested.str` 32, `nested.bytes_field` 4, `string_array` items 64):

| behavior | drivers | why |
|---|---|---|
| **accept, keep the over-long value** | cpp, rust-std, go, py-cython, py-pure, java, typescript, csharp, zig (9) | heap storage — `maxlen` is simply never consulted |
| **`R invalid_msg`** | c, cpp-c-cpp (2) | fixed buffer sized from `maxlen` |
| **`R buffer_full`** | rust-nostd (1) | fixed buffer, different error class |

A value **within** `maxlen` → all 12 agree. So the three "enforcers" enforce only because
their storage physically cannot hold more — an artifact of the memory model, not an
implemented rule. Exactly the shape of F-0010 (under-count) and F-0013 (over-index).

### The hole

The spec never says what a decoder must do when a `string`/`blob` exceeds `maxlen`:

- MESSAGE_SPEC mentions `maxlen` five times, **never normatively**: §2 calls it
  *"a validation/sizing bound on string/blob byte length"* (in the list of attributes that
  never reach the wire); §3/§6 note it is optional "like `count`"; §5.1 uses it as a
  **pre-sizing hint** *"on heap-less profiles"*; §6 rejects it on the wrong element type
  (schema validity, not wire enforcement).
- **§7's "Enforce schema bounds as `INVALID`" enumerates only** `M > N` on a fixed-count
  array and a wrapper-array element id `≥ N`. **`maxlen` is absent.**
- **CORELIB_PLAN does not mention `maxlen` at all** (zero occurrences).

Two adjacent gaps come with it:
- **the unbounded case** — omitting `count`/`maxlen` is described for arrays (§3: *"there is
  no `N` to fill to"*) but the receiver's obligation for a bound-less `string`/`blob` is
  unstated;
- **receiver-side technical limits** — the generator already ships generic caps
  (`max_dyn_array_count` / `max_dyn_string_len` / `max_dyn_blob_len`, generator#102) and
  Crucible tests them with a dedicated fourth verdict `L`, but **CORELIB_PLAN §6.2 "Limits &
  Constants (normative)" lists only format-wide ceilings** (`ID_MAX`, `FIXLEN_MAX`,
  `ARRAY_MAX`, `MAX_DEPTH`, value domains). The configurable receiver cap is undocumented —
  Crucible's own `oracle/policy.yaml` has flagged this as a spec hole since Phase 1.

### Proposed clauses

> **§7.x — A declared bound binds every target (normative).**
> A schema `count: N` on an array and a `maxlen: L` on a `string`/`blob` are **wire-validity
> bounds**, not sizing hints. They bind **every implementation regardless of its allocation
> strategy**: a heap-less target that pre-sizes from the bound and a heap target that
> allocates per message **MUST both reject** input that exceeds it. A decoder **MUST NOT**
> accept an over-bound value merely because its storage happens to be able to hold it.
>
> Accordingly, extend §7's enumeration — a wire element count `M > N` on a fixed-count
> array, a wrapper-array element id `≥ N`, **or a `string`/`blob` whose wire byte length
> exceeds its schema `maxlen`** — is malformed input and **MUST** be reported as `INVALID`.
>
> **§7.y — Omitting a bound declares an unbounded field (normative).**
> A `string`/`blob` without `maxlen`, or an array without `count`, is **unbounded**: the
> receiver **MUST** materialize as much as the received message specifies. An unbounded
> field has no schema bound to violate, so its length alone can never yield `INVALID`
> (the format-wide ceilings of CORELIB_PLAN §6.2 still apply). This form is available only
> to targets that allocate dynamically; heap-less profiles require the bound in order to
> pre-size, so a schema intended for them **MUST** declare it.
>
> **§6.2.x — Receiver-side technical limits are configuration, not schema (normative).**
> Because an unbounded field lets the *sender* dictate the *receiver's* allocation, an
> implementation **MAY** be configured with **generic maximum limits** — independent of any
> message definition — capping the array count / string length / blob length it will
> materialize (the generator's `max_dyn_*` options). These protect the receiver; they are
> **not** part of the wire contract.
>
> Exceeding such a limit is a **policy rejection by the receiver — a category distinct from
> `INVALID`**: the bytes are well-formed and decode successfully under a looser or unset
> limit. An implementation **MUST NOT** conflate the two, and **MUST NOT** apply a generic
> limit to a field whose schema already bounds it (there the schema bound governs, per
> §7.x). Two receivers configured with **different** limits reaching different outcomes on
> the same message is **not** an interop failure and **not** a conformance defect.

### Impact

- **§7.x** — validates `c`, `cpp-c-cpp`, `rust-nostd` (already reject); requires the **9 heap
  backends** to start enforcing `maxlen`. Also makes `rust-nostd`'s `buffer_full` class wrong
  (it is a wire-validity failure → `invalid_msg`), a small per-impl follow-up.
- **§7.y** — codifies existing behavior; nothing changes for the heap camp on bound-less
  fields.
- **§6.2.x** — codifies what the generator already implements (generator#102) and what
  Crucible already tests (limit mode, the `L` verdict), and closes the spec hole
  `oracle/policy.yaml` has carried since Phase 1.

Where the fix lands is **codegen** (as with F-0010/F-0013): `maxlen`/`count` are schema
knowledge the schema-agnostic corelibs do not have, so generated code must enforce them —
the same conclusion the §7 preamble already draws ("The corelib cannot know the schema").

**Timing.** A sofabgen update reworking array/string/blob `count`/`maxlen` is expected. Filing
this **first** is deliberate: F-0010 showed the working order — hole → proposal
(documentation#16) → adopted (#18) → *then* generator#136 implemented the **adopted** rule
uniformly. Without a clause, the codegen would implement an undefined rule and the family
would converge on an arbitrary answer.

---

## Status

**Proposals 1 + 2 ADOPTED upstream (2026-07-16); Proposal 3 filed 2026-07-17.**
- Proposal 1 → **documentation#17** merged (`1018e0c`): §5.2 gains the normative
  *precedence of `INVALID` over `INCOMPLETE`*; §4.6 makes wrong-width `fp32`/`fp64`
  an explicit `INVALID`; §6.3 `InvalidMessage` row + MESSAGE_SPEC §7 updated. Closes
  documentation#15.
- Proposal 2 → **documentation#18** merged (`ac621db`): the **sparse fill-to-N**
  reading. §3 redefines `count: N` as a fixed-length array of exactly N logical
  elements; a wire count `M < N` is a *trailing-default run*; decode **MUST**
  materialize N, canonical encode **MUST** elide the trailing default run
  (`M` = one-past-last-non-default); `M > N` and element id `≥ N` are `INVALID`.
  Closes documentation#16.

**Compliance audit vs the adopted clauses (2026-07-16, all 12 drivers):**
- Proposal 1 / §5.2 — ✅ **whole family compliant.** wrong-width fp fixlen (`56 0a 59`
  and three siblings) → all 12 `R`; over-count `M>N` → all 12 `R`. (This codifies the
  F-0006/F-0007 fixes; nothing left to do.)
- Proposal 2 / §3+§5.1 — ✗ **family split, neither camp fully compliant** (this is
  F-0010, now with a definite spec direction):
  - **encode (observable):** `c, rust-std, rust-nostd, cpp, cpp-c-cpp, zig` emit the
    **trailing default run** (`[7,8,9,0,0]`, wire count 5) → violate the §3 canonical
    "MUST NOT emit the trailing default run." The 6 systems backends need the encoder
    to trim to `M` = one-past-last-non-default.
  - **decode (latent — round-trip-masked):** `go, py-cython, py-pure, java, typescript,
    csharp` keep `M` elements and do **not** default-fill to `N` (go confirmed by
    source: `[]uint32` slice, `m.U32 = narrow(v)`, encodes `len(m.U32)`) → violate
    §5.1 "a growable-list target MUST default-fill to N." Their **wire** is canonical
    (count 3), so the round-trip oracle cannot see this — only direct element/length
    access would. Recorded in F-0010.
  See [`../findings/F-0010-undercount-array-pad-vs-keep/NOTES.md`](../findings/F-0010-undercount-array-pad-vs-keep/NOTES.md).

Attribution traced (the F-0008 lesson applied): **codegen, not corelib** — the
schema-agnostic corelib array writers only write `count = len(passed slice)` and are
correct; both fixes need `N` / fixed-vs-dynamic, which live only in generated code.
Filed **[generator#136](https://github.com/sofa-buffers/generator/issues/136)** with
the R1/R2 reproducers. F-0004's §8 UTF-8 opt-in check remains unimplemented family-wide
(generator#85).

**Proposal 3 — filed [documentation#19](https://github.com/sofa-buffers/documentation/issues/19)
(2026-07-17), awaiting adoption.** Motivated by **F-0015**. Filed *ahead of* an announced
sofabgen update reworking array/string/blob `count`/`maxlen` — deliberately, so the codegen
implements an **adopted** rule rather than an undefined one (the F-0010 order: hole →
proposal → adoption → codegen). Verified against the current spec (`documentation@c160838`):
of the four parts of the intended model, only **one is specified today** —
`count` binds every target (§3/§5.1, via documentation#18); `maxlen` binding, the
unbounded-field obligation, and the receiver-side `max_dyn_*` limits are **all
undocumented**.

