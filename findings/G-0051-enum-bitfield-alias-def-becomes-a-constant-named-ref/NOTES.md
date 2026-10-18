# G-0051 — an `enum` / `bitfield` def that is only a `$ref` to another becomes a type with one constant named `$ref`

**Status:** 🔴 **OPEN** — filed as generator#777. Owner: **generator** (`internal/model`, every backend).
**Issue:** [generator#777](https://github.com/sofa-buffers/generator/issues/777) (filed 2026-10-18)
**Guard:** `schema/ref-forms/def-alias-{enum,bitfield}.sofab.yaml`, checked by `scripts/check-ref-codegen.py` (XFAIL while this is open: Go refuses its own output, the IR models the alias differently from the written-out form; the gate fails once both are fixed, until the `known:` lines are dropped). `def-alias-union.sofab.yaml` and `def-alias.sofab.yaml` (struct) are the working controls.

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

## Why no other gate sees it

No Crucible schema had an enum or bitfield alias. It cannot go into
`schema/probe-ref.sofab.yaml` while this is open: the Go driver would not build.
