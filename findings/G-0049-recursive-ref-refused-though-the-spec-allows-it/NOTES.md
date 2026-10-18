# G-0049 — sofabgen refuses every recursive `$ref`; MESSAGE_SPEC §5.4 still allows it — the spec is what changes

**Status:** ⚪ **BY DESIGN** — the generator's refusal is the intended behaviour (decided 2026-10-18: no recursive types). What is open is the spec, which still says a struct "may" reference itself: [documentation#101](https://github.com/sofa-buffers/documentation/issues/101). Owner of the remaining work: **documentation** (MESSAGE_SPEC §5.4/§6), then the generator's schema README (l.73, l.113), which repeats it. Not a generator defect.
**Issue:** [documentation#101](https://github.com/sofa-buffers/documentation/issues/101) (filed 2026-10-18)
**Guard:** `schema/ref-forms/recursive-{tree,direct,mutual,union}.sofab.yaml` (`# expect: reject circular $ref`), checked by `scripts/check-ref-codegen.py` on all 11 targets: a generator that starts accepting a `$ref` cycle fails the gate.

**Found 2026-10-18** on branch `worktree-ref-schemas-212` (family branch `main`), sofabgen
`0.0.0-20261017174557-c82ead33edeb` (generator main `c82ead33edeb`), documentation
`main@b6586b5`. First logged as a generator gap; re-classified the same day.

## What the spec says today

MESSAGE_SPEC §5.4 ("Recursive types", l.599-623 at `b6586b5`): "a struct **may** reference
itself, directly or through an array element, via a `$ref` to a predefined `$defs` struct.
This expresses trees and linked lists", with three guardrails (decode bounded by
`MAX_DEPTH = 255`; termination through an omittable field; the encoder "should" guard a cyclic
object graph). §6 (l.640) lists "recursion via `$ref` to a predefined `$defs` struct/union".
It is explicit, but a permission, not a requirement: "may", no MUST, the section is not
marked normative, and §6 calls itself a "proposed extension". The generator's schema README
repeats it (`schema/README.md:113` "recursive types", l.73).

## What sofabgen does

Every cycle is refused while `$ref`s are resolved, before any backend runs, on all 11 targets:

```
error: probe.sofab.yaml: #/$defs/struct/Tree/children/items/fields: circular $ref "#/$defs/struct/Tree"
```

`internal/parser/parser.go:151`, deliberately — `docs/ARCHITECTURE.md:242-243` "**recursive
refs are rejected** (a recursive value member has no finite size)". The four forms: the §5.4
treenode (`Tree.children: array of $ref Tree`), a linked list (`Node.next: $ref Node`), mutual
recursion (A → B → A through arrays), and an expression union (`Expr.add: $ref Pair`,
`Pair.l/r: $ref Expr`).

## Decision: no recursive types

A recursive type buys nothing on the wire (it is plain nested sequences either way) and costs:

- **Heap-less targets cannot hold it** — a recursive value member has no finite size, and C,
  `cpp-fixed`, `rust-nostd` and Zig without an allocator hold nested structs inline; §5.4 says
  nothing about them.
- **Encode can loop** on an object graph that points back to an ancestor; §5.4 only says
  "should" guard.
- **Recursion in all generated code** — defaults, equality, copy, reset, reused-destination
  decode, JSON — in 11 backends, each needing its own depth guard.

A tree stays expressible as a flat array of nodes with index references, bounded by `count`
and finite everywhere. documentation#101 proposes the wording (a `$ref` cycle is invalid, a
generator MUST refuse it) and asks to keep §5.3 "General recursion" and §6's recursive
`items` — nesting, not self-reference — clearly apart.

## Why the wire side needs nothing

Nesting depth is bounded by `MAX_DEPTH = 255` whatever the schema (CORELIB_PLAN §4.9, a
decoder MUST reject deeper). Crucible sweeps it through declared and unknown frames
(`engine/structured/sweep_framing.py`, `sweep_union_deep.py`), so a hostile stream cannot
exhaust a stack with or without recursive types.
