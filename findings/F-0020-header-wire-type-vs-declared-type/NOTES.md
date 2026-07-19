# F-0020 — a header wire type ≠ the field's declared type: four incompatible behaviors

**Status:** **open.** Two separable parts — a C++ mis-decode that is wrong under *every*
candidate rule (report now), and a family-wide semantics question that needs a spec clause
first (do not touch five backends before it is decided).
**Axis:** verdict (hard: accept vs reject) **+ accept_value** (silent mis-decode).
**Found:** 2026-07-19, while checking whether repeated fields with differing types were
covered by any existing test (they were not). The repetition framing turned out to be a red
herring — the control showed a *single* mis-typed field already diverges.

## The measurement

`sweep.py` enumerates every top-level field id × every wire type — 66 vectors:

| | vectors | result |
|---|---|---|
| wire type **matches** the declared type | 11 | **all 12 drivers agree** |
| wire type **differs** | 55 | **all 55 diverge** |

The 11 agreeing vectors are exactly `f000_t0` (u8→unsigned), `f001_t1` (i8→signed), …,
`f010_t6` / `f100_t6` / `f200_t6` (the three sequence fields). **100 % of the mismatch space
is divergent** — there is no partial coverage to build on.

Running the pair sweep (`sweep.py <dir> pairs`, the same id twice with differing types)
gives 330 vectors, 330 divergent, 9 clusters — but that is dominated by this same
single-field effect, not by repetition. Repetition-with-*matching*-types is F-0019.

## Four incompatible behaviors

The representative reproducers in this directory (5 mismatches + 2 controls → 4 clusters):

| reproducer | bytes | behavior |
|---|---|---|
| `A_u8_as_signed.bin` | `01 06` | 7 skip · c/cpp-c-cpp/py `R usage` · **cpp accepts `u8 = 6`** |
| `B_u8_as_array_unsigned.bin` | `03 01 05` | **6 accept `u8 = 5`** (element taken as the scalar) · go/ts skip · 4 `R usage` |
| `C_struct_as_scalar.bin` | `50 05` | 9 skip · c/cpp-c-cpp `R usage` · **cpp `R invalid_msg`** |
| `D_arrays_as_signed.bin` | `a1 06 06` | 10 skip · c/cpp-c-cpp `R usage` |
| `E_stringarray_as_fixlen.bin` | `c2 0c 0a 41` | (in cluster 1 with `C`) |
| `control_u8_correct.bin` | `00 05` | all 12 agree |
| `control_struct_correct.bin` | `56 07` | all 12 agree |

So the family answers the same question in four ways: **skip the field**, **reject as
`usage`**, **reject as `invalid_msg`**, or **decode it anyway** — the last one silently, with
a wrong value.

`A_u8_as_signed.bin` is the sharpest: `01 06` is field id 0 (declared `u8`, wire type
Unsigned) carrying wire type **Signed**, zig-zag payload `06` = 3. `cpp` re-encodes
`u8 = 6` — the *raw* varint, un-zig-zagged. No error, no reject; a wrong value delivered as
if correct.

## Where each behavior is decided

| profile | mechanism | decided in |
|---|---|---|
| go, rust, java, csharp, zig | typed visitor callbacks (`fn unsigned` / `fn signed`, matched on `(scope, id)`) — a mis-typed field lands in a callback whose switch lacks the id | generated code, *structurally* |
| typescript | `if (c.wire !== WireType.X) { c.skip(c.wire); break; }` (`message.ts:345-356`) | generated code, *explicitly* — this is the F-0017 / G-0014 fix from 0.18.0 |
| c, cpp-c-cpp | `sofab_object_field_cb` matches on **id alone** and hands the istream the *descriptor's* type (`object.c:396-410`); the istream then rejects the mismatch | **corelib** (informed by the generated descriptor) |
| **cpp** | `case 4: is.read(u32);` (`probe.hpp:288-300`) — dispatch on **id alone, no wire-type check** | generated code — **the defect** |

