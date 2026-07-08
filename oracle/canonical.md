# Canonical form (v1 — round-trip re-encoding)

Every driver decodes an input and prints **exactly one line** describing the
result. The comparator (`oracle/comparator.py`) diffs these lines byte-for-byte
across implementations, so the form must be unambiguous and identical regardless
of language and message shape.

## Grammar

```
line    := accept | reject
accept  := "A" SP hex            ; hex of the re-encoded sparse-canonical wire
reject  := "R" SP class
class   := "invalid_msg" | "argument" | "usage" | "buffer_full" | "other"
hex     := *( HEXDIG HEXDIG )    ; lowercase, two digits per byte; empty allowed
```

A trailing `\n` terminates every line. No other output goes to stdout (logs →
stderr).

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
warning, not a failure — see `policy.yaml`); the verdict (accept vs reject) is
always **hard**. `encode` failing after a successful decode (it should not, given
a worst-case buffer) is reported as a reject class too.
