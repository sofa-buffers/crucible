# F-0044 — a child of a **skipped unknown sequence** binds into the enclosing scope


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-08-01** by minimizing cluster 3 of the 3-hour pacemaker round (corelibs
**0.10.0** + sofabgen **0.22.0**). The fuzzer's representative was 128 bytes of repeated
wrapper open/close noise; the defect is **6 bytes**.

## The isolate

`unknown_seq_with_child.bin` = `c6 01 19 d6 0c 07`

| bytes | meaning |
|---|---|
| `c6 01` | id **24**, wire type `SEQ_BEG` — id 24 is **absent from `probe`**, so the whole sequence must be skipped |
| `19 d6 0c` | id **3**, wire type signed, value 811 — a child *inside* that unknown sequence. Id 3 at **root** is `i16` |
| `07` | `SEQ_END` |

Both camps **accept** (`A`); they disagree on the decoded value:

| camp | re-encodes to | drivers |
|---|---|---|
| the unknown sequence is skipped **whole** (**correct**) | *(empty — the all-default message)* | c, cpp, cpp-c-cpp, dart, go, py-cython, py-pure, typescript (8) |
| the child **leaks into root** and binds `i16 = 811` | `19 d6 0c` | csharp, java, rust-std, rust-no-std, zig (5) |

The re-encoded bytes of the wrong camp are **byte-identical to the child header inside the
skipped sequence** — the clearest possible signature of a scope leak.

## Three controls isolate the axis exactly

| control | result | what it rules out |
|---|---|---|
| `ctl_child_alone.bin` (`19 d6 0c`) — the same child at root, no wrapper | all 13 agree | not the field: id 3 binds fine when it *is* at root |
| `ctl_unknown_seq_empty.bin` (`c6 01 07`) — the unknown sequence with no child | all 13 agree | not the skip: an empty unknown sequence is skipped correctly everywhere |
| `ctl_known_seq_with_child.bin` (`56 19 d6 0c 07`) — a **known** sequence (id 10) with the same child | all 13 agree | not the nesting: scoping works when the sequence is one the schema declares |

So it is precisely the combination *unknown sequence id* × *has a child*.

## Root cause — two codegen strategies, only one of them scopes the skip

This maps exactly onto how each backend's generated decoder is shaped.

**The wrong camp uses a flat visitor with a `cur` scope variable.** `drivers/java/build/gen/
src/main/java/message/Probe.java:464`:

```java
public void sequenceBegin(int id) {
    if (sp == stk.length) stk = java.util.Arrays.copyOf(stk, sp * 2);
    stk[sp++] = cur;
    switch (cur) {
    case 0: switch (id) {
        case 10:  cur = 1; break;
        case 100: cur = 2; break;
        case 200: m.string_array.clear(); cur = 4; break;
        case 201: m.blob_array.clear();   cur = 5; break;
        case 202: m.struct_array.clear(); cur = 6; break;
    } break;                       // <-- no default arm
    ...
    }
}
```

`cur` is pushed, but when `id` matches **no case** it is left **unchanged**. The decoder is
therefore still in the root scope while reading the unknown sequence's children, and the
next `onSigned(3, 811)` binds `m.i16`. `sequenceEnd()` pops correctly, so the damage is
confined to the subtree — but the value is already wrong.

C# is the same shape, `drivers/cs/build/Message.cs:388`, with the same missing arm:

```csharp
switch ((cur, id)) {
    case (Root, 10):  cur = Root_nested; break;
    ...                            // <-- no `default:` / `case (_, _):`
}
```

**The correct camp uses recursive descent**, where an unrecognised id is skipped as a whole
subtree and its children never reach a field dispatch at all —
`drivers/ts/build/message.ts:165`:

```ts
default: c.skip(c.wire); break;
```

That one arm is the entire difference.

## Attribution — generated code (a G-number), not the corelibs

*Does the fix need knowledge only the schema has?* **Yes.** "Id 24 is not declared at this
scope" is a schema fact; the corelib is schema-agnostic by design and faithfully reports
`sequenceBegin(24)` — it has no basis to do anything else. Per CLAUDE.md's triage table this
is `generator`, and the sibling-profile diff confirms it: the split is **by codegen strategy**
(flat visitor vs recursive descent), not by language or by corelib.

