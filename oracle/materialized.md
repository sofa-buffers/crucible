# Materialized value form (the element-access oracle)

A **second** canonical form, alongside the round-trip form (`canonical.md`). Where
the round-trip form emits `A <hex(encode(decode(input)))>` — the *re-encoded wire* —
this form emits `A <dump(decode(input))>`: a full walk of the **decoded in-memory
value**, every field and every array element made explicit.

## Why a second form exists

The round-trip form has a **recorded blind spot** (`canonical.md` §"Tradeoff"): two
decoders that hold *different* in-memory values but re-encode to the *same*
sparse-canonical bytes look identical. The sparse-canonical wire **elides trailing
default runs** (arrays) and **omits default fields**, so anything a decoder
mis-materializes that the encoder then normalizes away is invisible. F-0010 (the
managed camp keeping `M` elements vs filling to `N`) was exactly this class — masked
whenever the two encoders' trailing-trim heuristics agreed.

This form makes the decoded value **directly observable**: it never omits a field
and never trims an array, so a decode that produced a different value is a payload
divergence on the `accept_value` axis, whether or not the re-encoding would have hid
it. It is PLAN §7's original canonical intent ("explicit distinction … type tags …
floats as bit patterns"), resurrected as an *added* oracle — not a replacement (the
round-trip form stays the default, and remains the schema-agnostic path).

**Converged (2026-07-29).** The gate is green on the first family that carries the merged
sparse-array rewrite (corelibs 0.9.0 @ main, sofabgen 0.21.0): all 13 drivers agree with
each other *and* with the reference. The reference was already on the new rule while the
family was not — the disagreement that state produced was the point of the gate, and it
resolved on the family's side, not the reference's.

Closing it needed four Crucible-side walkers to stop reading a `count: N` array's
**capacity** as its length: `drivers/c/driver.c` (`md_array_len`, plus the sized wrapper
holder's own count), `drivers/go/driver.go`, and the generated walkers from
`drivers/{zig,dart}/materialize_gen.py`. Generated code was never the problem — every
backend hands the walker a length (C's `ARRAY_SIZED` descriptor and its companion
`*_len` member, Zig's `FixedArray(T,N).slice()`, Dart/Go/Java/… their native containers).
The form's other signals are unchanged: **wrapper-array lengths**, **element-level value
fidelity**, and regression-proofing. See `docs/ARCHITECTURE.md`.

## Wiring (reuses the comparator unchanged)

A driver emits this form **instead of** the round-trip hex when `SOFAB_MATERIALIZE=1`
is set in its environment; otherwise it emits the round-trip form as before. The
verdict prefix (`A`/`I`/`R`/`L`) and the whole protocol (`drivers/common/CONTRACT.md`)
are identical — only the `A` payload changes from wire-hex to a value dump. The
comparator (`oracle/comparator.py`) compares the `A` payload across drivers exactly as
it does the hex, on the same hard `accept_value` axis. `scripts/materialize.sh` sets
the env and runs the differential. `I`/`R`/`L` are unaffected (a materialized value
exists only for a COMPLETE decode).

## Grammar

One line per input, `\n`-terminated, produced only for a COMPLETE (`A`) decode:

```
line    := "A" SP value
value   := obj | u | s | fp32 | fp64 | text | blob | arr
obj     := "{" [ field *( ";" field ) ] "}"     ; a struct/message — fields in ASCENDING id order
field   := id ":" value                          ; id = decimal field id in this scope
u       := "u" 1*DIGIT                            ; unsigned integer, decimal
s       := "s" [ "-" ] 1*DIGIT                    ; signed integer, decimal (leading "-" if negative)
fp32    := "f" 8HEXDIG                            ; the IEEE-754 32-bit pattern, 8 lowercase hex, MSB-first
fp64    := "F" 16HEXDIG                           ; the IEEE-754 64-bit pattern, 16 lowercase hex, MSB-first
text    := "t" 1*DIGIT ":" *(2HEXDIG)            ; a UTF-8 string: byte length, then the raw bytes as hex
blob    := "b" 1*DIGIT ":" *(2HEXDIG)            ; an opaque blob: byte length, then bytes as hex
arr     := "[" [ value *( "," value ) ] "]"      ; an array — every element present in memory, in index order
```

Rules that make it byte-reproducible across 13 languages:

- **Every schema field is emitted, always**, in ascending field-id order — a field at
  its default is emitted with its default value, not omitted. (The family carries no
  presence bit, so *absent* and *present-but-default* are indistinguishable in memory;
  this form deliberately does **not** try to separate them — it dumps the materialized
  value.)
- **Arrays emit exactly the elements the value has** — `count` is a **capacity**, not a
  length (MESSAGE_SPEC §3, documentation#31), so there is **no fill-to-N** for any array
  form. A compact numeric/fp array materializes its `M` wire elements; a wrapper array
  materializes *highest present id + 1* elements, interior gaps as element defaults.
  **The length is itself the signal**, so an impl holding a different element count shows
  a different element list — which is exactly how a decoder that still pads to `N`, or an
  encoder that still trims a trailing default, becomes visible here.
- **Floats are raw bit patterns**, never a decimal or `"NaN"`/`"inf"` rendering — so
  `-0.0`, signalling/quiet NaN payloads, and every rounding are compared exactly.
  fp32 is the 32-bit pattern (a decoder that widened through a 64-bit double MUST
  repack to f32 before printing — a known fidelity caveat for Python/TypeScript, as in
  `canonical.md`).
- **Strings and blobs are `len:hex`** — the length is explicit (distinguishing a
  1-byte NUL blob `b1:00` from an empty `b0:`), and hex sidesteps every escaping and
  encoding question. A `string` is its UTF-8 bytes; a `blob` its opaque bytes.
- Integers are decimal with no padding; unsigned and signed carry distinct tags
  (`u`/`s`) so the wire subtype is visible even when the numeric value coincides.

Example — the all-defaults `probe` (schema `schema/probe.sofab.yaml`):

```
A {0:u0;1:s0;2:u0;3:s0;4:u0;5:s0;6:u0;7:s0;10:{0:f00000000;1:F0000000000000000;2:t0:;3:b0:};100:{0:[u0,u0,u0,u0,u0];1:[s0,s0,s0,s0,s0];2:[u0,u0,u0,u0,u0];3:[s0,s0,s0,s0,s0];4:[u0,u0,u0,u0,u0];5:[s0,s0,s0,s0,s0];6:[u0,u0,u0,u0,u0];7:[s0,s0,s0,s0,s0];10:{0:[f00000000,f00000000,f00000000,f00000000,f00000000];1:[F0000000000000000,F0000000000000000,F0000000000000000,F0000000000000000,F0000000000000000]}};200:[];201:[]}
```

The `engine/structured/materialize.py` reference is the ground truth; every driver's
`SOFAB_MATERIALIZE=1` output must equal it byte-for-byte on a COMPLETE decode.
