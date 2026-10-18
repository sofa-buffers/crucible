# G-0049 — sofabgen refuses every recursive `$ref`, though MESSAGE_SPEC §5.4 defines recursive types

**Status:** 🔴 **OPEN** — not filed upstream yet. Owner: **generator** (the schema loader, every backend); the spec is implicated (see "What a fix has to decide").
**Issue:** not filed — draft in this write-up
**Guard:** `schema/ref-forms/recursive-{tree,direct,mutual,union}.sofab.yaml`, checked by `scripts/check-ref-codegen.py` (XFAIL on all 11 targets while this is open; the gate fails once sofabgen accepts them, until the `known:` lines are dropped).

**Found 2026-10-18** on branch `worktree-ref-schemas-212` (family branch `main`), sofabgen
`0.0.0-20261017174557-c82ead33edeb` (generator main `c82ead33edeb`), documentation
`main@b6586b5`.

## The rule

MESSAGE_SPEC §5.4 ("Recursive types", l.599-623 at `b6586b5`):

> a struct may reference itself, directly or through an array element, via a `$ref` to a
> predefined `$defs` struct. This expresses trees and linked lists:
> `treenode = struct{ value: i32, children: array of <$ref treenode> }`

with three guardrails (decode bounded by `MAX_DEPTH = 255`; termination reachable through an
optional or possibly-empty field; the encoder guards a cyclic object graph with the same
budget). §6 repeats it for the schema: "recursion via `$ref` to a predefined `$defs`
struct/union". §5.4 does not name mutual recursion (A → B → A); it is read as included, since
each step is a `$ref` to a `$defs` struct. The generator's own schema README agrees:
`schema/README.md:113` (at `c82ead33edeb`) lists "recursive types" among the definition types
whose wire mapping MESSAGE_SPEC specifies, and l.73 calls `struct` "recursive".

## What sofabgen does

Every cycle is refused while `$ref`s are resolved, before any backend runs, so the result is
the same on all 11 targets:

```
error: probe.sofab.yaml: #/$defs/struct/Tree/children/items/fields: circular $ref "#/$defs/struct/Tree"
```

`internal/parser/parser.go:151` (`circular $ref %q`). Refused alike (`schema/ref-forms/`):

| form | shape |
|---|---|
| `recursive-tree` | the §5.4 treenode: `Tree.children: array of $ref Tree` |
| `recursive-direct` | a linked list: `Node.next: struct $ref Node` (terminates: `next` is omittable) |
| `recursive-mutual` | `A.bs: array of $ref B`, `B.as: array of $ref A` |
| `recursive-union` | `Expr = union{ lit: i32, add: struct $ref Pair }`, `Pair = {l, r: union $ref Expr}` |

The refusal is deliberate in the generator's design doc — `docs/ARCHITECTURE.md:242-243`
"**recursive refs are rejected** (a recursive value member has no finite size)", and l.388 —
so the generator contradicts both MESSAGE_SPEC §5.4 and its own README.
`ir.SeqDepth` already returns `ok=false` on a back-edge and `analysis.checkDepth` skips it,
so the depth code anticipates recursion; the loader never lets it get there.

## Attribution: generator (with a spec question)

Whether a type may refer to itself is a **schema** fact; the corelib never sees a type
declaration and decodes a recursive message as plain nested sequences already (the wire is
unchanged, §5.4 "On the wire this is nothing new"). Crucible's past-`MAX_DEPTH` vectors
(`engine/structured/sweep_framing.py`, `sweep_union_deep.py`) show every corelib bounds the
nesting. Only the generator refuses.

## What a fix has to decide

The generator's reason is real for part of the roster: a recursive **value** member has no
finite size, and the heap-less targets (C's fixed object model, `cpp-fixed`, `rust-nostd`,
Zig without an allocator) hold every nested struct inline. A tree needs indirection — a
pointer/`Box`/`Option<Box<…>>` or an index into a caller-provided pool — and a heap-less
target needs a bound on it (a `count` on the recursive array bounds the fan-out, not the
depth). MESSAGE_SPEC §5.4 says nothing about targets without a heap. So the outcome is either

- the generator implements recursion for the heap targets (indirection per backend; encode
  guards cycles with `MAX_DEPTH`) and refuses it with a clear message on heap-less ones, and
  MESSAGE_SPEC §5.4 / CORELIB_PLAN record that profile split; or
- MESSAGE_SPEC §5.4 and the generator README drop recursion.

Either way the README line and the spec must stop promising what the generator refuses.

## Why no other gate sees it

No Crucible schema could carry a recursive type until this was checked — the generator never
produced code for one — so the differential and materialized oracles have nothing to run.
`scripts/check-ref-codegen.py` asserts the expectation (`# expect: accept`) per target.
