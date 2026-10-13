# Canonical form (v2 — round-trip re-encoding, three-valued verdict)

Every driver decodes an input and prints **exactly one line** describing the
result. The comparator (`oracle/comparator.py`) diffs these lines byte-for-byte
across implementations, so the form must be unambiguous and identical regardless
of language and message shape.

## Grammar

```
line       := accept | incomplete | reject | limit | refused
accept     := "A" SP hex          ; COMPLETE — hex of the re-encoded sparse-canonical wire
incomplete := "I"                 ; INCOMPLETE — decode ended mid-message; no payload (see "The `I` line has no payload")
reject     := "R" SP class        ; INVALID — malformed regardless of what follows
limit      := "L" [ SP class ]    ; LIMIT_EXCEEDED — a configured receiver-side decode cap was exceeded (limit mode only)
refused    := "E" SP class        ; the decode ACCEPTED, and re-encoding that value was REFUSED (generator#656)
class      := "invalid_msg" | "argument" | "usage" | "buffer_full" | "limit_exceeded" | "other"
hex        := *( HEXDIG HEXDIG )  ; lowercase, two digits per byte; empty allowed
```

A trailing `\n` terminates every line. No other output goes to stdout (logs →
stderr).

### The reject classes, and which of them may legally appear

CORELIB_PLAN §6.3 fixes the error taxonomy at **five** codes — `None`/`OK`,
`BufferFull`, `InvalidArgument`, `InvalidMessage`, `LimitExceeded` — and settles what
used to be an open question here by removing a category rather than refining it:

> **A type-mismatched read is not an error at all.** […] There is therefore **no**
> result code for "invalid usage": every remaining caller mistake is an out-of-range
> argument (`InvalidArgument`) and every remaining malformed input is `InvalidMessage`.

So the classes are not six equal alternatives to be compared. They fall into three
groups, and the comparator treats them differently:

| class | status | why |
|---|---|---|
| `invalid_msg` | **expected** | the `INVALID` outcome; what a decode reject is |
| `limit_exceeded` | **expected** (limit mode) | §6.2.1's receiver cap, its own code and its own `L` verdict |
| `argument`, `buffer_full`, `other` | **allowed but reported** | §6.3 permits language-specific conditions "as long as the baseline meanings are preserved", so these are legal — but `argument` on the **decode** path is one of *two* distinct shapes. Historically it meant a generated layer erred where the family cleanly rejects (the F-0003 / F-0008 codegen-defect shape). Since §6.3 grew a third refusal tier, it can *also* mean the spec's own **`InvalidArgument`**: a destination too short for the value handed over (§6.6.3), told apart from a schema-bound violation (`InvalidMessage`) and a receiver-cap rejection (`LimitExceeded`). That second shape is legitimate, not a defect, and is where the fixed-capacity profiles in the roster (`c`, `cpp-c-cpp`, `cpp-fixed`, `rust-nostd`) can produce it on a decode. Either way it is surfaced as a warning, never silently equal — the two shapes are told apart by which profile emitted it and what the destination actually was, not by the class name alone |
| `usage` | **FORBIDDEN** | §6.3 abolishes the category. A driver emitting it reports a corelib carrying a code the spec says cannot exist |

**Why this is checked per line and not by comparing drivers.** The `reject_class` axis
is hard, but it only fires on *disagreement*: if every implementation named the same
forbidden class, the run would be unanimous and therefore green. A class that must never
appear cannot be policed by agreement — it is checked on its own, per line, whatever the
others said. This is the "cross-tier" case docs/TODO.md asked for, and the reason it
needed its own mechanism.

