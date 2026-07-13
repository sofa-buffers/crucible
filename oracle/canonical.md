# Canonical form (v2 — round-trip re-encoding, three-valued verdict)

Every driver decodes an input and prints **exactly one line** describing the
result. The comparator (`oracle/comparator.py`) diffs these lines byte-for-byte
across implementations, so the form must be unambiguous and identical regardless
of language and message shape.

## Grammar

```
line       := accept | incomplete | reject
accept     := "A" SP hex          ; COMPLETE — hex of the re-encoded sparse-canonical wire
incomplete := "I" [ SP hex ]      ; INCOMPLETE — decode ended mid-message; optional hex = re-encode of the partial value
reject     := "R" SP class        ; INVALID
class      := "invalid_msg" | "argument" | "usage" | "buffer_full" | "other"
hex        := *( HEXDIG HEXDIG )  ; lowercase, two digits per byte; empty allowed
```

A trailing `\n` terminates every line. No other output goes to stdout (logs →
stderr).

## The three verdicts (MESSAGE_SPEC §7)

Decoding is three-valued and finish-less — a decoder reports exactly one of
`COMPLETE` / `INCOMPLETE` / `INVALID`, and the driver maps that to the line's
first character:

| corelib outcome | line | meaning |
|---|---|---|
| `COMPLETE` | `A <hex>` | consumed bytes end exactly at a field boundary; a valid message |
| `INCOMPLETE` | `I` (or `I <hex>`) | bytes end **inside** a field/varint or an open sequence — valid so far, not a complete message. **Not an error** (§7); the caller owns end-of-input |
| `INVALID` | `R <class>` | malformed regardless of what follows (unknown wire-type, varint > 64 bits, count/length over max, `MAX_DEPTH`, stray sequence-end) |

`A` / `I` / `R` are **three distinct hard verdict values**: two implementations
disagreeing on which one applies is a `verdict` divergence (a finding). A driver
**MUST NOT** collapse `INCOMPLETE` into either neighbour — reporting `A` for a
truncated message (accept-as-done) or `R` (reject-as-malformed) is itself the bug
this axis exists to catch (see F-0001).

### The `I` payload

`I` may stand alone, or carry the hex of the **partial** value decoded before the
stream ran out (same decode→encode→hex pipeline as `A`, over whatever complete
fields arrived). Emitting it is encouraged — it catches an impl that consumed a
different prefix before hitting truncation — but the payload comparison
(`incomplete_value` axis) is **soft** in Phase 2: partial-value materialization is
not yet aligned across languages. The verdict itself (`I` vs `A`/`R`) is always
hard.

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

Float/NaN note: a decoder that materializes fp32 through a 64-bit double (Python,
TypeScript) may not preserve a NaN *payload* across decode→re-encode; this is a
known per-language limit, harmless for current seeds.

## Reject classes

Coarse taxonomy so the comparator can tell "rejected for the same reason" from
"rejected differently". Phase 2: the class comparison is **soft** (a mismatch is a
warning, not a failure — see `policy.yaml`); the verdict (which of `A`/`I`/`R`)
is always **hard**. `encode` failing after a successful decode (it should not,
given a worst-case buffer) is reported as a reject class too.