It is also the same *defect shape* as G-0025 / generator#265 (the dart backend's missing
`onStringBytes` override for a string-free scope): **a dispatch switch with no default arm**,
so an unmatched id inherits behaviour that was only ever correct for matched ids.

**The fix:** emit a dedicated "skipping" scope state. On an unmatched id in `sequenceBegin`,
set `cur` to it; every field hook returns immediately while it is active; `sequenceEnd` pops
back as it already does. Affected: **csharp, java, rust-std, rust-no-std, zig**.

## Spec basis

MESSAGE_SPEC §2 / §7.3: an unknown id is skipped, and §7.3's skip is *"exactly as a field with
an unknown id is skipped"* — a length jump over bytes that are **not interpreted**. Skipping a
sequence means skipping its subtree; binding a child of it into the parent interprets bytes
that must not be interpreted, and changes the decoded value of a message every implementation
accepts. That makes it an `accept_value` divergence — the hard axis, and the core interop bug
this harness exists to find.

## Second symptom (added 2026-08-01): the same defect flips accept/reject

Cluster 8 of the same fuzz round minimizes to **`verdict_flip_two_levels.bin`** =
`d6 17 d6 0c c6 0c` — an unknown sequence (id 378) opened, then `struct_array` (202), then
`string_array` (200), all left open.

| verdict | drivers |
|---|---|
| `I` (**correct** — everything inside the unknown sequence is skipped; the message is merely truncated) | c, cpp, cpp-c-cpp, dart, go, py-cython, py-pure, typescript (8) |
| `R invalid_msg` | csharp, java, rust-std, rust-no-std, zig (5) |

**The same five backends, and the mechanism follows directly from the cause above.** Because
`cur` is never switched to a skipping scope, the inner `202` is processed as the *real*
`struct_array`, which sets `cur` to its element scope. The next frame, id `200`, is then read
as a `struct_array` **element index** — and 200 ≥ `count: 5` trips the bound check:

```java
case 6: if (id >= 5) throw new java.io.UncheckedIOException(
            new SofabException(SofabError.INVALID_MSG,
                "Root_struct_array element: array index above schema capacity 5"));
```
(`Probe.java:478`)

Two controls isolate the depth requirement:

| control | bytes | result |
|---|---|---|
| `ctl_verdict_no_wrapper` | `d6 0c c6 0c` | all 13 agree — without the unknown wrapper the same two frames are fine |
| `ctl_verdict_one_level` | `d6 17 d6 0c` | all 13 agree — **one** level inside the unknown sequence is not enough |

So it needs two levels of nesting inside the skipped sequence: the first supplies a wrong
scope, the second is judged against it.

**Why this matters for priority:** the defect is not confined to silently corrupting a value.
It also makes a decoder **reject a message the other eight accept**, which surfaces as a hard
interop failure rather than a quiet one.

## Coverage gap this exposes

No sweep axis covers *unknown **sequence** id carrying children*. `sweep_framing.py` uses
unknown ids (50/51) only for scalar / fixlen / array wire types. Worth an axis once fixed —
see `docs/TODO.md`.

## Repro

```
CORPUS=findings/F-0044-unknown-sequence-children-bind-in-enclosing-scope ./scripts/run.sh
```

## Resolution

**Impls:** generator (**csharp, java, rust-std, rust-no-std, zig** — the flat-visitor backends; codegen) — `sequenceBegin`'s dispatch switch has **no default arm**, so an unmatched id leaves `cur` at the parent (`Probe.java:464`, `Message.cs:388`); the recursive-descent backends skip the subtree (`message.ts:165` `default: c.skip(c.wire)`) and are correct · **Axis:** accept_value

✅ **RESOLVED 2026-08-02** — generator#268 fixed and closed the same day it was filed. `sequenceBegin`'s dispatch gained the default arm; a skipped unknown sequence no longer leaks children. **Re-verified** on the post-fix family (sofabgen `0.0.0-20260802183113-4865f8515430`, corelibs @ main): all vectors converge across 13 drivers, and the verdict *direction* was checked, not just agreement. Reproducers promoted into the green `corpus/regression/` gate (117 → 160 inputs). *Original report:
