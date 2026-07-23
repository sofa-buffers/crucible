# F-0033 — a scalar wire value exceeding its declared width splits the family 3 ways (reject / mask / keep) — spec hole

**Status:** 🔴 **OPEN (spec hole)** — **[documentation#26](https://github.com/sofa-buffers/documentation/issues/26)**. Found 2026-07-23 by the **C
pacemaker fuzzing round** (34 M execs) — the differential replay of the grown corpus surfaced it as an
`accept_value` cluster; the hand-built value corpus never carried an over-width scalar (`gen.py` only
emits in-range values).

**Axis:** accept_value (round-trip) + verdict — a **3-way** split. **Family-wide / spec**, not one impl's
bug: the spec explicitly leaves scalar value-range outside the wire-validity clauses, so no single impl is
"wrong" until a clause is adopted (the F-0010 / F-0015 arc).

## The split

A `u8` field receives a wire value **> 255** (the wire is an unsigned varint; the declared width does not
bound it — MESSAGE_SPEC §1:45: *"declared width is a **storage hint**; the wire carries a single unsigned
integer regardless"*). Reproducer `u8_over_16383.bin` = `00 ff 7f` (id 0, `u8`, value 16383):

| camp | behaviour | drivers |
|---|---|---|
| **reject** | `R invalid_msg` | c, cpp-c-cpp (2) |
| **mask to width** | value & 0xFF = **255**, re-encodes `00 ff 01` | go, rust-std, rust-nostd, cpp, csharp, zig (6) |
| **keep full value** | **16383**, re-encodes `00 ff 7f` | py-cython, py-pure, java, typescript, dart (5) |

Reproduces for every width: `u8_over_256.bin` (256 → mask 0 / keep 256), `u16_over_70000.bin`
(70000 → mask 4464 / keep 70000). The in-range control `u8_255_ctl.bin` (`00 ff 01`) is **`A` on all 13**
and round-trips identically — so the split is purely the *over-width* value, not the encoding.

## Why the spec does not resolve it (yet)

- **§1:45** — the declared width `u8`/`u16`/`u32`/`u64` is a *storage hint*; the wire carries a single
  unsigned integer **regardless of width**. So `00 ff 7f` is a well-formed unsigned field on the wire.
- **§7 (:527-529)** — *"Value-range conformance is **not a wire-type question and is outside this
  clause**."* A header carrying the unsigned wire type is well-formed for `u8`…`u64` alike.
- **§7.1 (:478-489)** — the enumerated schema-bound INVALID violations are `count`, wrapper-element id,
  and `string`/`blob` `maxlen` **only**. **Scalar over-width is absent.** So an over-width `u8` is *not* a
  mandated INVALID — which makes `c`/`cpp-c-cpp`'s reject arguably non-conformant, and leaves mask-vs-keep
  unspecified for the accepting camps.

So the format says "the wire carries the integer regardless" and "value-range is outside the wire clause",
but never says what a *narrow-storage* receiver does with a value that exceeds the hint — reject, mask, or
keep. Three defensible readings, three camps. This is a **spec hole**, the exact shape of F-0010
(under-count) and F-0015 (over-maxlen) before their clauses were adopted.

## Proposed clause (draft; the documentation issue carries it)

The most self-consistent reading of §1:45 ("the wire carries the integer regardless") is **preserve the
value**: a decoder **MUST** accept a scalar whose wire value exceeds its declared width, retain the full
value (storing it in a wide-enough accumulator — the decoder already accumulates varints into ≥64 bits,
CORELIB_PLAN §4.1), and re-encode it unchanged; it **MUST NOT** silently mask to the width (data loss) or
reject (the value is well-formed on the wire, and §7.1 does not list it). The alternative — declare
over-width **INVALID** and add it to §7.1 — is also coherent but contradicts "storage hint / carries the
integer regardless". The maintainers pick; Crucible enforces whichever lands.

## Attribution — spec hole (documentation), not a single-impl bug

Per the CLAUDE.md triage the deciding question is moot here — the divergence is *family-wide* and stems
from spec **silence**, not from one impl mis-reading a defined rule (three impls each implement a
different defensible reading). So the fix is a spec clause; filed against **`documentation`**. Once
adopted, the non-conforming camps converge (like F-0010 / F-0015). Until then the vectors stay OUT of any
green gate — the family legitimately splits.

## Reproduce

```sh
CORPUS=findings/F-0033-scalar-value-exceeds-declared-width-3way-split ./scripts/run.sh
# u8_255_ctl → all 13 A; the over-width vectors split reject / mask(→255/0/4464) / keep(→16383/256/70000).
```

## How it was found

The C libFuzzer pacemaker (34 M execs, 0 sanitizer hits) grew `corpus/interesting`; the differential
replay + `oracle/cluster.py` reduced 294 diverging inputs to 13 root-cause clusters — 12 mapped to known
classes (java `incomplete_value` soft, F-0028/F-0029, and the F-0032 §5.2 schema-bound-vs-truncation
family), and this one — an `accept_value` cluster with two distinct re-encoded values — was the new
signal. The hand-built value corpus (`gen.py`) never emits an over-width scalar, so only fuzzing reached
it.
