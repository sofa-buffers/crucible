# F-0057 — corelib-c-cpp aborts on every zero-length array when `allow_dynamic` is on

**Status:** ✅ **RESOLVED** — [corelib-c-cpp#131](https://github.com/sofa-buffers/corelib-c-cpp/issues/131) fixed by [corelib-c-cpp#132](https://github.com/sofa-buffers/corelib-c-cpp/pull/132), merged 2026-08-04 (`assert(var != NULL || element_count == 0)` — the precondition was simply too strong; a zero-element array has no payload to write and so no destination to require).
**Guard:** corpus/regression — promoted under a descriptive name; matched by content.
**Issue:** [corelib-c-cpp#131](https://github.com/sofa-buffers/corelib-c-cpp/issues/131), [corelib-c-cpp#132](https://github.com/sofa-buffers/corelib-c-cpp/pull/132)

[`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's state; this file is the evidence.

**Found 2026-08-04**, on the **first run** of a configuration that did not exist in Crucible
until that day: `corelib: c-cpp` with `allow_dynamic: true`, added as the fourth C++ target
([crucible#129](https://github.com/sofa-buffers/crucible/issues/129), generator#289 +
corelib-c-cpp#70). It surfaced in `sweep_empty_frame` as a driver crash, not a divergence —
10 of that axis's 39 vectors abort the process.

## The reproducer

`a6 06 03 00 07` — five bytes, a message consisting of nothing but a **zero-length array**:

| bytes | meaning |
|---|---|
| `a6 06` | open `arrays` (id 100) |
| `03` | id 0, `ARRAY_UNSIGNED` — the `u8` array |
| `00` | **count = 0** |
| `07` | close the sequence |

| outcome | drivers |
|---|---|
| `A` (**correct** — a valid message; an empty array re-encodes to nothing) | c, go, rust-std, rust-nostd, cpp, cpp-fixed, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig, dart (14) |
| **abort** (`SIGABRT`) | **cpp-c-cpp-dyn** (1) |

```
driver: vendor/corelib-c-cpp/src/istream.c:1133:
        sofab_istream_read_array: Assertion `var != NULL' failed.
```

The message is not malformed and does not need to be complete: `r1` (`a6 06 03 00`, four
bytes, truncated before the sequence end) is `I` for the other fourteen and aborts the same
way. The array's element type is irrelevant — `r2` is the nested **fp32** array and aborts
through `sofab_istream_read_array_of_fp32`, and the `i16` position aborts too. What matters is
`count == 0`, nothing else.

## Why it happens — the chain is three corelib calls long

1. Generated code calls `is.readArray(u8, _count, 5)`. It passes the wire count and the schema
   bound `5` correctly; nothing here is wrong or schema-dependent.
2. `IStreamImpl::readArray` (corelib-c-cpp `sofab.hpp`) checks the wire tag, checks the count
   against the bound, and then resizes the destination:
   ```cpp
   if constexpr (requires { out.resize(wireCount); }) { out.resize(wireCount); }
   else                                               { out = C{}; }
   read(out);
   ```
   With `wireCount == 0` and a growable destination, the `std::vector` becomes **empty**.
3. `read(out)` builds `std::span<Elem> span{value}` and hands `span.data()` to the C core.
   **`std::vector::data()` on an empty vector may return `nullptr`**, and on libstdc++ it does.
4. `sofab_istream_read_array(&ctx_, nullptr, 0, sizeof(Elem), …)` hits its precondition:
   ```c
   assert(ctx != NULL);
   assert(var != NULL);      /* <- istream.c:1133 */
   assert(element_size > 0);
   ```

## Why no other configuration sees it

This is the value of running all four C++ configurations side by side: the sibling that differs
in exactly one setting is the control.

| config | destination for an array | `data()` when empty |
|---|---|---|
| `cpp-c-cpp` (`allow_dynamic:false`) | `sofab::InlineVector<T,N>` | always the inline storage — **never null** |
| `cpp-c-cpp-dyn` (`allow_dynamic:true`) | `std::vector<T>` | **null** |

So the defect is not new code — it is the pre-existing `std::vector` branch of `readArray`,
which had no caller in Crucible until the fourth configuration was added. `cpp` (the pure C++
corelib, also `std::vector`) is unaffected because it does not route through the C core's
`sofab_istream_read_array` and carries no such assertion.

## Severity: an asserts-enabled build only — but there, unconditionally

Rebuilt with `-DNDEBUG` (asserts off) and ASan+UBSan **on**, both reproducers decode correctly
and agree with the family:

```
a6060300 07      -> A          (rc 0, no sanitizer report)
0001a606030007   -> A 0001     (rc 0, no sanitizer report)
```

So there is no memory unsafety: with `target_ptr = NULL` and `target_count = 0` the decoder has
nothing to write and writes nothing. The defect is a **wrong precondition** — `var != NULL` is
asserted for a case the API is expected to handle — and its cost is that every consumer running
an asserts-enabled build dies on a valid message. That is the usual configuration for a debug
or test build, which is exactly where a decoder is fed untrusted input.

## Controls

| file | bytes | expectation | observed |
|---|---|---|---|
| `r0_zero_count_u8_array.bin` | `a6 06 03 00 07` | valid, accepted | 14 × `A`, cpp-c-cpp-dyn aborts |
| `r1_zero_count_truncated.bin` | `a6 06 03 00` | incomplete | 14 × `I`, cpp-c-cpp-dyn aborts |
| `r2_zero_count_fp32_nested.bin` | `00 01 a6 06 56 05 00 20 07 07` | valid, accepted | 14 × `A 0001`, cpp-c-cpp-dyn aborts |
| `ctl_count1_u8_array.bin` | `a6 06 03 01 05 07` | valid, accepted | **all 15 agree** — `A a60603010507` |

The `ctl` row is the one that pins it: the identical shape with **count 1** passes everywhere,
including cpp-c-cpp-dyn. Only the empty destination aborts.

## Attribution — corelib-c-cpp

The triage question (CLAUDE.md) is *does the fix need knowledge only the schema has?* It does
not. `count`, `maxlen` and the declared element type play no part: generated code handed over
the right count and the right bound, and `readArray` had already accepted both by the time it
resized. Every link in the chain — the `resize`, the `span.data()`, and the assertion that
receives the result — is corelib-c-cpp code. Under CLAUDE.md's split this is wire mechanics on
the reader side, so it is filed against **corelib-c-cpp**, not the generator.

A precedent inside the same header supports that reading: the string and blob paths already
treat zero length as a case needing care — generated code emits `b.set_len(_size); if (_size)
is.read(b);`, guarding the zero-length call at the call site. The array path has no equivalent
guard on either side, and the corelib is where it belongs, because `readArray` is the function
that produced the empty destination in the first place.

## Suggested fix

Either accept the empty case in the C core (`var == NULL` is well-defined when
`element_count == 0`, since there is nothing to write), or do not call through at all when the
resized destination is empty. The first is preferable: it fixes every current and future
growable destination at once, rather than requiring each wrapper to remember the guard.

## Effect on the Crucible gates

`cpp-c-cpp-dyn` was **quarantined** in `drivers/roster` while this was open — a crashing driver
takes the whole process down and poisons every subsequent record in the same batch, so
`sweep_empty_frame` would have been permanently red and stopped meaning "something new broke".
**Quarantine lifted 2026-08-04** with the upstream fix; the driver is back in the blocking roster
and in both streaming gates. The entry named this finding, which is what made the removal a
mechanical step rather than an archaeology exercise.
