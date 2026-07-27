# F-0036 — a trailing all-default struct element survives the re-encode in 12 of 13 (no §3/§5.1 trailing-trim for sequence-form elements)

**Family:** `poc/omit-all-default-sequences` (found 2026-07-27 by the new
`sweep_empty_frame` axis, first run after WP-05).

## The split

`trailing_empty_elem.bin` — `u8=1` + `seq[202]( elem0{k=1}, elem1() )`: the trailing
element is all-default, so the canonical fixed-count encoding trims it (§3/§5.1 —
*"the trailing run of default elements is elided even for sequence-form elements"*):

| camp | re-encode |
|---|---|
| `c` | `seq[202]( elem0{k=1} )` — trailing run trimmed (canonical) |
| the other 12 | `seq[202]( elem0{k=1}, elem1() )` — the empty frame is kept |

`alldefault_elem_only.bin` — `seq[202]( elem0() )` is the `M = 0` end of the same
rule: every element at its default → under POC §2 the whole **wrapper is omitted**
(`c` re-encodes just `0001`); the 12 keep `seq[202]( elem0() )`.
`ctl_canonical.bin` round-trips identically on all 13.

## Why the 12 are non-canonical

MESSAGE_SPEC §3/§5.1 (both main and POC): a `count: N` array's canonical wire
carries `M` = one past the last non-default element — explicitly *"even for
sequence-form elements"*. The POC §2 adds the `M = 0` consequence: the all-default
array equals the field's declared default, so the field is omitted. Decoders MUST
accept the non-canonical forms (all 13 do — the verdicts agree) and a re-encode
normalizes them (only `c` does).

## Attribution — codegen (generator), G-0021

The generated marshals loop the container and frame **every** element with the lazy
pair (`begin_sequence_lazy(i)` / `end_keep`), with no trailing-default narrowing —
in the same generated file that carefully trims compact arrays (`_trim_tail` /
`_trim_tail_float` in `drivers/python/build/gen/message.py`; the identical loop
shape appears in the dart/ts/go/… output). The corelibs are not implicated: they
emit what the loop hands them, and corelib-cpp even ships the narrowing helper for
trivially-copyable elements (*"Narrow a fixed-count array to its non-default prefix,
for encode"*, `sofab.hpp`) — it is just never reached for struct rows. `c` is
canonical because the fix for F-0030 put the recursive `_field_is_default` elision
into `sofab_object_encode` (corelib-c-cpp, POC branch).

Interaction: with F-0035 unfixed, the appending camp *also* mis-indexes the interior
cases; this finding is purely about the **trailing/M=0** normalization and is
observable in the id-honoring camp too (`cpp`, `dart` keep the trailing frame).

## Repro

```
CORPUS=findings/F-0036-trailing-default-struct-elem-not-retrimmed ./scripts/run.sh
```

Carved out of the blocking `sweep_empty_frame` axis until fixed
(`trailing_empty_elem`, `empty_frame`/`frame_only` at the 202 element position).
