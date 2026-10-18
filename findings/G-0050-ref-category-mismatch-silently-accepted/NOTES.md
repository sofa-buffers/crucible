# G-0050 — a `$ref` to a def of the wrong category is accepted, and the declared field type is silently replaced

**Status:** 🔴 **OPEN** — filed as generator#776. Owner: **generator** (`internal/model`, every backend).
**Issue:** [generator#776](https://github.com/sofa-buffers/generator/issues/776) (filed 2026-10-18)
**Guard:** `schema/ref-forms/reject-{union-body-to-struct,struct-body-to-union,payload-to-union}.sofab.yaml`, checked by `scripts/check-ref-codegen.py` (XFAIL on all 11 targets while this is open; the gate fails once sofabgen refuses them, until the `known:` lines are dropped).

**Found 2026-10-18** on branch `worktree-ref-schemas-212` (family branch `main`), sofabgen
`0.0.0-20261017174557-c82ead33edeb` (generator main `c82ead33edeb`), documentation
`main@b6586b5`.

## The rule

The generator schema README (`schema/README.md:71-74` at `c82ead33edeb`) pairs each body key
with its type: an `enum`'s map or `{ $ref }`, a `bitfield`'s `bits` or `{ $ref }`, a
`struct`'s `fields:` inline or `{ $ref }`, a `union`'s `oneof:` inline or `{ $ref }`. The
`$defs` categories (`struct`, `union`, `enum`, `bitfield`) exist to say which kind a
definition is. A `type: union` field whose `oneof` points at a `$defs/struct` is a schema
error, the same as an `enum` body pointing at a struct — which sofabgen refuses (by its shape, see below).

## What sofabgen does

The schema is validated on the dereferenced tree, where a struct's field map and a union's
option map have the same shape, and the model keys the shared type on the `$ref` pointer
(`internal/model/model.go:316` `refForComposite` takes the key from `refKey`, l.441, which strips
`#/$defs/` and never compares the category with the field's `type`). The **target's** category wins and the declared `type` is dropped:

| form (`schema/ref-forms/`) | declared | generated (Go, every target alike) |
|---|---|---|
| `reject-union-body-to-struct` | `u: { type: union, oneof: { $ref: '#/$defs/struct/Vec2' } }` | `U Vec2` — a plain struct field |
| `reject-struct-body-to-union` | `s: { type: struct, fields: { $ref: '#/$defs/union/Shape' } }` | a union field |
| `reject-payload-to-union` | `payload: { $ref: '#/$defs/union/Shape' }` | the union's options become the payload's fields |

These are different wire contracts, not spellings: a struct writes every non-default member,
a union holds and writes exactly one option and is omitted at `default_id`'s default
(MESSAGE_SPEC §2, §4.2). An author who wrote `type: union` gets an encoder that writes two
"options" at once, and a decoder that keeps both.

The neighbouring mismatches are refused too (`reject-enum-body-to-struct`,
`reject-bitfield-body-to-enum`), but for their SHAPE, not their category: an enum constant is no
bitfield flag mapping ("bitfield flag must be a mapping"), a struct field no enum constant
("enum constant requires \"value\""). No category check exists; struct↔union slips through
because only those two bodies are both maps of field specs.

## Attribution: generated code

The category of a definition and the type a field declares are schema facts; the corelib
never sees either. The fix is one comparison where the model resolves a `$ref` key
(`<cat>/<Name>` against the field's `type`, and `struct` for a `payload`).

## Why no other gate sees it

Nothing on the wire is malformed: the generated code is self-consistent, only not what the
schema says, so every driver built from such a schema would agree with every other. Only a
check on the generator's input contract sees it — `scripts/check-ref-codegen.py`
(`# expect: reject`).