**Measured 2026-08-17, before the check was added:** across `corpus/interesting` (6000
inputs), `crashes`, `regression`, `conformance`, `seeds`, `union` and `structured`, over
all fifteen drivers, **every reject is `invalid_msg`**. Nothing emits `usage`, `other`,
`argument` or `buffer_full` today, so the check starts green — it exists to keep it that
way. **No source of `usage` remains in the roster.** The last one was `corelib-py`'s
`SofaStateError`, filed as
[corelib-py#96](https://github.com/sofa-buffers/corelib-py/issues/96) and **merged
2026-08-17**: it is now a deprecated alias of `SofaRangeError` — which *is* §6.3's
`InvalidArgument` — and the four type-mismatched reads that used to raise return `None`
and skip the field instead (MESSAGE_SPEC §7.3), so they yield no reject class at all.
Re-measured here on both engines after removing a stale compiled `_speedups` artifact that
had made the first attempt report the pre-fix behaviour: all four skip, pure and cython
alike. `drivers/python/driver.py`'s dead `usage` row went with it.

So the check now guards a class nothing can emit. That is the point of keeping it: it
costs one comparison per line, and it is what makes the state unreachable rather than
merely absent — including for a driver added later, whose author would otherwise have only
this document's prose to go on.

## The three verdicts (MESSAGE_SPEC §7)

Decoding is three-valued and finish-less — a decoder reports exactly one of
`COMPLETE` / `INCOMPLETE` / `INVALID`, and the driver maps that to the line's
first character:

| corelib outcome | line | meaning |
|---|---|---|
| `COMPLETE` | `A <hex>` | consumed bytes end exactly at a field boundary; a valid message |
| `INCOMPLETE` | `I` | bytes end **inside** a field/varint or an open sequence — valid so far, not a complete message. **Not an error** (§7); the caller owns end-of-input |
| `INVALID` | `R <class>` | malformed regardless of what follows (unknown wire-type, varint > 64 bits, count/length over max, `MAX_DEPTH`, stray sequence-end) |

`A` / `I` / `R` are **three distinct hard verdict values**: two implementations
disagreeing on which one applies is a `verdict` divergence (a finding). A driver
**MUST NOT** collapse `INCOMPLETE` into either neighbour — reporting `A` for a
truncated message (accept-as-done) or `R` (reject-as-malformed) is itself the bug
this axis exists to catch (see F-0001).

### The fourth verdict `L` (LIMIT_EXCEEDED, limit mode only)

| corelib outcome | line | meaning |
|---|---|---|
| `LIMIT_EXCEEDED` | `L` (or `L <class>`) | a **configured** receiver-side decode cap (`max_dyn_array_count` / `max_dyn_string_len` / `max_dyn_blob_len`, generator#102) was exceeded on a schema-*unbounded* field. The bytes are well-formed; rejecting them is receiver **policy** — a category deliberately **distinct from `R` (INVALID)** |

`L` exists because a limit violation is *not* a wire-conformance failure: the same
bytes decode fine under a looser (or unset) limit. It appears **only in limit mode**
(`scripts/run-limits.sh`), where every driver in the roster is generated with the
**same** caps — so they must all agree on `L`, and a disagreement is a `verdict`
finding exactly like `A`/`I`/`R`. In the default conformance/fuzz run **no limits are
configured** (unset = unlimited), so `L` can never occur there and every driver's
output ranges over `A`/`I`/`R` as before. Because the caps only bind schema-unbounded
fields, limit mode uses a dedicated **unbounded** schema (`schema/probe-dyn.sofab.yaml`)
and a **heap-only** driver roster (the fixed-capacity profiles — c, c-cpp, rust-nostd —
cannot represent an unbounded field; see `scripts/run-limits.sh`). Comparing a limited
against an unlimited implementation is **not** a divergence and is avoided by
construction (identical caps across the roster) — which is not this document's own rule
but the spec's: **CORELIB_PLAN §6.2.1** (normative) states that two receivers configured
with different limits reaching different outcomes is neither an interop failure nor a
conformance defect, and that conformance testing therefore compares implementations
configured identically. It also gives the condition its own error code, `LimitExceeded`
(§6.3), and forbids reporting it as `InvalidMessage` — which is what `L` being a category
distinct from `R` encodes here. MESSAGE_SPEC §5.4's `MAX_DEPTH` note is the stack
analogue. *(This paragraph read "the heap note is pending upstream (generator#102)" until
2026-08-18; §6.2.1 closed that hole and the citation had gone stale.)*

### The fifth verdict `E` (the re-encode was refused)

| what happened | line | meaning |
|---|---|---|
| decode said `COMPLETE`, and re-encoding that value was **refused** | `E <class>` | the implementation accepted bytes its own encoder will not write back. Not a decode outcome at all — the decode said accept |

**Why this is not an `R`.** Until generator#656 an encode could only fail by running out
of buffer, and the drivers encode into the schema's own worst case (`MAX_SIZE`), so
"encode failed after a successful decode" was the impossible branch this document used
to describe as "it should not, given a worst-case buffer" and every driver mapped to a
reject class. #656 gave that branch a **designed trigger**: a value past a declared
bound — a `string`/`blob` over `maxlen`, an array over `count`, an integer, enum or
bitfield outside its declared width — is refused at encode with §6.3's `InvalidArgument`,
never clamped and never emitted (generator `docs/ARCHITECTURE.md` §9.6.1). So the branch
is now reachable, and reporting it as `R <class>` states the one thing that definitely
did **not** happen: that the input was malformed. It was accepted. `R` and `E` are facts
about opposite halves of the stack, and they get different verdicts for the same reason
`L` is not `R`.

**What an `E` means.** One implementation contradicting itself:

- its decoder accepted a value past a schema bound — the §7.1 enforcement gap of the
  F-0015 / F-0033 shape — **or**
- its encode guard refuses a value that is in fact within bounds — the F-0052 shape (a
  bound compared against the wrong quantity or the wrong width).

Both are findings, and which one it is decides the attribution: a schema fact (`count`,
`maxlen`, a declared width) can only be known by generated code, wire mechanics by the
corelib (CLAUDE.md's triage table). The `E` line says *which driver* contradicted itself;
reading its generated guard against its corelib's reader says which half is wrong.

**Checked per line, not by agreement** — the mechanism the forbidden `usage` class
already uses, and for the same reason: a verdict that must never appear cannot be
policed by comparing drivers. Every driver answering `E` for one input is the family
sharing one bug, not a green run. So every `E` fails the run on its own, whatever the
others said, and it *also* shows up as a `verdict` divergence against whoever answered
`A` — one fact reported twice, as a forbidden reject class already is.

**The class** is whatever the corelib named: `argument` for §6.3's `InvalidArgument`,
which is what #656 refuses with and therefore the only class expected here;
`buffer_full` or `other` otherwise, and either of those is its own defect (a worst-case
buffer that is not, or a failure mode outside the taxonomy). On mutual `E` the class is
compared on the `encode_class` axis.

**`E` never replaces `I`.** The `I` verdict is a statement about the decode, and it is
hard. An `INCOMPLETE` decode is never re-encoded at all (it has no payload, below), so
there is nothing to refuse — answering `E` (or `R other`) there would let an encode-side
fact overwrite a decode-side verdict, which is the `I`-into-`R` collapse F-0001 exists
to catch.

**Measured 2026-10-12, when the verdict was added:** zero `E` lines over the whole
roster across `corpus/seeds`, `corpus/structured`, `corpus/conformance` and
`corpus/regression` — every value the family accepts, it re-encodes. The verdict
starts green and exists to keep the decode and encode halves of one stack from drifting
apart silently, which is the state #656 made possible. Reaching an `E` from the wire
needs a decoder bug, which is why no corpus can demonstrate one: the encode-bound cells
themselves (a value filled past its bound through the generated setters) are the
generator's own conformance suite, `tests/conformance/lib/check_encode_bounds.py`, not
this harness — Crucible's half is the asymmetry, not the guard.

### The `I` line has no payload

`I` stands alone. A partial value is not a decode result: what an out-parameter API
(Java's `tryDecode(data, out)`) leaves in its destination after an `INCOMPLETE` decode
is defined nowhere, and a value-returning API (Rust's `Err`) hands back nothing at all —
so a payload would compare API shapes, not decoders. It also compared nothing — only Java and the Kotlin legs ever
printed it, so the comparison it fed (`incomplete_value`, soft) could only ever tell
those drivers apart from everyone else, and it did, thousands of times per corpus, on a
difference that was the drivers' and not the corelibs'. The comparator rejects an `I`
line that carries anything after the letter as malformed. The verdict itself (`I` vs
`A`/`R`) is hard, as before.

## How `accept` is produced: decode → re-encode → hex

On a successful decode the driver **re-encodes the decoded message** with the
corelib's own encoder and emits the lowercase hex of those bytes:

```
value  = decode(input)          # reject on failure
bytes  = encode(value)          # the sparse-canonical wire form
line   = "A " + hex(bytes)
```

Why this instead of walking fields:

- **Schema-agnostic.** The driver never references individual fields, so scaling
  the schema (arrays, nested structs, unions, blobs, unicode) needs **zero**
  driver changes — only the generated `decode`/`encode` change.
- **Faithful decoded-value comparison.** The generated encoders are
  deterministic and sparse-canonical (MESSAGE_SPEC S2/S5.1), and the whole family
  produces byte-identical wire for the same value (this is exactly the invariant
  the `arena` reference-wire SHAs enforce). So *identical decoded value ⇒
  identical re-encoded bytes*, and any decode divergence surfaces as a hex diff.
- **Round-trip oracle for free.** Comparing re-encoded bytes also catches an
  encoder that produces non-canonical output for a value others encode
  canonically — the round-trip invariant from PLAN §6, folded into the decode
  comparison.

### Tradeoff (recorded)

Two implementations that decode an input to *different* values but happen to
re-encode to the *same* bytes would be masked. Because encoding is deterministic
from the value, this only happens when the differing values are
encode-equivalent — i.e. they differ only in something the wire cannot represent
(e.g. `-0.0` vs `+0.0`, both omitted as default). Those are semantically equal on
the wire and are non-findings, so the masking is benign. Genuinely different
decoded values encode differently and are caught.

Float/NaN note: CORELIB_PLAN §6.5 makes bit-exact decode→re-encode of a signaling
NaN a **MUST**, at both the scalar `fp32` and the array-element position, for every
implementation including a double-only target (Python, TypeScript) — a widened
double destroys the sNaN payload the instant it passes through, so a double-only
port **MUST** provide a raw-wire-bytes path rather than round-tripping the widened
value. This is not a tolerable per-language limit; a NaN-payload mismatch is a
§6.5 violation, and this oracle's own decode→re-encode→hex form (above) would
surface it as an `accept_value` divergence like any other wrong re-encode. It is
`scripts/materialize.sh`'s corpus, `corpus/structured` (`f32_snan`,
`arr_fp32_nan_bits`), not this oracle's default sweep, that actually exercises the
sNaN vectors — `run.sh` does not read `corpus/structured` at all, so a defect here
is invisible to the round-trip gate purely because the vector never reaches it, not
because the comparison is structurally blind. `materialize.sh` additionally checks
the decoded **value** against a schema-driven reference (not just driver-vs-driver
agreement), which is what actually caught this class (docs/TODO.md, DONE
2026-08-02) and is a standing blocking gate.

`encode` failing after a successful decode has its own verdict, `E <class>` — see
"The fifth verdict `E`". It used to be reported as a reject class, on the reasoning
that with a worst-case buffer it could not happen; generator#656 made it happen on
purpose, for a value past a declared bound, and a decode-reject verdict is the wrong
place to put it.
