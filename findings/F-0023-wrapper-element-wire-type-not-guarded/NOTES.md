# F-0023 — a mis-typed array-wrapper element is not skipped: the §7.3 guard is missing on the wrapper-element loop

**Status:** **open — generator-only.** MESSAGE_SPEC §7.3 requires a mis-typed field to be
**skipped**; §5.1 makes a wrapper element a normal field — so a mis-typed element must be
skipped too. Four backends reject or mis-accept it instead. Filed as [generator#TBD].
**Axis:** verdict (reject / mis-accept vs skip) — the conformant 7 skip; ts/py reject, cpp/
cpp-c-cpp mis-handle. **Found:** 2026-07-20 by the **wire-type sweep**
(`engine/structured/wiretype_sweep.py`) on sofabgen 0.19.3.

## Not a spec hole — §5.1 + §7.3 already compose

§5.1 (normative): *"A wrapper sequence is an **ordinary sequence**, so **every element is a
normal field with its own `(id, type)` header**."* §7.3 (normative): a field whose header wire
type — for `fixlen`, including the subtype — is not the one its declared type maps to MUST be
**skipped**. A wrapper element is a field, so a mis-typed element MUST be skipped. The 7 that
skip are conformant; the rejecters/mis-accepters are not. No new clause needed.

## The observation

A `string_array` (id 200) element (declared `string`, i.e. fixlen subtype String) receiving a
different wire type or fixlen subtype:

| reproducer | bytes | element carries |
|---|---|---|
| `strelem_recv_scalar_signed.bin` | `c6 0c 01 06 07` | a signed scalar |
| `strelem_recv_fixlen_fp32.bin` | `c6 0c 02 20 00 00 c0 3f 07` | a fixlen **fp32** (subtype mismatch) |
| `strelem_recv_fixlen_blob.bin` | `c6 0c 02 13 de ad 07` | a fixlen **blob** (subtype mismatch) |
| `strelem_recv_sequence.bin` | `c6 0c 06 07 07` | a sequence |

`c6 0c` opens `string_array`, the mis-typed element at id 0 follows, `07` closes. Conformant
result: the element is skipped, the array stays empty, all 12 agree. Actual:

| behaviour | drivers |
|---|---|
| **skip** (conformant) | c, go, csharp, java, rust-std, rust-nostd, zig (7) |
| **reject `usage`** on every mismatch | **py-cython, py-pure** |
| **reject `invalid_msg`** on every mismatch | **typescript** |
| **reject `usage`** on a fixlen-subtype mismatch | **cpp-c-cpp** |
| **mis-accept** a fixlen `blob` as the string (`…0212dead07`), reject a sequence | **cpp** |

Control `strelem_recv_correct.bin` (`c6 0c 02 0a 41 07`, element 0 = "A") decodes on all 12.

## Root cause — the §7.3 guard was applied to struct fields but not the wrapper loop

generator#174 added the per-field wire-type guard to *struct-field dispatch* (top-level,
`nested`, the `arrays` struct). It was **not** added to the *array-wrapper element loop*, which
reads each element as the declared element type with no header check.

**TypeScript** (`drivers/ts/build/message.ts`): the struct fields all carry the guard —
`case 2: if (c.wire !== WireType.ArrayUnsigned) { c.skip(c.wire); break; } …` — but the
`string_array` loop does not:

```ts
while (c.readHeader()) { … const _s = c.readString(); … arr[_id] = _s; }   // no c.wire check
```

`readString()` on a non-string element throws → `invalid_msg`.

**Python** (`drivers/python/build/gen/message.py`): the `arrays` struct loop guards each field
(`if fld.type != WireType.ARRAY_UNSIGNED: …`), but the `string_array` loop does not:

```python
while True:
    _ef0 = d.next(); …
    self.string_array[_ef0.id] = d.string()    # no _ef0.type check
```

`d.string()` on a non-string element raises `SofaStateError` → `usage`.

**cpp / cpp-c-cpp** (`_StrSeq::deserialize`, `drivers/cpp/gen/*/probe.hpp`): reads a string per
element without checking the element's wire type / fixlen subtype, so a fixlen `blob` is read
as the string (cpp) or the C istream rejects the type mismatch as `usage` (cpp-c-cpp).

The conformant 7 either skip structurally (the visitor backends have no string-element handler
for a non-string wire) or check the type (c via the object-API descriptor mask, #100).

## The fix — generator-only, mirror of generator#174 one position deeper

Emit the same §7.3 element guard in the wrapper-element loop that #174 emits for struct
fields: before reading an element as its declared type, check the element header's wire type
(and, for a `fixlen` string element, the subtype); on a mismatch **skip** the element instead
of reading it. No corelib change — the element header and its wire type are already available
at the loop (`c.wire` in TS, `fld.type` in Python, the istream's field type in C++).

Applies to **ts, py, cpp, cpp-c-cpp**. The other seven already skip.

## The pattern — a third §7.3 position the guard missed

The wire-type sweep found the §7.3 guard was added piecemeal and three positions were left
open: F-0020 fixed struct-field dispatch; **F-0022** is the array-*fill* arms (a scalar at an
array field); **F-0023** is the array-*wrapper element* loop (a mis-typed element). Each was
invisible to the earlier scalar-field-only reproducers — "axis green" was isolate green. This
is the argument for the sweep as a standing suite.

## Reproducing

```sh
python3 oracle/cluster.py --corpus findings/F-0023-wrapper-element-wire-type-not-guarded \
  --driver c:... --driver typescript:... [all 12]
# 5 inputs -> 4 mismatch clusters (7 skip vs ts/py reject, cpp/cpp-c-cpp mis-handle)
```

Build via `./scripts/run.sh` — never point the comparator at `drivers/*/build/` after a
limit-mode run (probe-dyn binaries mis-report a sweep as ~all divergent).
