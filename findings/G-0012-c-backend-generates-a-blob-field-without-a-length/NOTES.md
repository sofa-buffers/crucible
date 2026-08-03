# G-0012 — C backend generates a blob field without a length (round-trip data loss)

**Status:** ✅ **fixed in sofabgen 0.17.1** (commit `25d5853`, sized blob descriptor) —
[generator#128](https://github.com/sofa-buffers/generator/issues/128) closed
2026-07-15. Re-verified 2026-07-16: short blobs round-trip in `c`. Fix: emit
`{ uintX field_len; uint8_t field[N]; }` + `SOFAB_OBJECT_FIELD_BLOB_SIZED` — the corelib
already provided it, wire bytes unchanged.
Surfaced 2026-07-15 by the cross-encode / structured-value oracle (Crucible finding
**F-0009**). **Lang:** c · **Where:** the generator C backend, generated `probe.h`
struct + `probe.c` field descriptors.

**What:** a `blob` field (e.g. `nested.bytes_field`, `maxlen: 4`) is generated as a
bare fixed array with the plain, fixed-full-capacity descriptor:

```c
typedef struct { … char str[33]; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD(3, message_probe_nested_t, bytes_field, SOFAB_OBJECT_FIELDTYPE_BLOB)
```

There is **no length member**, and a blob is opaque bytes (can contain `\0`), so the
object API cannot tell how many bytes are live. On re-encode it emits the full
`maxlen` (zero-padded); an all-zero sub-`maxlen` blob collapses to empty. A producer
on the C object API therefore cannot faithfully carry a blob shorter than `maxlen` —
silent round-trip data loss (`[0x01]` → `01 00 00 00`; `[0x00]` → dropped). `str`
round-trips because it is `char[maxlen+1]` and NUL-terminated; a blob can't be
NUL-recovered.

**Why it matters:** ships to every consumer of the generated C object API. Not a
corelib bug — the C `ostream`/`istream` take an explicit length (the C++ wrapper
`cpp-c-cpp`, using `FixedBytes<N>`, round-trips correctly over the *same* C sources).

**Proposed fix:** the corelib already offers the sized variant. Emit a companion
length member immediately before the buffer and use it:

```c
typedef struct { … uintX bytes_field_len; uint8_t bytes_field[4]; … } message_probe_nested_t;
SOFAB_OBJECT_FIELD_BLOB_SIZED(3, message_probe_nested_t, bytes_field_len, bytes_field)
```

`SOFAB_OBJECT_FIELD_BLOB_SIZED` stores the received length on decode and "produces
byte-identical wire to a plain blob of the same actual length" (`object.h`), so the C
object API then matches the rest of the family byte-for-byte.
