# F-0030 — c re-encodes an all-default array-of-struct as N empty struct frames (§5.1 trailing-elision not applied to sequence-form elements)

**Status:** 🔴 **OPEN** — [corelib-c-cpp#109](https://github.com/sofa-buffers/corelib-c-cpp/issues/109) (pure-C object API — the `c` driver).
Found 2026-07-23 by the **WP-05 array-of-struct integration** — the moment a `struct_array`
(`array of struct{k:u32, v:string}`, id 202, count 5) was added to `schema/probe.sofab.yaml`.

**Axis:** accept_value (round-trip). **Impls:** `c` (1) vs the other **12** (incl. `cpp-c-cpp`, the C++
object layer over the *same* corelib-c-cpp istream/ostream). **Corelib, not codegen** — the trailing-run
elision lives in `object.c`, and every other backend (including the C++ wrapper over the same corelib)
elides correctly.

## The split — an all-default fixed-count array-of-struct

MESSAGE_SPEC §5.1 (the normative "Fixed-count wrapper arrays elide the trailing default run —
sequence-form elements included" paragraph): in the trailing run `[M, N)` of a `count: N` wrapper, a
trailing all-default `struct`/`union`/nested-array element — *"which at an interior position would encode
as an empty frame"* — is **not written at all**; the decoder recovers it by the `N`-fill. An **all-default**
array-of-struct has `M = 0`, so the whole `[0, N)` run is elided → the canonical wire is the **empty
wrapper**.

Minimal reproducer: the **empty message** (`b""` — every field default).

| camp | re-encodes the `struct_array` (id 202) as | drivers |
|---|---|---|
| **empty wrapper** (canonical §5.1) | `d60c 07` — open + close, no elements | go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig, dart (12) |
| **N explicit empty struct frames** | `d60c 06 07 0e 07 16 07 1e 07 26 07 07` — five `seq[i]()` empty struct elements | **c (1)** |

(`06 07` = `seq[0]()` … `26 07` = `seq[4]()`.) Both decode to the same value (5 default structs, by the
`N`-fill), so it is an **accept_value** split — c re-encodes non-canonically.

**c elides *leaf*-element wrappers correctly.** On the same empty message the all-default `string_array`
(id 200) and `blob_array` (id 201) re-encode as `c60c07` / `ce0c07` (empty wrappers) on **all 13**,
including c. So c's object encoder *does* apply §5.1 trailing-elision — but only to `string`/`blob`
(leaf) elements, not to `struct` (sequence-form) elements. That is the bug, one composite level below the
leaf-wrapper F-0013/F-0026 family.

## Root cause — `object.c`'s "a SEQUENCE is never omitted" guard is too broad for wrapper elements

`sofab_object_encode` (`vendor/corelib-c-cpp/src/object.c:302-311`):

```c
#if !defined(SOFAB_DISABLE_SEQUENCE_SUPPORT)
        if (field->type != SOFAB_OBJECT_FIELDTYPE_SEQUENCE)   /* <-- SEQUENCE skips the default check */
#endif
        {
            if (_field_is_default(field, src, info->default_values))
                continue;   /* leaf field equal to its default -> elided */
        }
```

The guard is **correct for a standalone struct field** (§2: an all-default nested struct is *always* framed
as an empty sequence, never dropped — see the object.c:294-300 comment). But it also fires for the
**elements of a fixed-count struct-element wrapper**, where §5.1 requires the **trailing** all-default run
to be elided. Because a SEQUENCE element never reaches the `_field_is_default`/skip path, c frames every
element of the wrapper, including the trailing all-default run — emitting `N` empty struct frames instead
of the canonical empty wrapper.

The leaf-element wrappers (`string_array`/`blob_array`) work because their elements are *not* SEQUENCE
type, so the `_field_is_default` skip applies and trailing defaults are elided. The fix is to teach the
wrapper encode to apply §5.1 trailing-elision to sequence-form (struct/union/nested-array) elements too:
within a `count: N` wrapper, do not emit a trailing element whose whole sub-object is default (while
keeping the §2 "a *standalone* struct field is always framed" rule intact for non-wrapper sequences).

## Attribution — corelib-c-cpp (object.c), not codegen

Per the CLAUDE.md triage: *does the fix need knowledge only the schema has?* **No.** The trailing-elision
is a wire-canonicality rule (§5.1) the object encoder already implements for leaf wrappers; it just does not
extend it to sequence-form elements. No schema fact is missing — the descriptor already distinguishes a
wrapper element from a standalone field. `cpp-c-cpp` (the C++ `sofab::` object layer over the **same**
corelib-c-cpp `istream`/`ostream`) elides correctly, pinning it to the pure-C `object.c` path — exactly the
F-0026 diagnostic (the sized-blob `sofab_object_init` reset). This is the encode-side analogue in the same
object API. **Filed against corelib-c-cpp.**

## Reproduce

```sh
# build the 13 drivers against a schema carrying a struct_array (WP-05 branch's
# schema/probe.sofab.yaml, or the standalone probe-structarray.sofab.yaml here), then
# feed the empty message:
SCHEMA="$PWD/findings/F-0030-c-object-struct-array-trailing-default-not-elided/probe-structarray.sofab.yaml" \
  CORPUS="$PWD/findings/F-0030-c-object-struct-array-trailing-default-not-elided" \
  ./scripts/run.sh
# empty.bin: c re-encodes 5 empty struct frames; the other 12 emit the empty wrapper.
```

## Impact on WP-05

This breaks the **base round-trip** of *every* message once `struct_array` is in the main probe (every
message has an all-default `struct_array`), so the extended-probe differential is red until the fix lands.
WP-05's full six-axis + cross-encode + materialized coverage over the extended probe therefore **blocks on
this fix** (or must run `struct_array` in a separate report-only schema, the WP-01 union pattern, to keep
the main gate green). The `schema.py` composite-element (`struct_wrapper`) support is landed and reusable.