## Part 1 — the C++ guard (report now, independent of the spec)

corelib-cpp documents the contract explicitly (`sofab.hpp:1619`):

> Call from inside a deliver callback. **The requested type must match the field's wire type.**

The generated C++ code violates that precondition. `read<T>` for an integral `T` just pulls a
varint and applies zig-zag *based on `T`'s signedness*, never on the wire type
(`sofab.hpp:1631-1640`) — hence `u8 = 6`. The corelib is correct: it states the precondition
and faithfully does what it is told. Per CLAUDE.md's triage, **the caller is the bug**.

This is **G-0014 in the C++ backend, unfixed** — [generator#161](https://github.com/sofa-buffers/generator/pull/161)
(0.18.0, "frame each decoded field by header wire type") only touched the TypeScript backend.

**It is not a generator-only fix.** The generated type derives from `sofab::IStreamMessage`,
but `deserialize(sofab::IStreamImpl &is, sofab::id id, std::size_t, std::size_t)` receives the
stream as a *separate object*, and its `type_` member is `protected` (`sofab.hpp:1074`) with
no public accessor — so generated code cannot query the wire type today. Two parts:

1. **corelib-cpp** — expose the current field's wire type publicly (the analogue of the TS
   cursor's `c.wire`), or pass it into `deserialize`, whose signature already carries
   `size`/`count`;
2. **generator (C++ backend)** — emit the guard using it.

Same shape as F-0010, which needed corelib-c-cpp#87 alongside its codegen fix.

## Part 2 — the semantics (spec first, then codegen)

Nothing normative says what a decoder must do when the header wire type contradicts the
schema. MESSAGE_SPEC §7 requires generated code to enforce schema-bound violations it can
detect, but never names this case. Consequences of each candidate rule:

| rule | who changes | cost |
|---|---|---|
| **skip** (what 7–9 already do) | c, cpp-c-cpp, py must stop rejecting | for the C family this is **corelib** (`object.c`), not generator |
| **reject** | the 7 skipping backends | expensive — see below |

The "reject" branch is the expensive one and the reason not to guess: in the visitor
backends, **"unknown id" and "known id, wrong type" are indistinguishable** — both fall
through the same switch. Unknown fields *must* be skipped (§5.2 skip path), so telling the
two apart requires the generator to emit a per-scope **id → declared-type table** and consult
it before dispatch. That is a structural change across five backends.

**Filed as [documentation#23](https://github.com/sofa-buffers/documentation/pull/23)**
(MESSAGE_SPEC §7.3 + §7.4, together with F-0019). The codegen issues wait on that clause —
except the C++ guard below, which is wrong under every candidate rule and can be filed
independently.

## Reproducing

```sh
python3 findings/F-0020-header-wire-type-vs-declared-type/sweep.py /tmp/ws single   # 66
CORPUS=/tmp/ws CLUSTER=1 ./scripts/run.sh                                            # 11 agree, 55 diverge
# the committed subset:
CORPUS=findings/F-0020-header-wire-type-vs-declared-type CLUSTER=1 ./scripts/run.sh  # 2 agree, 5 diverge
```

Build the drivers through `./scripts/run.sh` — never point the comparator at
`drivers/*/build/` directly after a limit-mode or union run, which leaves binaries generated
from a different schema there.

## Relationship to F-0017 and F-0019

- **F-0017** is this axis, seen through a single isolate (`05 00 01`). It is correctly closed
  — that vector converged to all-12-`R invalid_msg` and still does (it is in the green
  regression gate). But the **isolate converged, the axis did not**: 55 of 55 mismatches
  still diverge. Isolate-green is not axis-green.
- **F-0019** (repeated sequence id: 11 merge, ts replaces) is a *different* axis — it needs
  matching types. It should be resolved after this one, since a rule for mis-typed
  repetitions falls out of whatever is decided here.
