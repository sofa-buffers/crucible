# F-0014 — the ARRAY_FIXLEN element word is not (fully) validated at the header → INCOMPLETE instead of INVALID

**Status:** open — filed per-impl: **[corelib-c-cpp#89](https://github.com/sofa-buffers/corelib-c-cpp/issues/89)**,
**[corelib-py#41](https://github.com/sofa-buffers/corelib-py/issues/41)**,
**[corelib-ts#51](https://github.com/sofa-buffers/corelib-ts/issues/51)** (follow-up to the
fixed corelib-ts#49).
**Found:** 2026-07-17 by the **coverage-guided fuzzer** (1 h round, 143 M execs) — the
residual precedence clusters that remained after corelib-ts#49 removed the dominant one.
**Axis:** verdict (INVALID vs INCOMPLETE — the §5.2 precedence family).
**Affects:** `c` + `cpp-c-cpp`, `py-cython` + `py-pure`, `typescript` — each on a *different*
missing check.

## The class

MESSAGE_SPEC **§4.8**: an `ARRAY_FIXLEN` carries **only** `fp32` (element size 4) or `fp64`
(size 8). **§5.2**: a construct malformed regardless of what follows is `INVALID` — and must
be rejected when its *describing bytes* (here the element word) are read, **before**
consuming or waiting for the payload. A decoder that defers reaches end-of-input first and
mis-reports malformed input as `INCOMPLETE`.

This is the same bug class as the already-fixed **F-0006** (corelib-py#38), **F-0007**
(corelib-c-cpp#82) and **F-0012** (corelib-ts#49) — all of which fixed the **scalar** fixlen
path. F-0014 is the **array** path, still unfixed, and each impl misses a *different* check:

| isolate | what is malformed | defers to `I` | rejects `R` |
|---|---|---|---|
| `45 05 22` | element subtype = `STRING` (§4.8: fp32/fp64 only) | **c, cpp-c-cpp** | the other 10 |
| `75 60 00 0d 0d` | `fp32` element with size `0` (must be 4) | **py-cython, py-pure** | the other 10 |
| `56 07 a6 06 56 0d 7f 01 09 ff ff 05` | reserved element subtype `7`, at a *known* fp64-array field | **typescript** | the other 11 |

Note the matrix: **c validates size-vs-subtype but not subtype-vs-fieldtype; py validates the
subtype but not the size; ts validates both but too late.** Each is a partial implementation
of the same rule.

## Root causes (traced per impl)

**corelib-c-cpp — the element-word switch never learns it is in an array.**
`_DECODER_STATE_FIXLEN_LEN` (`src/istream.c:668`, switch at :674–707) validates subtype ∈
{fp32,fp64,string,blob} (`default:` → INVALID :705), `fp32` size == 4 (:682), `fp64` size == 8
(:692), `size <= SOFAB_FIXLEN_MAX` (:710) — but **omits §4.8's array restriction**. The state
is shared *verbatim* between scalar `FIXLEN` (:506) and `FIXLENARRAY` (:876/:921) and the
switch never consults which one it is, though the field type sits in `ctx->target_opt` and
*is* used further down (:736, :771, :809). So subtype `STRING` in an array falls into the
string arm → `_DECODER_STATE_FIXLEN_RAW` → waits for payload → `INCOMPLETE`.

**corelib-py — the width check the comment promises does not exist.**
`_read_header`'s ARRAY_FIXLEN branch (`src/sofab/decoder.py:378–401`, element word :389–393)
validates `subtype > FixlenSubtype.FP64` → INVALID (:392) but **omits every check on
`elem_size`** (:390) — no `4`/`8` width, no `FIXLEN_MAX`. `elem_size` flows into `_pending`
(:363) and only becomes a byte count at `_farray_nbytes` (:407). The scalar branch above
(:338–341) does both — and **its comment at :335 already refers to "the eager element-width
check on the fixlen-array path below"**, a check that was never written.

**corelib-ts — ordering, not a missing check (and #49 already knew).**
`arrayFixlenHeader` (`src/decode/cursor.ts:411`) validates the element word *correctly and
completely* (`sub !== wantSub || size !== wantSize` → INVALID, :418–420). But it calls
`arrayCount()` **first** (:414), and `arrayCount` (:374) throws
`incompleteError("truncated array")` when `count > remaining` — before the element word is
ever read. Commit `0279378` (#49) **identified this exact trap** and sidestepped it in
`skipValue`'s ArrayFixlen case (:296–331) by inlining the count parse, with a comment saying
the guard *"would report a malformed-element array as INCOMPLETE instead of INVALID
(corelib-ts#49)"* — the reasoning just wasn't carried to the known-field path. `fast.ts:164`
is unaffected (its `arrayCount`, fast.ts:217, has no remaining-bytes guard).

## Why the fuzzer found it now

corelib-ts#49 removed the dominant precedence cluster (**66% → gone**; the sample's divergence
rate fell **86% → 32%**). That unmasked the residual clusters — 149 (py), 97 (c-family), 94
(ts) inputs — which all turned out to be this one class on the array path. Each isolate above
is minimal and pins exactly one impl as the lone `I`.

## Reproducers

- `c_family_subtype_string.bin` — `45 05 22`
- `py_fp32_size0.bin` — `75 60 00 0d 0d`
- `ts_reserved_subtype_known_field.bin` — `56 07 a6 06 56 0d 7f 01 09 ff ff 05`

## Gate status

Kept **out of** `corpus/regression/` (they diverge by design until the three fixes land).
Promote each into the gate as its issue closes — the F-0007/F-0006/F-0012 precedent.
