# F-0009 — C object API pads a sub-`maxlen` blob to `maxlen` (and drops an all-zero blob)

> **✅ RESOLVED 2026-07-16 (sofabgen 0.17.1).** [generator#128](https://github.com/sofa-buffers/generator/issues/128)
> fixed (commit `25d5853`, sized blob descriptor — the C backend now emits `SOFAB_OBJECT_FIELD_BLOB_SIZED`
> with a length companion). Re-verified: short blobs (`[0x01]`, `[0x00]`, `[0x00 0x01]`) round-trip in `c`
> and match the family; the sub-`maxlen` vectors rejoined the green `corpus/structured/` gate.

**Status:** open — **triaged & filed [generator#128](https://github.com/sofa-buffers/generator/issues/128)**
(sofabgen C backend; codegen weakness **G-0012**). **Not** a corelib bug — the C
corelib already provides the fix primitive (`SOFAB_OBJECT_FIELD_BLOB_SIZED`); the C
backend just doesn't use it.
**Found:** 2026-07-15 by the **cross-encode / structured-value oracle**
(`scripts/cross-encode.sh`) on its first run — a divergence on a *valid* value the
malformed-wire fuzzer never reached.
**Axis:** accept_value (round-trip) — the same value re-encodes to different bytes.
**Affects:** the `c` driver (the C corelib's generated **object API**,
`message_probe_decode`/`_encode`) — **only**. Every other driver, *including the C++
wrapper `cpp-c-cpp` over the same C `istream.c`/`ostream.c`*, preserves the blob.

## The divergence

Feeding a `nested.bytes_field` (a `blob`, `maxlen: 4`) with a **sub-maxlen** value:

| blob value | `c` re-encodes to | family (go, cpp, cpp-c-cpp, rust, py, java, ts, cs, zig) |
|---|---|---|
| `[0x01]` (1 B) | `01 00 00 00` — **padded to maxlen 4** | `01` (actual length) |
| `[0x00]` (1 B) | *dropped* (empty) | `00` (preserved) |
| `[0x00,0x01]` (2 B) | `00 01 00 00` — padded | `00 01` |
| `[0xDE,0xAD,0xBE,0xEF]` (4 B, = maxlen) | `de ad be ef` — **agrees** | `de ad be ef` |

So the C object API emits a blob at its **full fixed `maxlen`** (zero-padded),
losing the real length; an all-zero sub-maxlen blob collapses to empty. Full-`maxlen`
blobs agree (padding is a no-op), which is why only sub-`maxlen` blobs diverge — and
why the malformed fuzzer, working from arbitrary wire, rarely produced a valid
short blob to catch it. Reproducers: `blob_short.bin` (`[0x01]`),
`blob_zero.bin` (`[0x00]`).

## Why it matters

Round-trip **data loss** on a valid message: a producer on the C object API cannot
faithfully carry a blob shorter than its declared `maxlen`.

## Root cause (confirmed) — sofabgen C backend

The generated C struct + descriptor for `nested.bytes_field` (`probe.h` / `probe.c`):

```c
typedef struct { double f64; char str[33]; uint8_t bytes_field[4]; float f32; } message_probe_nested_t;
SOFAB_OBJECT_FIELD(3, message_probe_nested_t, bytes_field, SOFAB_OBJECT_FIELDTYPE_BLOB)
```

`bytes_field` is a bare `uint8_t[maxlen]` with **no length member**, wired with the
**plain, fixed-full-capacity** `SOFAB_OBJECT_FIELD(..., BLOB)` descriptor. A blob is
opaque bytes (can hold `\0`), so with no length the object API can't tell how many
bytes are live → it emits the full `maxlen` (padded), and an all-zero one collapses
to empty. (`str` round-trips because it is `char[maxlen+1]` and NUL-terminated, so
the corelib recovers its length; a blob can't be NUL-recovered.)

**The corelib already offers the fix** (`object.h`): `SOFAB_OBJECT_FIELD_BLOB_SIZED`
pairs a fixed buffer with a companion length member (stored on decode), and produces
**byte-identical wire to a plain blob of the same actual length**. The C++ backend
already does the equivalent via `sofab::FixedBytes<N>` + `os.write(id, data,
size())`. So it is a **pure codegen issue**, not a corelib one — the C backend must
emit `{ uintX bytes_field_len; uint8_t bytes_field[N]; }` and use the sized
descriptor. **Filed [generator#128](https://github.com/sofa-buffers/generator/issues/128)** (G-0012).

## Harness note

The green cross-encode gate (`corpus/structured/`) uses only full-`maxlen` blobs so
it stays a clean regression gate; the sub-`maxlen` reproducers live here as the
finding, mirroring how open findings are kept out of the green seed gate.
