# Canonical form (v0 — Phase 1)

Every driver decodes an input and prints **exactly one line** describing the
result, in this canonical form. The comparator (`oracle/comparator.py`) diffs
these lines byte-for-byte across implementations, so the form is designed to be
unambiguous and identical regardless of language. See `drivers/common/CONTRACT.md`
for the framing that carries these lines.

## Grammar

```
line    := accept | reject
accept  := "A" ( SP field )*          ; fields in ascending schema-id order
reject  := "R" SP class
field   := name "=" value
class   := "invalid_msg" | "argument" | "usage" | "buffer_full" | "other"
```

A trailing `\n` terminates every line. No other output goes to stdout (logs →
stderr).

## Value encoding (per type)

| type | encoding | rationale |
|---|---|---|
| unsigned (u8…u64) | decimal, no leading zeros | exact |
| signed (i8…i64) | decimal, leading `-` if negative | exact |
| fp32 | `%08x` of the IEEE-754 bits (lowercase, zero-padded to 8) | **bit-exact**: distinguishes `-0.0`, every NaN payload, ±inf — which decimal printing loses |
| fp64 | `%016x` of the IEEE-754 bits | as fp32 |
| string | lowercase hex of the UTF-8 bytes (empty → `s=`) | avoids escaping/whitespace ambiguity; exact bytes |
| blob | lowercase hex of the raw bytes | exact bytes |

Example accept line for the `probe` message:

```
A u=42 i=-7 f=3fc00000 s=6869
```

(`f=3fc00000` is `1.5f`; `s=6869` is `"hi"`.)

## Absent vs default vs value (v0 decision)

The C object API and the Go visitor API both **materialize decoded values into a
value type**, applying the schema default (zero) to any field the wire omits.
The SofaBuffers wire is sparse-canonical: a default-valued field is *not*
emitted, so on the wire `absent == default`. For these value-materializing
decoders the two are therefore indistinguishable *and equal*, and the canonical
form simply emits every field's value (the default when absent).

> This collapses the three-way absent/default/value distinction from PLAN §7
> into two states **for value-materializing decoders**. When a
> presence-tracking decoder joins (a driver that can tell "field was on the
> wire" from "field defaulted"), this file gains an explicit presence marker and
> the comparator learns to treat a value-materializing driver's "default" as
> compatible with a presence-tracking driver's "absent". Recorded as a Phase-1
> simplification in ARCHITECTURE.md.

## Reject classes

The class is a coarse taxonomy so the comparator can tell "rejected for the same
reason" from "rejected differently". In Phase 1 the class comparison is **soft**
(a class mismatch is a warning, not a failure — see `policy.yaml`) because the
per-language error taxonomies are not yet aligned. The verdict itself
(accept vs reject) is always **hard**.
