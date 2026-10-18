# G-0051 — an `enum` / `bitfield` def that is only a `$ref` to another becomes a type with one constant named `$ref`

**Status:** ✅ **RESOLVED** — fixed upstream in [generator#781](https://github.com/sofa-buffers/generator/pull/781) (merged 2026-10-18, `61bf3f04`, "fix(model): a $defs enum or bitfield written as a $ref is an alias"). An enum or bitfield alias def now carries the constants of the def it names, and with them its width. Owner: **generator** (`internal/model`, every backend), not a corelib.
**Issue:** [generator#777](https://github.com/sofa-buffers/generator/issues/777) (filed 2026-10-18, closed 2026-10-18)
**Guard:** `schema/ref-forms/def-alias-{enum,bitfield}.sofab.yaml`, checked by `scripts/check-ref-codegen.py` (the alias must model alike to the written-out form, on all 11 targets); and `schema/probe-ref.sofab.yaml` fields `ea` (id 33) and `fa` (id 34) with the `q_*` vectors of `engine/structured/sweep_ref.py`, run by `scripts/run-ref.sh` (`BIG = 1000` and flag pos 9 accepted, past i16 / u16 refused, the same under the alias and written out).

**Found 2026-10-18** by the review of crucible#212's tests, on branch `worktree-ref-schemas-212`
(family branch `main`), sofabgen `0.0.0-20261017174557-c82ead33edeb` (generator main
`c82ead33edeb`), documentation `main@b6586b5`.

## The rule

A `$defs` entry may be a `$ref` to another definition of its category (an alias); the
generator resolves every `$ref` before validating (generator `schema/README.md` §"Dereference,
then validate — but emit with `$ref` intact") and a struct alias works. An `enum` is bounded by
the smallest signed type holding **every declared constant** and a `bitfield` by the smallest
unsigned type holding its highest declared `pos` (MESSAGE_SPEC §1, l.48 and the bitfield
paragraph, at `b6586b5`). An alias declares the constants of the def it names.

## What sofabgen does

```yaml
$defs:
  enum:
    Hue:  { R: 0, G: 1, BIG: 1000 }
    HueA: { $ref: '#/$defs/enum/Hue' }
messages:
  probe:
    payload:
      c: { id: 1, type: enum, enum: { $ref: '#/$defs/enum/HueA' }, default: 1 }
```

- `--dump-ir`: `HueA` has `consts: [{name: "$ref", value: 0}]` — one constant, named `$ref`.
- Go refuses its own output: `go backend: generated sofab_types.go is not valid Go (a generator
  bug): 15:7: illegal character U+0024 '$'` — even when the alias is unused, since Go emits
  every `$defs` type.
- TypeScript, Java, Kotlin, C#, Dart and C++ generate `$ref = 0` without complaint. The field
  takes the width of that one constant, i8: TypeScript checks `if (_v < -128 || _v > 127) throw
  … InvalidMsg`. So `BIG = 1000`, a declared constant, is **INVALID** through `HueA` and valid
  through `Hue` or written out.
- The bitfield alias the same way: one flag named `$ref`; a declared `pos: 9` (width u16)
  shrinks to u8.

## Attribution: generated code

`internal/model/model.go:147` and `:151` (at `c82ead33edeb`) build a `$defs` enum / bitfield
with `b.buildEnum(name, key, group[name])` / `b.buildBitfield(…)` from the raw definition map,
which for an alias holds the single key `$ref`. A struct or union def goes through
`b.buildFields`, which follows the `$ref`, which is why their aliases work. Validation passes
because it runs on the dereferenced tree. Which constants a type declares is a schema fact; the
corelib never sees it.

## Why no other gate saw it

No Crucible schema had an enum or bitfield alias. It could not go into
`schema/probe-ref.sofab.yaml` while this was open: the Go driver would not build.

## Resolution (verified 2026-10-18)

Verified with the sofabgen build of generator main `61bf3f04` (`0.0.0-20261018151733-61bf3f049efa`,
the `sofabgen-linux-amd64` artifact of generator CI run 39139819425, checksum verified), every
corelib at its main tip:

- **Generated code.** `scripts/check-ref-codegen.py` reported `FIXED?` for both forms: every
  target generates them (Go included) and the IR models the alias like the written-out def. The
  residuals that remain in `results/ref-codegen-baseline.txt` are the shared def's own
  declaration — e.g. C++ `enum ModeA : std::uint16_t { ModeA_R = 1, ModeA_W = 2, ModeA_Hi = 512 }`
  in `sofab-defs.hpp`, where the broken build had `enum ModeA : std::uint8_t { ModeA_$ref = 1 }`
  and the field `std::uint8_t f = 0` instead of `std::uint16_t f = 2`. The `# known: G-0051`
  lines are dropped; the gate reads 683 cells, 0 failing.
- **Wire.** The alias went into `schema/probe-ref.sofab.yaml` as `ea` (enum `WideHueA` →
  `WideHue { R: 0, G: 1, BIG: 1000 }`, default 1) and `fa` (bitfield `WideModeA` → `WideMode`
  with flag `hi` at pos 9), written out in `probe-ref-inline.sofab.yaml`. Thirteen `q_*` vectors
  test them: `BIG = 1000`, ±32767/−32768 and `hi = 512`, `65535` accepted and round-tripped; 32768,
  −32769 and 65536 refused; each default omitted. `scripts/run-ref.sh` over 367 vectors × 20
  drivers: 0 divergences and 0 conformance failures under each build, 0 answers and 0
  materialized values that differ between the alias and the written-out build, chunk and encode
  invariance 0 mismatches.
