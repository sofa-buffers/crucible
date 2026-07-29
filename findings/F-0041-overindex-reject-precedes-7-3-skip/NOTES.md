# F-0041 — the over-index reject is applied before the §7.3 skip (c, cpp)

**Found 2026-07-29** in the post-bootstrap cluster triage of `corpus/interesting`
(1121 inputs) on corelibs **0.9.0 @ main** / sofabgen **0.21.0** — cluster 3, 11 inputs.

This is a **clause-ordering** defect: both rules involved are implemented correctly
family-wide in isolation, and only their combination splits the roster.

## The split (5-byte isolate)

`overindex_mistyped.bin` = `c6 0c 40 01 07`

```
c6 0c   sequence start, id 200            -> the `string_array` wrapper (items: string, count: 5)
  40    header (8<<3)|0 = UNSIGNED, id 8  -> element index 8, and an integer where a string is declared
  01    value varint                      -> 1
07      sequence end
```

The element header is wrong twice over: its id `8` is past the declared `count: 5`, and
its wire type contradicts the declared element type (`string` → fixlen/string).

| camp | verdict | drivers |
|---|---|---|
| skip the mistyped field, no element ever exists (**correct**) | `A` (empty) | cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, rust-std, rust-nostd, typescript, zig (11) |
| reject on the element id | `R invalid_msg` | **c, cpp** (2) |

Two controls isolate the axis exactly — each rule alone is unanimous:

| control | result | what it establishes |
|---|---|---|
| `ctl_overindex_welltyped.bin` (`c6 0c 42 0a 41 07` — id 8, correctly typed `string "A"`) | all 13 `R invalid_msg` | the §7 over-index reject is right and universally implemented |
| `ctl_inrange_mistyped.bin` (`c6 0c 10 01 07` — id 2, an integer where a string is declared) | all 13 `A` (empty) | the §7.3 skip is right and universally implemented — including in `c` and `cpp` |

So neither camp has the *rules* wrong; they disagree only on which one is evaluated
first.

## What the spec requires

MESSAGE_SPEC §7.3, **normative**, states the ordering explicitly:

> A decoder **MUST NOT** report such a field as `INVALID`, and **MUST NOT** decode its
> payload into the declared field.
> …
> **Against a schema bound, this clause wins.** … The subtype is therefore decided first
> and the schema bound applied only to a field that survives it.

A field skipped under §7.3 is "exactly as a field with an unknown id is skipped", so it
never becomes an element of the array — and an id that is not an element index cannot
violate the element-index bound of §7/§5.1. §7.4 states the same principle from the
other side: *"An occurrence skipped under §7.3 is **not** an occurrence for this clause."*

*(The §7.3 paragraph argues the ordering through the fixlen-array count word; the
sentence itself is unqualified, and this isolate is the same situation at the element
position. If the maintainers read the clause as scoped to the fixlen count, the fix
belongs in the spec instead — worth saying so on the issue rather than assuming.)*

## Attribution: two corelibs, one shape — both confirmed by the profile split

`c` and `cpp` reject; `cpp-c-cpp` does not. Since `cpp` and `cpp-c-cpp` share the
generated `probe.hpp` and differ only in the corelib, and `c` and `cpp-c-cpp` share
corelib-c-cpp and differ only in the generated code, the two rejecters have **different**
proximate causes:

**corelib-c-cpp** — `src/object.c`, the descriptor/object decode path (the one the `c`
driver uses). When no descriptor field matches the wire id, a holder rejects outright:

```c
// No descriptor field matched this id. … a fixed-count sequence holder's
// fields ARE the element slots 0..field_count-1, so an unmatched id is an
// over-index element (id >= N): reject the message per MESSAGE_SPEC §7/§7.1
if (info->fixed_seq)
    sofab_istream_invalidate(ctx);
```

No wire-type test guards it. Forty lines above, the same file already reasons the other
way for the *length*: *"an unknown id leaves nothing behind: no value, no id occupied, no
container mutation. So the ids §5.1 counts are the ids that were consumed as elements,
not the ids that merely appeared on the wire."* A mistyped element merely appeared on the
wire — the over-index path is the one place that conclusion is not applied.

**corelib-cpp** — `include/sofab/sofab.hpp`, `StringSeq::deserialize` documents the
intended order and then delegates the bound one step too early:

> `readString` decides both, in the order §5.2 needs and before the payload: the declared
> subtype (§7.3 — a mis-typed element is not this array's) and then the element maxlen
> (§7.1). **The over-index reject (§5.1) is enforced by the stream at the element header**,
> from `cap` below …

Because the stream applies `cap` **at the element header**, a mistyped over-index element
is rejected before `readString` ever gets to make the §7.3 decision the comment describes.
