# F-0018 — C object API truncates a `string` at an embedded U+0000

**Status:** open — surfaced 2026-07-18 while adding the F-0004 strict-UTF-8 valid
controls (issue #55). Pre-existing (not introduced by sofabgen 0.18.0); it had
simply never been exercised because no prior seed put an embedded NUL in a `string`.
**Axis:** accept_value (round-trip) — all 12 **accept**, so it is invisible to any
accept/reject oracle; a pure value split.
**Found:** cross-check of the embedded-U+0000 control in `engine/structured/utf8_seeds.py`.

## The split

Reproducer `embedded_nul.bin` = a well-formed `probe` whose only set field is
`nested.str` = the bytes `41 00 42` ("A", U+0000, "B") — **valid UTF-8** (U+0000 is
a legal scalar). Feeding it to every driver:

| behavior on re-encode | impls | wire |
|---|---|---|
| **truncate at NUL** (`str` = "A") | **c, cpp-c-cpp** | `56 12 0a 41 …` (len 1) |
| **preserve** (`str` = "A\0B") | go, rust-std, rust-nostd, cpp, py-cython, py-pure, java, typescript, csharp, zig (10) | `56 12 1a 41 00 42 …` (len 3) |

All 12 return `A` (accept). The two corelib-c-cpp-based drivers lose the embedded
NUL and everything after it; the 10 heap/managed profiles keep the full length.

## Attribution — codegen (the generated C object descriptor)

The wire carries an **explicit length** for the string, so preserving the bytes
needs no schema knowledge — this is a wire/storage mechanic, not a schema-bound
one. The generated descriptor `drivers/c/gen/probe.c` declares the field as

```c
SOFAB_OBJECT_FIELD(2, message_probe_nested_t, str, SOFAB_OBJECT_FIELDTYPE_STRING)
```

and `corelib-c-cpp/src/include/sofab/object.h` documents
`SOFAB_OBJECT_FIELDTYPE_STRING` as *"Null-terminated string."* — so the decoded
value is stored in a NUL-terminated buffer and the re-encoder measures it with the
NUL as the terminator, dropping `\0B`.

This is the **direct string analogue of F-0009** (the C object API padded/dropped a
blob because the generated descriptor used an unsized blob field; fixed by emitting
the *sized* variant, G-0012). The likely fix mirrors it: the generated code must
carry the decoded string **length** (a sized string object-field) rather than rely
on NUL termination. If the corelib exposes no sized-string object-field type yet
(only `…_FIELDTYPE_STRING` = NUL-terminated was found), the fix spans **both** the
corelib (add a sized-string field type, as it already has for blob) and the
generator (emit it) — the F-0010-style "occasionally both" case.

## Scope / severity

Data-loss on round-trip, not a crash or DoS; only bites a `string` containing an
embedded NUL (unusual but valid). Kept **out of** the green `corpus/regression/`
gate (it cannot be unanimous on value until fixed); the reproducer lives here.
**Not yet filed upstream** — attribution points at the sofabgen C backend (a
`G-00NN` in `docs/SOFABGEN.md`); confirm whether a sized-string corelib field type
exists before filing generator-only vs generator+corelib.
