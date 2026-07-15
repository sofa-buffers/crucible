# F-0008 — corelib-c-cpp hangs (infinite loop / DoS) on a nested sequence inside the `string_array` field

**Status:** open — filed **[corelib-c-cpp#84](https://github.com/sofa-buffers/corelib-c-cpp/issues/84)**. A 4-byte untrusted input makes
the `cpp-c-cpp` decoder loop forever (no output, no crash — a denial-of-service).
**Found:** 2026-07-15 by the **structure-aware mutator** (engine/mutator) → the
differential loop, localized by the new comparator per-driver **timeout** (the
input hung `cpp-c-cpp`; every other driver returned in milliseconds).
**Axis:** liveness / DoS (a hang, distinct from F-0003's panic-crash).
**Affects:** `corelib-c-cpp` **only** — the C++ object-stream path
(`sofab::IStreamObject<Probe>` + generated `probe.hpp`). Its pure-C sibling driver
(`c`, same `istream.c`) and the pure-C++ corelib (`cpp`) both decode the input fine.

## Reproduce

`hang_min.bin` — **4 bytes**: `c6 0c c6 07`

```sh
python3 -c "import struct,sys;d=open(sys.argv[1],'rb').read();sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0008-cpp-c-cpp-nested-seq-in-string-array-hang/hang_min.bin \
  | timeout 3 drivers/cpp/build/c-cpp/driver ; echo "exit=$?"   # 124 = hung
```

Wire decode of `c6 0c c6 07` (two field headers, `header = (id<<3)|wire_type`):
- `c6 0c` → varint `1606` → wire_type `6` (SEQUENCE_START), field id `200` = `string_array`.
- `c6 07` → varint `966` → wire_type `6` (SEQUENCE_START), field id `120` (unknown).

i.e. **open the `string_array` field as a sequence, then open another sequence
inside it, and hit end-of-input.** `string_array` is `type: array, items: {type:
string, count: 5}` — an array of variable-length strings, which the C++ backend
decodes via `sofab_istream_read_sequence` (sofab.hpp "Decode a sequence of
variable-length string elements into a vector").

## Correct verdict (every other impl)

The bytes end with two open sequences, so per MESSAGE_SPEC §7 the outcome is
**INCOMPLETE (`I`)** — a valid-so-far, non-error partial decode. Confirmed:

```
c6 0c c6 07  →  c=I  cpp=I  go=I  rust-std=I   (all fast)   ·   cpp-c-cpp = HANG
```

Both `c` (the C object API over the very same `istream.c`) and `cpp` (the pure-C++
corelib) return `I` immediately. Only corelib-c-cpp's C++ object-stream path loops.

## Trigger condition (isolated)

Sweeping minimal variants pins the trigger to **a `SEQUENCE_START` on the
`string_array` field (id 200) followed by *any* nested `SEQUENCE_START`**:

| input | structure | cpp-c-cpp |
|---|---|---|
| `c6 0c 07` | string_array open, then **close** | ok |
| `c6 0c` | string_array open, unclosed | ok |
| `56 c6 07` | nested **struct** (id 10) + nested seq | ok |
| `c6 0c c6 07` | **string_array (id 200) + nested seq (unknown id)** | **HANG** |
| `c6 0c c6 0c` | string_array + string_array | **HANG** |
| `c6 0c 56 07` | string_array + nested struct | **HANG** |

So it is specific to the **string-array element `read_sequence` path** meeting a
nested `SEQUENCE_START` where it expects a string element (or end): the decoder
neither consumes the inner marker nor terminates on end-of-input, and spins. It is
**not** the generic nested-struct path (`56 …` = the `nested` struct is fine), and
**not** an unbalanced-sequence check in general (a lone open, or a struct+nested,
is fine).

## Localization

corelib-c-cpp's `IStreamImpl::feed` (`src/include/sofab/sofab.hpp`) delegates to the
C `sofab_istream_feed`, and the generated `probe.hpp` binds a
`sofab_istream_read_sequence` for the `string_array` string elements. The pure-C
driver (generated C visitor) and pure-C++ corelib both terminate on this input, so
the loop is in the **interaction between the generated C++ `string_array`
read-sequence handling and the C istream on a nested sequence marker** — most
likely a decode state that re-reads the same marker without advancing / without an
end-of-input guard. (No debugger in this environment; localized by differential +
the minimal-variant sweep above.)

## Why it matters

A **4-byte** untrusted message wedges the decoder forever — a denial-of-service in
any C++ consumer built on corelib-c-cpp. This is the liveness analogue of F-0003
(which was a panic-crash): the structure-aware mutator manufactured the shape and
the comparator's per-driver timeout turned an otherwise-invisible infinite loop
into a localized `[TIMEOUT]` finding.

## Fix direction (corelib-c-cpp)

In the `string_array` element read-sequence path, on encountering a nested
`SEQUENCE_START` where a string element (or the sequence end) is expected, either
skip the nested sequence or report the partial decode (INCOMPLETE at EOF / INVALID
for a type mismatch) — and ensure the decode state **always advances** so it cannot
re-read the same marker. Match the pure-C object API and pure-C++ corelib, which
both return INCOMPLETE here.
