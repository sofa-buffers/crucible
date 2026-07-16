# MESSAGE_SPEC proposals (from Crucible findings)

Crucible surfaces divergences that are either bugs *or* spec holes (PLAN §8). Two
open findings are spec holes — family-wide, no single impl is "wrong" until the spec
decides. These are drafted clauses to propose upstream in
`documentation/MESSAGE_SPEC.md`. Each cites the finding that motivates it and states
which implementations it validates vs. requires to change.

---

## Proposal 1 — §7: INVALID takes precedence over INCOMPLETE

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

## Status

Neither clause is filed upstream yet. When adopted in `MESSAGE_SPEC.md`, the
corresponding corelib work is tracked per-impl (epic-style, like §7/#86 and §8/#85),
and Crucible flips F-0007's residual note and F-0010 to green as the family converges.
