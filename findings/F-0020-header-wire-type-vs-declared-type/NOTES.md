# F-0020 — a header wire type ≠ the field's declared type: four incompatible behaviors

**Status:** **open — spec clause adopted, implementations outstanding.** MESSAGE_SPEC **§7.3**
([documentation#23](https://github.com/sofa-buffers/documentation/pull/23), merged `0894035`)
now requires a mis-typed field to be **skipped** as if its id were unknown. Non-conformant as of 2026-07-19 (after corelib-c-cpp#100):
**cpp-c-cpp / py** (reject), **cpp** (mis-decodes). **c** is ✅ conformant. Remainder is
entirely [generator#174](https://github.com/sofa-buffers/generator/issues/174). The cpp defect was already wrong under
every candidate rule and is independent of the clause.
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

## Part 2 — the semantics: decided

**MESSAGE_SPEC §7.3** ([documentation#23](https://github.com/sofa-buffers/documentation/pull/23),
merged `0894035`) adopts **skip**: a field whose header wire type is not the one its declared
type maps to (§1) — for `fixlen`, including the subtype — MUST be skipped exactly as an
unknown id is skipped, MUST NOT be reported `INVALID`, and MUST NOT be decoded into the
declared field. The clause also bounds the check to what the wire distinguishes (wire type +
fixlen subtype) and constrains the observable outcome rather than the layer, so the C
object-API's descriptor-table check stays conformant.

"Reject" was considered and rejected as the resolution, for a reason worth keeping on record:
in the visitor backends **"unknown id" and "known id, wrong type" are indistinguishable** —
both fall through the same switch — while unknown ids *must* be skipped. Telling them apart
would have required the generator to emit a per-scope **id → declared-type table** in five
backends. "Skip" reuses a path every implementation already has.

Outstanding against the clause:

| profile | today | required | where the fix goes (traced) |
|---|---|---|---|
| c | ✅ skips | — | **done** — [corelib-c-cpp#100](https://github.com/sofa-buffers/corelib-c-cpp/issues/100), commit `fd5086a` |
| cpp-c-cpp | ❌ `R usage` | skip | [generator#174](https://github.com/sofa-buffers/generator/issues/174) — **not** the corelib: this profile is generated **C++** (`case 4: is.read(u32);`, `gen/c-cpp/probe.hpp:209`) merely linked against the C corelib, so it never enters the object API that #100 fixed |
| py-cython, py-pure | `R usage` | skip | [generator#174](https://github.com/sofa-buffers/generator/issues/174) — **generator only**, see below |
| cpp | mis-decodes (`R invalid_msg` on sequences) | skip | [corelib-cpp#43](https://github.com/sofa-buffers/corelib-cpp/issues/43) (accessor, blocking) + [generator#174](https://github.com/sofa-buffers/generator/issues/174) |

### Python — generated code, and generator-only

`drivers/python/driver.py:26` maps `SofaStateError` → `usage`. corelib-py raises it from
`Decoder._take_scalar` (`decoder.py:509-512`): `if pending[1] != wtype: raise
SofaStateError("no matching scalar value for the current field")` — the same design as
corelib-cpp, where asking for a type the field does not carry is a **caller** error, not a
message error. `_take_fixlen` (`decoder.py:534-538`) does the same for the subtype.

The caller is generated code. `drivers/python/build/gen/message.py:70-115` dispatches on
`fld.id` **alone**:

```python
fld = d.next()
if fld is None or fld.type == WireType.SEQUENCE_END:   # <- fld.type IS available here
    return
if fld.id == 0:
    self.u8 = d.read_unsigned_array()                  # <- but never checked against it
```

Note line 72: the generated loop **already reads `fld.type`** to detect the sequence end. The
wire type is in hand; it is simply never compared with the declared type. So unlike the C++
case, no corelib change is needed — this is **generator-only**, and the guard has everything
it needs at the point of dispatch.

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
