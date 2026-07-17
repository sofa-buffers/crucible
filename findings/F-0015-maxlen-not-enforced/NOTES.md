# F-0015 — a `string`/`blob` over its schema `maxlen`: 9 accept, 2 reject `invalid_msg`, 1 rejects `buffer_full`

**Status:** ✅ **FULLY RESOLVED** — spec clause adopted **and** implemented, verified against
the pre-bump baseline. **sofabgen 0.17.5** (`b0b2832`, "feat: reject over-maxlen strings/blobs
as INVALID on decode (Option B)") makes **all 12 drivers** answer `R invalid_msg` on all three
over-`maxlen` vectors — the baseline was 9 accept / 2 `invalid_msg` / 1 `buffer_full`. Both
halves landed: the 9 heap backends now enforce `maxlen`, **and** rust-nostd's `buffer_full`
became `invalid_msg` (the class correction §7.1 implies). The within-`maxlen` control still
accepts on all 12. All four vectors are now in the green `corpus/regression/` gate.

*The whole arc closed in one day:* hole found while preparing the regression → clause filed
(documentation#19) → spec PR authored & merged (#20) → codegen implemented (0.17.5) → verified
against the baseline. The baseline vectors are exactly what made "fixed" distinguishable from
"never tested".

**Original status —** spec-RESOLVED, corelibs to converge. The clause was **adopted** —
**[documentation#20](https://github.com/sofa-buffers/documentation/pull/20) merged** (`49cdee9`,
2026-07-17), closing [documentation#19](https://github.com/sofa-buffers/documentation/issues/19)
(`docs/spec-proposals.md`, Proposal 3). **MESSAGE_SPEC §7.1 now settles it:** a declared
`count`/`maxlen` is a wire-validity bound that binds **every target regardless of allocation
strategy**; a decoder *"MUST NOT accept an over-bound value merely because its storage happens
to be able to hold it"*. So the **9 heap backends must start enforcing `maxlen`**, and
`rust-nostd`'s `buffer_full` class is now wrong (a wire-validity failure → `invalid_msg`).
Target: **all 12 → `R invalid_msg`**. Like F-0001 (truncation) / F-0004 (UTF-8) /
F-0010 (under-count): resolved spec-first, then per-impl.
**Found:** 2026-07-17, while preparing the regression for an announced sofabgen update
reworking array/string/blob `count`/`maxlen` — the audit asked "which count/maxlen axes do
we actually cover?" and found this one **untested and already divergent**.
**Axis:** verdict + accept_value.
**Affects:** the whole family — a 9-vs-2-vs-1 split.

## The divergence

Every `maxlen` field in `schema/probe.sofab.yaml` splits the same three ways:

| behavior | re-encode | drivers | why |
|---|---|---|---|
| **accept, keep the over-long value** | `A …` with the full payload | cpp, rust-std, go, py-cython, py-pure, java, typescript, csharp, zig **(9)** | heap storage — `maxlen` is never consulted |
| **reject** | `R invalid_msg` | c, cpp-c-cpp **(2)** | fixed buffer sized from `maxlen` |
| **reject, different class** | `R buffer_full` | rust-nostd **(1)** | fixed buffer, different error class |

A value **within** `maxlen` → **all 12 agree** (`control_string_8_within_maxlen32.bin`).

So the three "enforcers" enforce only because their storage physically cannot hold more —
an **artifact of the memory model, not an implemented rule**. The same shape as F-0010
(under-count) and F-0013 (over-index): fixed-capacity profiles honor the schema bound by
accident, heap profiles ignore it entirely.

## The spec hole

The spec **never says** what a decoder must do when a `string`/`blob` exceeds `maxlen`:

- MESSAGE_SPEC mentions `maxlen` 5×, **never normatively** — §2 calls it *"a
  validation/sizing bound on string/blob byte length"* (in the list of attributes that never
  reach the wire); §3/§6 say it is optional "like `count`"; §5.1 uses it as a **pre-sizing
  hint** *"on heap-less profiles"*; §6 rejects it on a wrong element type (schema validity,
  not wire enforcement).
- **§7's "Enforce schema bounds as `INVALID`" enumerates only** `M > N` on a fixed-count
  array and a wrapper-array element id `≥ N` — **`maxlen` is absent**.
- **CORELIB_PLAN does not mention `maxlen` at all** (0 occurrences).

Contrast **`count`**, which *is* specified to bind every target since documentation#18
(§3: *"regardless of its storage model"*; §5.1: *"`N` for every target"*). `maxlen` never
got the same treatment — hence the divergence.

Two adjacent gaps ride along (both in Proposal 3):
- the **unbounded** case (no `count`/`maxlen`) — the receiver's allocate-per-message
  obligation is unstated for `string`/`blob`;
- **receiver-side technical limits** — the generator ships `max_dyn_*` caps (generator#102)
  and Crucible tests them with a dedicated `L` verdict, but CORELIB_PLAN §6.2 "Limits &
  Constants (normative)" lists only format-wide ceilings. `oracle/policy.yaml` has flagged
  this as a spec hole since Phase 1.

## Reproducers

All generated from the reference encoder's primitives; the schema fields are
`nested.str` (`maxlen: 32`), `nested.bytes_field` (`maxlen: 4`), `string_array.items`
(`maxlen: 64`).

- `string_40_over_maxlen32.bin` — a 40-byte string in a `maxlen: 32` field
- `blob_8_over_maxlen4.bin` — an 8-byte blob in a `maxlen: 4` field
- `strarray_elem_70_over_maxlen64.bin` — a 70-byte `string_array` element (`maxlen: 64`)
- `control_string_8_within_maxlen32.bin` — **control**, within the bound → all 12 agree

## Why it matters now

A sofabgen update reworking `count`/`maxlen` is announced. Without a clause it would
implement an **undefined** rule and the family would converge on an arbitrary answer.
F-0010 established the working order: hole → proposal (documentation#16) → adopted (#18) →
*then* generator#136 implemented the **adopted** rule uniformly. Proposal 3
(documentation#19) is filed first for exactly that reason.

These vectors are also the **baseline**: they record what all 12 do *before* the bump, so
the bump's effect is measurable rather than guessed.

## Expected resolution

Per Proposal 3 §7.x, the target is **all 12 → `R` (INVALID)**: a declared bound binds every
target regardless of allocation strategy. That moves the 9 heap backends to enforce
`maxlen`, and makes `rust-nostd`'s `buffer_full` class wrong (a wire-validity failure →
`invalid_msg`) — a small per-impl follow-up. The fix lands in **codegen**, as with
F-0010/F-0013: `maxlen` is schema knowledge the schema-agnostic corelibs do not have.

## Gate status

Kept **out of** `corpus/regression/` (they diverge by design until the clause lands and the
family converges). Promote `control_string_8_within_maxlen32.bin` now if desired (it is
already green); promote the three over-bound vectors once the family agrees.
