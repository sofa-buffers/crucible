# F-0008 — generated C++ fixed-capacity string/blob-array fill hangs (infinite loop / DoS) on an element index ≥ capacity

> **⚠️ CORRECTION 2026-07-15 — re-targeted corelib-c-cpp → generator (sofabgen).**
> The first write-up blamed the corelib-c-cpp *decode*. That was wrong: the
> corelib-c-cpp maintainer showed `sofab_istream_feed` structurally terminates and
> couldn't reproduce it in the corelib (**corelib-c-cpp#84 closed**, dispute in
> **[crucible#16](https://github.com/sofa-buffers/crucible/issues/16)**). Tracing
> into the **generated `probe.hpp`** found the real infinite loop in the C++
> codegen — filed **[generator#126](https://github.com/sofa-buffers/generator/issues/126)**
> (see Root cause). The differential *symptom* (only `cpp-c-cpp` hangs) was real;
> the attribution was one layer too shallow. Codegen-weakness log: **G-0011**.

**Status:** open — **[generator#126](https://github.com/sofa-buffers/generator/issues/126)**
(sofabgen C++ backend). A 4-byte untrusted input makes the generated fixed-capacity
string-array fill loop forever (no output, no crash — a denial-of-service).
**Found:** 2026-07-15 by the **structure-aware mutator** (engine/mutator) → the
differential loop, localized by the new comparator per-driver **timeout** (the
input hung `cpp-c-cpp`; every other driver returned in milliseconds).
**Axis:** liveness / DoS (a hang, distinct from F-0003's panic-crash).
**Affects:** the **fixed-capacity C++ profile** (the `cpp-c-cpp` driver / embedded
target). The heap C++ profile (`cpp`, `std::vector`), the pure-C object API (`c`,
same `istream.c`), Go, and Rust all decode the input fine — it is specifically the
generated `_FixedStrSeq`/`_FixedBlobSeq` fill on the corelib's fixed-capacity
`InlineVector`.

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

## Root cause (generator / sofabgen C++ backend) — confirmed

The generated element handler for a fixed-capacity string/blob array grows the
destination up to the wire element index, then writes at that index
(`drivers/cpp/gen/c-cpp/probe.hpp`, `_FixedStrSeq` / `_FixedBlobSeq`):

```cpp
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();  // id = wire element index
auto &s = (*out)[id]; ...
```

On the **fixed-capacity** profile `out` is the corelib's `InlineVector<T, N>`, whose
`emplace_back()` is a **no-op once full** (intentional — no heap growth;
`corelib-c-cpp/src/include/sofab/sofab.hpp`):

```cpp
T &emplace_back() noexcept { std::size_t i = len_ < N ? len_++ : N - 1; ... }  // len_ never exceeds N
```

So when the wire delivers an element index `id ≥ N`, `out->size()` reaches `N` and
**sticks** — `size() <= id` stays true forever → the `while` never terminates. For
`string_array` (`count: 5`) the nested `SEQUENCE_START` in `c6 0c c6 07` is element
id `120 ≥ 5`, so it spins. The **heap** profile (`cpp`, `std::vector`) grows and
terminates (or OOMs for a huge id), which is exactly why `cpp` did not hang and
`c-cpp` did. It is **not** the corelib istream (`c`, the C object API over the same
`istream.c`, terminates) and **not** the Crucible driver (a single `feed()`, no
re-feed) — it is the generated fixed-capacity fill loop.

## Why it matters

A **4-byte** untrusted message wedges the decoder forever — a denial-of-service in
any consumer of the generated **fixed-capacity C++ profile** (the embedded target).
The liveness analogue of F-0003 (a panic-crash). The structure-aware mutator
manufactured the shape and the comparator's per-driver timeout turned an
otherwise-invisible infinite loop into a localized `[TIMEOUT]` finding — but the
attribution took a second pass (see the correction banner): the differential
*symptom* pointed at `cpp-c-cpp`, and only tracing the generated code showed the
bug is codegen, shared by any fixed-capacity C++ target.

## Fix direction (generator#126)

Bound the fill loop by the fixed capacity `N` and drop/ignore (or reject) an element
index `≥ N`, so it cannot spin on a full `InlineVector` — e.g. `if (id < N) { while
(out->size() <= id) out->emplace_back(); (*out)[id] = …; }`. Mirrors how the C/Zig
backends drop excess native-array elements (MESSAGE_SPEC §5.1). The heap profile is
unaffected but the same guard is harmless there. (Earlier, wrong direction —
"corelib-c-cpp read-sequence must always advance" — struck: the corelib is fine.)
Reference for the intended behavior: the pure-C object API and pure-C++ corelib, which
both return INCOMPLETE here.
