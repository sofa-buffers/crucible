# G-0045 — the sofabgen C++ backend applies the element-index bound of a nested array before the §7.3 wire-type skip

**Status:** 🔴 **OPEN** — found 2026-10-01 by the first nightly with the union steps (run 36829015200); not yet filed upstream.
**Guard:** none — open; `sweep_union_deep` carries the vectors, and the reproducers in this folder become `corpus/regression/G0045_*` once the generator fix lands.
**Issue:** not filed yet (generator, awaiting approval)

**Found 2026-10-01** by clustering the union corpus of nightly 36829015200: camp 2, 49 inputs,
the four C++ drivers reject, the other 13 accept or report INCOMPLETE.

## The rule

MESSAGE_SPEC §7.3: a field whose wire type contradicts the declared type MUST be skipped, not
reported `INVALID`. *"Against a schema bound, this clause wins."* The subtype is decided first,
the bound only applies to a field that survives it. This is the ordering F-0041 fixed in two
corelibs; here it is broken in generated code.

## The split (`schema/probe-union-deep.sofab.yaml`, field 8 `grid`, array of arrays, outer count 2)

| input | meaning | 4 C++ drivers | other 13 |
|---|---|---|---|
| `r0_grid_mistyped_overindex.bin` `46 31 30 07` | `grid{ element 6 = signed scalar }` | **`R invalid_msg`** | accept (field skipped) |
| `ctl0_grid_mistyped_inrange.bin` `46 01 30 07` | same, element index 0 | accept | accept |
| `ctl1_grid_welltyped_overindex.bin` `46 16 07 07` | `grid{ element 2 = empty sequence }` | reject | reject (§7 bound, right) |
| `ctl2_list_mistyped_overindex.bin` `26 2e 30 07` | the same shape at `list` (one level, cap 3) | accept | accept |

Each rule alone is unanimous (ctl0, ctl1); the one-level array is correct everywhere (ctl2) —
only the combination at the **nested** array splits the C++ family.

## Attribution: generated code

The bound is a schema fact, so only generated code could apply it — and it applies it too early.
`drivers/cpp/gen/<variant>/probe.hpp`, `grid` (case 8) emits a bespoke
`struct _S0 : sofab::IStreamMessage` whose `deserialize` begins with

```cpp
if (cap >= 0 && static_cast<std::size_t>(_id) >= static_cast<std::size_t>(cap)) { is.invalidate(); return; }
```

(`cpp-fixed` / `c-cpp` use `out->capacity()` instead of `cap = 2`). That runs on the element
header, before the wire type is known, and the bespoke struct never publishes `elemWire`.
The one-level `list` instead uses corelib `sofab::MessageSeq<…>` (`_r0.cap = 3`), which
publishes `elemWire` to the stream (§7.3), so the mistyped element is skipped first. Same
language, same corelib, two emitted shapes: the generator, not the corelib.

The corelib is correct — it was handed a cap and used it. Sibling profiles: `cpp` and
`cpp-c-cpp` fail alike (shared generated shape), and `c`, `go`, `rust`, `dart`, `py-pure`, `zig`
skip correctly.

## Fix direction

Emit `MessageSeq` (or publish `elemWire`) for the element level of an array of arrays, so the
wire-type check precedes the bound.
