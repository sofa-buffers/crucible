# F-0028 — cpp & dart accept a field id over ID_MAX on decode (skip instead of INVALID)

**Status:** 🔴 **OPEN** — [corelib-cpp#47](https://github.com/sofa-buffers/corelib-cpp/issues/47) +
[corelib-dart#14](https://github.com/sofa-buffers/corelib-dart/issues/14) (two decoders, same gap).
Found 2026-07-23 by the **WP-04 framing & ceilings sweep** (`engine/structured/sweep_framing.py`).

**Axis:** framing/ceilings (§6.2), verdict split. **Impls:** `cpp`, `dart` (2) accept vs the other **11**
reject. **Corelib, not codegen** (the id ceiling is a format constant, not a schema fact; the check
belongs in the decoder — and corelib-c-cpp already has it there).

## The split

A field id **> ID_MAX** (2³¹−1, CORELIB_PLAN §6.2:640) is malformed → `INVALID` (§6.2; canonical.md:33
lists "count/length over max"). The reproducer places field id **2³¹** (ID_MAX+1) at the root with wire
type `unsigned`, value 5.

| camp | behaviour | drivers |
|---|---|---|
| **reject** (conformant §6.2) | `R invalid_msg` | c, go, rust-std, rust-nostd, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig (11) |
| **accept** | the field is treated as an unknown id and **skipped** → `A` (re-encodes empty) | **cpp, dart (2)** |

## Reproducers

- `id_over_idmax.bin` = `80 80 80 80 40 05` (6 B) — header varint `(2³¹ << 3) | 0` = id 2³¹, wire
  `unsigned`; value `5`. **cpp/dart:** `A`; **11 others:** `R`.
- `id_at_idmax_ctl.bin` — the control: field id **ID_MAX** (2³¹−1, the largest *valid* id). Unknown to
  the schema, so **all 13 skip it → `A`**. Isolates the divergence to the id being *over* the ceiling,
  not to a large-but-valid id (the WP's "must not reject for the id" control).

```sh
CORPUS=findings/F-0028-cpp-dart-decode-id-over-idmax-accepted ./scripts/run.sh
# 2 inputs: control agrees (all 13 A); id_over_idmax diverges (cpp,dart A vs 11 R)
```

## Root cause — the decoder reads the id without the ID_MAX guard its encoder has

Both corelibs enforce `ID_MAX` on the **encode** side but not on **decode**:

| corelib | encode-side check | decode-side check | decodes id 2³¹ as |
|---|---|---|---|
| **corelib-cpp** | `putHeader`: `if (fieldId > detail::kIdMax) return Error::InvalidArgument` (`include/sofab/sofab.hpp:475`, and the typed `field()` overloads :489-584) | **none** — the decoder reads `auto fieldId = static_cast<sofab::id>(header >> 3)` (`sofab.hpp:1410`, and :1812) with no `> kIdMax` test | an unknown id → skip → `A` |
| **corelib-dart** | `encoder.dart:140`: `if (id < 0 \|\| id > idMax) …` | **none** — `decoder.dart:221`: `final id = header >>> 3;` then `switch (wireType)` with no `id > idMax` test | an unknown id → skip → `A` |
| corelib-c-cpp (rejecter, contrast) | ostream.c:147 | **`istream.c:485`: `if (id > SOFAB_ID_MAX) …`** — the decoder DOES check it | `INVALID` |

corelib-c-cpp's `istream.c:485` is the model: the check belongs in the decoder's header read, before the
id is dispatched to the skip path. Its C++ sibling `cpp-c-cpp` (same istream) rejects — which is why the
pure-C++ `corelib-cpp` (`cpp`) and `corelib-dart` (`dart`) are the only two that miss it.

## Attribution — corelib (two impls), not codegen

Per the CLAUDE.md triage: *does the fix need knowledge only the schema has?* **No.** `ID_MAX` is a
**format constant** (2³¹−1), not a schema fact; the check is pure wire mechanics (validate the header id
range on read) and every other decoder — including corelib-c-cpp in the same C++ `cpp-c-cpp` profile —
performs it. The generated code faithfully skips whatever unknown id the corelib hands it; the corelib
should never have handed it an out-of-range id. Fix: add the decode-side `id > ID_MAX → InvalidMessage`
guard both decoders' encoders already carry — corelib-cpp at the `sofab.hpp:1410`/`:1812` header read,
corelib-dart at `decoder.dart:221`. Filed:
[corelib-cpp#47](https://github.com/sofa-buffers/corelib-cpp/issues/47),
[corelib-dart#14](https://github.com/sofa-buffers/corelib-dart/issues/14).

## Regression-gate & promotion

Held out of the blocking `corpus/regression/` gate and the framing axis kept **report-only**
(`scripts/sweep.sh`) until both fixes land — the F-0025/F-0026 arc. When they land: re-bootstrap, verify
`id_over_idmax` → all 13 `R`, promote the reproducer + the `id_at_idmax_ctl` control into the gate, and
flip the framing axis's id-ceiling vectors to blocking. (`FIXLEN_MAX`, `ARRAY_MAX`, stray-end, and the
`MAX_DEPTH` split F-0029 are tracked with the same axis.)
