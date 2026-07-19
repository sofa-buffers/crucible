# F-0019 — a repeated sequence (struct) field id: 11 profiles merge, TypeScript replaces

**Status:** **open — spec hole first, codegen second.** Do **not** file against the TypeScript
backend yet: if the spec closes the hole with "reject", all 12 are wrong, not one.
**Axis:** accept_value (round-trip) — all 12 **accept**; the re-encoded value differs. Invisible
to any accept/reject oracle.
**Found:** 2026-07-19, by the 24 h pacemaker round (11.4 G execs); surfaced as the dominant
`accept_value` class in the post-fuzz stage-C differential, then delta-debugged from a
1456-byte fuzzer input down to 20 bytes.

## The observation

`dup_seq_nested.bin` (20 B) opens the `nested` struct (field id 10) **twice** in the same
scope — a blob (`bytes_field`, id 3) in the first occurrence, an fp64 (`f64`, id 1) in the
second:

```
56 1a 23 deadbeef 07   56 0a 41 0000000000000440 07
│  │  │             │  │  │  └ fixlen_word: len 8, subtype 1 (fp64)
│  │  │             │  │  └ header: id 1, type 2 (fixlen)  -> nested.f64
│  │  │             │  └ header: id 10, type 6 (SEQ START) -> nested, AGAIN
│  │  │             └ SEQ END
│  │  └ fixlen_word: len 4, subtype 3 (blob) + payload
│  └ header: id 3, type 2 (fixlen) -> nested.bytes_field
└ header: id 10, type 6 (SEQ START) -> nested
```

All 12 **accept**. On re-encode:

| behavior | drivers | re-encoded |
|---|---|---|
| **merge** both occurrences | c, cpp, cpp-c-cpp, csharp, go, java, py-cython, py-pure, rust-std, rust-nostd, zig (11) | `560a4100000000000004401a23deadbeef07a606560707c60c07` — `nested{f64, blob}` |
| **replace** (first occurrence lost) | **typescript** (1) | `560a41000000000000044007a606560707c60c07` — `nested{f64}` |

`dup_seq_arrays.bin` (12 B) shows the same split for a second struct (`arrays`, id 100):
`5607a6060301410c0142560707c60c07` (11) vs `5607a6060c0142560707c60c07` (ts).

### Scope — it is specific to sequences with differing children

Three controls, **all 12 agree** on each:

| control | bytes | why it matters |
|---|---|---|
| `control_dup_scalar.bin` | `00 05 00 07` | a repeated **scalar** (u8, id 0) — uniform last-wins |
| `control_dup_same_field.bin` | `a606 030141 07 a606 030142 07` | the **same** child in both occurrences — uniform last-wins |
| `control_single_seq.bin` | `56 0a41 …0440 1a23 deadbeef 07` | both children in **one** sequence — the merged form, uniform |

So the divergence needs a *sequence* opened more than once with *different* children. Only
then does replace-vs-merge become observable.

## Attribution — generated code, not the corelib

The corelib only reports sequence-start/-end events; the decision to reuse or replace the
sub-object is made entirely by generated code. Comparing the three backends for the same
field id 10:

| backend | generated decode | effect |
|---|---|---|
| C++ (`drivers/cpp/gen/cpp/probe.hpp:301`) | `is.read(nested);` | decodes **into** the existing member → merge |
| Go (`drivers/go/message/probe.go:97`) | `case 10: return &m.Nested, nil` | visitor onto the existing member → merge |
| **TypeScript** (`drivers/ts/build/message.ts:351`) | `o.nested = ProbeNested.decodeFrom(c);` | builds a **fresh** object and assigns → earlier children lost |

corelib-ts is not implicated: it delivers both sequences faithfully. Per CLAUDE.md's triage
this is a **codegen** question (`generator` / sofabgen TypeScript backend) — *if* merge turns
out to be the required behavior. See below.

## Why this is a spec hole first

CORELIB_PLAN §3 (Core Concepts, "ID"):

> IDs **must be unique within a single sequence/scope** but may repeat in different scopes.

MESSAGE_SPEC §5 reinforces the intent: it explains that arrays are carried by a **wrapper
sequence** rather than by repeating one field id, because only the wrapper can represent an
explicitly empty array. Repeating an id is therefore not a form this format uses at all.

So both reproducers are **invalid encodings** by §3. But neither document says what a
**decoder** must do when it receives one. There is no clause on:

- reject as `INVALID` (§7), or
- accept and merge (what 11 profiles do), or
- accept and replace (what the TS backend does).

Consequently there is **no spec basis for an `oracle/policy.yaml` entry** — and CLAUDE.md is
explicit that "a policy entry with no spec basis is a spec hole to file upstream, not a silent
exception". The reproducers therefore stay **out** of the green `corpus/regression/` gate until
the hole is closed.

## Proposed order (the F-0015 pattern)

F-0015 closed in one day precisely because the clause landed *before* the codegen change, so
every backend implemented a defined rule instead of a guess. Same order here:

1. **Spec proposal** to `documentation`: define decoder behavior for a duplicate field id
   within one scope. The most consistent resolution is **reject as `INVALID`** — §3 already
   declares the encoding illegal, and §7 already requires generated code to enforce
   schema-bound violations it can detect. That also makes merge-vs-replace moot.
2. **Then** the codegen issue against `generator`, with the adopted clause as its basis.

Step 1 is **filed as [documentation#23](https://github.com/sofa-buffers/documentation/pull/23)**
(MESSAGE_SPEC §7.3 + §7.4, together with F-0020). Step 2 — the codegen issue against
`generator` — waits on that clause being adopted.

## Reproducing

```sh
python3 oracle/cluster.py --corpus findings/F-0019-duplicate-sequence-id-fields-lost \
  --driver c:drivers/c/build/driver --driver typescript:drivers/ts/build/driver   # …all 12
# 5 inputs: 3 agree, 2 diverge -> 1 cluster (11 merge vs typescript replace)
```

Build the drivers via `./scripts/run.sh` first — never point the comparator at
`drivers/*/build/` directly after a limit-mode run, which leaves `probe-dyn` binaries there.
