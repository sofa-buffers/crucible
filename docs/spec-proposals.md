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

**✅ ADOPTED** — [documentation#20](https://github.com/sofa-buffers/documentation/pull/20)
**merged** (`49cdee9`, 2026-07-17), closing
[documentation#19](https://github.com/sofa-buffers/documentation/issues/19). The clauses below
are now MESSAGE_SPEC §2/§7/§7.1/§7.2 and CORELIB_PLAN §6.2/§6.2.1/§6.3.

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

## Proposal 4 — §5.2/§4.3: a header wire type that contradicts the schema; repeated field ids

**✅ ADOPTED** — [documentation#23](https://github.com/sofa-buffers/documentation/pull/23)
**merged** (`0894035`, 2026-07-19). The clauses below are now MESSAGE_SPEC **§7.3** and
**§7.4**, adopted verbatim. All four Crucible spec proposals are now adopted
(#15→#17, #16→#18, #19→#20, #23).

**Motivated by:** **F-0020** (header wire type ≠ declared type) and **F-0019** (a field id
repeated in one scope). Two distinct not-well-formed inputs, one shared property: the spec
declares them illegal to *produce* but never says what a decoder must *do* with them. Both
are drafted here together because they interact (a repeated occurrence may also be
mis-typed) and a clause for one without the other leaves the combination undefined.

### The measurements

**F-0020** — a systematic sweep of every top-level field id × every wire type (66 vectors,
`findings/F-0020-header-wire-type-vs-declared-type/sweep.py`):

| | vectors | result |
|---|---|---|
| wire type **matches** the declared type (§1) | 11 | **all 12 drivers agree** |
| wire type **differs** | 55 | **all 55 diverge** |

100 % of the mismatch space is divergent, in four incompatible ways:

| behavior | drivers |
|---|---|
| skip the field | csharp, go, java, rust-std, rust-nostd, typescript, zig (7–9, per case) |
| `R usage` | c, cpp-c-cpp, py-cython, py-pure (4) |
| `R invalid_msg` | cpp (1) |
| **decode it anyway, wrong value** | cpp (1) |

The last is the sharp one: `01 06` is field id 0 (declared `u8` → wire Unsigned) carrying
wire type **Signed**, zig-zag payload `06` = 3. `cpp` re-encodes **`u8 = 6`** — the raw
un-zig-zagged varint. No reject, no warning; a wrong value delivered as if correct.

**F-0019** — a field id repeated in one scope:

| case | merge | replace |
|---|---|---|
| struct (`nested`, `arrays`) | 11 | typescript |
| union (`choice`) | 11 | typescript |
| array wrapper (`string_array`) | c, cpp, cpp-c-cpp (3) | 9 |
| **scalar** (`u8` twice) | — | **all 12 agree: last wins** |

Note the array wrapper inverts the majority, and typescript changes sides. There is no
consistent family behavior to codify by observation alone.

### The hole

CORELIB_PLAN §3 requires ids to be "unique within a single sequence/scope", and MESSAGE_SPEC
§1 maps each declared type to exactly one wire type. Both are constraints on the **encoder**.
Neither document states a **decoder** obligation for input that violates them. MESSAGE_SPEC
§7 requires generated code to enforce schema-bound violations it can detect, but never names
either case.

Consequently `oracle/policy.yaml` has no clause to cite for either divergence, and the
practical shape is a **parser differential**: the same bytes decode to different objects
depending on the implementation language. Where a validating service and a processing
service differ in language, that is the classic smuggling geometry.

### Proposed clause A (add to §5.2)

> **§5.2.x — A header wire type that contradicts the schema.**
> A field whose header wire type is not the one its declared type maps to (§1) — for
> `fixlen`, including the subtype — **MUST** be skipped exactly as a field with an unknown
> id is skipped. A decoder **MUST NOT** report it as `INVALID`, and **MUST NOT** decode its
> payload into the declared field.
>
> The check extends exactly as far as the wire format distinguishes: the 3-bit wire type,
> plus the fixlen subtype for `fixlen` fields. It cannot extend further — `u8`, `u16`,
> `u32`, `u64`, `boolean`, `enum` and `bitfield` all map to the same wire type (unsigned
> varint), so a header carrying that type is well-formed for any of them. Value-range
> conformance is not the subject of this clause.

### Proposed clause B (add to §4.3)

> **§4.3.x — A field id repeated within one scope.**
> Ids are unique within a sequence scope (CORELIB_PLAN §3); an encoding repeating one is
> **not well-formed**. A decoder **MUST** nevertheless process it deterministically, and
> **MUST NOT** report it as `INVALID`.
>
> For each field id in a scope, the **last** occurrence applies. The rule binds **per field
> id, not per sequence**: re-opening a sequence **continues** its scope. Children set in an
> earlier opening whose ids do not recur in a later one **are retained**. This covers
> structs and unions.
>
> **Array wrappers are the exception.** A wrapper carries the *value* of its array field
> (§5), not a namespace; a later occurrence **replaces** that value, discarding elements
> from earlier occurrences.
>
> *Example:* `seq[10]([3:blob] x) seq[10]([1:fp64] y)` decodes to
> `nested{ bytes_field = x, f64 = y }`.

### Interaction

Clause A applies first. An occurrence skipped under Clause A is **not** an occurrence for
Clause B, so a correctly-typed earlier occurrence survives a mis-typed later one.

### Implementation layer — deliberately unconstrained

Both clauses mandate the **observable outcome**, not which layer produces it. Typically
generated code performs the check, since only it knows the schema (§7). An object-API
profile may instead hand the schema to the corelib as a descriptor table and check there —
that is conformant. Without this paragraph the corelib-c-cpp object API would be
non-conformant by construction while doing the right thing.

### Both clauses follow from rules the format already has

Neither clause introduces a new concept; each is an existing rule applied to a case the
spec had not yet named.

**Clause A — "skip" is the mechanism the format already mandates.** A decoder must already
handle a field it cannot use: an unknown id is skipped by wire type (§5.2), and that skip
path exists in every implementation. A field whose wire type contradicts the schema is the
same situation — the decoder cannot use it — and reusing the existing treatment keeps one
rule instead of two. Choosing `INVALID` would create a *second*, divergent handling for
"a field this decoder cannot consume", where one is already specified and implemented.

**Clause B, scalars — already universal.** "Last occurrence wins" is not proposed but
*observed*: all twelve implementations already do exactly this for a repeated scalar
(measured, `control_dup_scalar.bin`). The clause records it so the rest can be derived
consistently.

**Clause B, sequences — follows from §3.** A sequence "opens a fresh ID scope **and nothing
more**". It carries no value of its own, so there is nothing for a last-wins rule to
replace; only the fields *inside* it carry values, and the rule applies to each of them by
id. Re-opening therefore continues the scope. This is the same rule as for scalars, applied
at the level where a value actually lives.

**Clause B, array wrappers — follows from §5.** §5 introduces the wrapper precisely so that
an array has an explicit representation of its own, including the explicitly empty array.
The wrapper therefore *is* the array field's value, not a namespace — so last-wins applies
to it whole. Again the same rule, applied where the value lives.

The distinction running through Clause B is thus not "sequence vs. non-sequence" but
**"namespace vs. value"**, which is exactly the distinction §3 and §5 already draw.

### Who this validates vs. requires to change

| clause | validated | must change |
|---|---|---|
| A | csharp, go, java, rust-std, rust-nostd, typescript, zig (skip) | **c, cpp-c-cpp, py** (stop rejecting) · **cpp** (currently mis-decodes) |
| B | 11 impls on struct + union; all 12 on scalars; 9 on the wrapper | **typescript** (struct + union) · **c, cpp, cpp-c-cpp** (wrapper) |

Two implementation notes, both verified against the sources:

- **corelib-c-cpp is a small, local change.** `istream.c:493` presets `ctx->target_opt` to
  the *actual* wire type before the field callback and leaves `target_ptr` NULL;
  `sofab_object_field_cb` (`object.c:396-410`) matches on **id alone** and then overwrites
  `target_opt` with the descriptor's *expected* type, so the post-callback comparison at
  `istream.c:307-321` fires `SOFAB_RET_E_USAGE`. That check is correct for its intended
  audience — a human calling the streaming API with the wrong `read` — but in the object
  path the "caller" is a generated descriptor table, so malformed *input* surfaces as a
  caller *usage* error. **The skip path already exists**: leaving `target_ptr` NULL skips the
  field with no check. So Clause A needs only that `object.c` compare the descriptor type
  against `ctx->target_opt` *before* registering the target and, on mismatch, not register.
  No new state, no API change — `object.h:44` includes `istream.h`, whose full
  `struct sofab_istream` (`istream.h:112`) exposes `target_opt`.
- **corelib-cpp needs a public accessor first.** The generated C++ dispatches on id alone
  (`probe.hpp:288-300`, `case 4: is.read(u32);`), violating the documented precondition
  (`sofab.hpp:1619`, *"The requested type must match the field's wire type"*). It cannot
  currently check: `deserialize(sofab::IStreamImpl &is, …)` receives the stream as a separate
  object and `type_` is `protected` (`sofab.hpp:1074`). So this is corelib-cpp **plus**
  generator — the F-0010 shape.

**Why the clauses reject nothing.** Both could have been resolved as `INVALID`. They are not,
for two reasons. First, rejecting a repeated id would require every decoder to track which
ids it has already seen per scope, across `MAX_DEPTH = 255` levels — real cost on heap-less
profiles, where "merge" is the zero-bookkeeping option a streaming decoder does by default.
Second, the security argument cuts the other way than it first appears: the parser
differential here comes from the rule being **undefined**, not from it being lenient. A
precisely specified lenient rule that all twelve follow has no differential.

Choosing `INVALID` for Clause A would additionally be expensive in a non-obvious way: in the
visitor-architecture backends (go, rust, java, csharp, zig) an unknown id and a known id with
the wrong type are **indistinguishable** — both fall through the same switch — while unknown
ids *must* be skipped. Telling them apart would require the generator to emit a per-scope
id → declared-type table in every backend.

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

**Proposal 3 — ✅ ADOPTED 2026-07-17** ([documentation#20](https://github.com/sofa-buffers/documentation/pull/20)
merged, closing #19). Filed *ahead of* the announced sofabgen count/maxlen update — so the
codegen now has a **defined** rule to implement rather than an undefined one. All three
Crucible spec proposals are now adopted (#15→#17, #16→#18, #19→#20). Motivated by **F-0015**. Filed *ahead of* an announced
sofabgen update reworking array/string/blob `count`/`maxlen` — deliberately, so the codegen
implements an **adopted** rule rather than an undefined one (the F-0010 order: hole →
proposal → adoption → codegen). Verified against the current spec (`documentation@c160838`):
of the four parts of the intended model, only **one is specified today** —
`count` binds every target (§3/§5.1, via documentation#18); `maxlen` binding, the
unbounded-field obligation, and the receiver-side `max_dyn_*` limits are **all
undocumented**.

**One open question raised in PR #20** (deliberately not decided unilaterally): CORELIB_PLAN
§6.3 says the decode result is the *three-valued outcome*, not a code from the error table,
and that the table covers "the *other* fallible operations". A receiver-limit rejection fits
neither — it is a decode-path terminal on **well-formed** input, so it is not `INVALID`, yet
the three-valued outcome has no value for *"valid, but more than I am configured to accept"*.
The PR states the **requirement** (it MUST stay distinguishable from `InvalidMessage`) and
leaves the **API shape** to the maintainers: a fourth decode outcome, or a terminal failure
carrying the new `LimitExceeded` code. Crucible already models it as a distinct fourth
verdict `L` (`oracle/canonical.md`), which is the fourth-outcome shape.

