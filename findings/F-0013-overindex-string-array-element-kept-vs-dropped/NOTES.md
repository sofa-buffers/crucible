# F-0013 — a string_array element at an index ≥ the schema count: dropped (fixed-capacity) vs kept (heap), plus an unbounded-allocation DoS

**Status:** open — **not yet filed upstream.** Codegen weakness **G-0013**
(`docs/SOFABGEN.md`). Target repo: `sofa-buffers/generator` (sofabgen), all heap
backends.
**Found:** 2026-07-16, while building `corpus/regression/` — constructing a *clean*
isolate for the resolved F-0008 (an over-capacity element index without F-0008's
truncation) surfaced a divergence that the contaminated original could not show.
**Axis:** `accept_value` (round-trip) **+ resource exhaustion** (memory-amplification
DoS).
**Affects:** every **heap** profile — `go`, `rust-std`, `cpp`, `py-cython`, `py-pure`,
`java`, `typescript`, `csharp`, `zig` (9 of 12). The **fixed-capacity** profiles (`c`,
`cpp-c-cpp`, `rust-nostd`) are correct.

## Reproduce

`overindex_clean.bin` — **7 bytes**: `c6 0c c2 07 0a 78 07`

```sh
python3 -c "import struct,sys;d=open(sys.argv[1],'rb').read();sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0013-overindex-string-array-element-kept-vs-dropped/overindex_clean.bin \
  | drivers/cpp/build/cpp/driver
```

Wire decode (`header = (id<<3)|wire_type`):
- `c6 0c` → varint `1606` → wire_type `6` (SEQUENCE_START), field id `200` = `string_array`.
- `c2 07` → varint `962` → wire_type `2` (FIXLEN), field id `120` — **element index 120**.
- `0a` → fixlen word `(1<<3)|2` → a 1-byte STRING payload; `78` = `"x"`.
- `07` → SEQUENCE_END.

`string_array` is `type: array, items: {type: string, count: 5, maxlen: 64}`, so element
index 120 is **at/beyond the schema count of 5**. The message is **complete and
well-formed otherwise** — deliberately, so it isolates the over-index axis alone and does
*not* also trip the open INVALID-vs-INCOMPLETE precedence spec-hole
([documentation#15](https://github.com/sofa-buffers/documentation/issues/15)) the way
F-0008's kept originals do.

## The split — every driver ACCEPTS, the value differs (3 vs 9)

| behavior | canonical re-encode | drivers | memory model |
|---|---|---|---|
| **drop** the element | `A 5607a606560707c60c07` (empty string_array) | `c`, `cpp-c-cpp`, `rust-nostd` | fixed capacity |
| **keep** it at index 120 | `A 5607a606560707c60cc2070a7807` | `go`, `rust-std`, `cpp`, `py-cython`, `py-pure`, `java`, `typescript`, `csharp`, `zig` | heap |

Nobody rejects, so this is invisible to any accept-vs-reject oracle — it is exactly the
"all accept, decode to different values" **semantic divergence** class PLAN §5 says the
structured track exists to catch. The split is **not** language-idiomatic drift: it falls
out of the **memory model**, cleanly, the same axis as F-0010.

## Root cause — codegen: the heap backends never enforce the schema `count`

The fixed-capacity backends bound the fill by the container's capacity; the heap backends
emit an **unbounded container** and an **unbounded fill loop**, so the schema's `count: 5`
is not enforced anywhere on the decode path.

**C++ — the two profiles, side by side.** The guard in `_FixedStrSeq` is exactly what
[generator#126](https://github.com/sofa-buffers/generator/issues/126) added to fix
F-0008's hang (`drivers/cpp/gen/c-cpp/probe.hpp` vs `drivers/cpp/gen/cpp/probe.hpp`):

```cpp
// c-cpp (fixed): bounded by capacity — drops an over-index element  ← the #126 fix
if (static_cast<std::size_t>(id) >= out->capacity()) return;
while (out->size() <= static_cast<std::size_t>(id)) out->emplace_back();

// cpp (heap): no guard — grows to id+1 and keeps the element
while (out.size() <= static_cast<std::size_t>(id)) out.emplace_back();
out[id] = std::move(_s);
```

**Rust — the same shape, and the container type shows the cause** (`message.rs`):

```rust
// rust-std:   pub string_array: Vec<String>,                              // unbounded
(_Loc::Root_string_array, _) => { while self.m.string_array.len() <= id as usize { self.m.string_array.push(Default::default()); } self.m.string_array[id as usize] = _s; }

// rust-nostd: pub string_array: heapless::Vec<heapless::String<64>, 5>,   // count: 5 honored → drops
```

So `count: 5` reaches the fixed-capacity backends (as a capacity) and is **dropped on the
floor** by the heap backends. The identical `_BlobSeq` fill in the C++ heap profile has the
same unguarded shape, so index-keyed **blob** arrays are almost certainly affected too —
untested here only because `schema/probe.sofab.yaml` has no blob array.

## Memory-amplification DoS (the half of F-0008 that was never fixed)

Because the fill materializes `id+1` elements and `id` is an unbounded **varint**, a tiny
input forces an arbitrarily large allocation. `overindex_amplify.bin` — **9 bytes**,
identical shape with index 2,000,000 (`c6 0c 82 c8 d0 07 0a 78 07`):

| driver | camp | peak RSS |
|---|---|---|
| `c` | drop | 8.6 MB |
| `cpp-c-cpp` | drop | 9.5 MB |
| `rust-nostd` | drop | 7.4 MB |
| `zig` | keep | 35.6 MB |
| `rust-std` | keep | 49.2 MB |
| `go` | keep | 121.9 MB |
| `cpp` | keep | **226.0 MB** |

~25 million× amplification on `cpp` from 9 bytes, against a schema that declares **5**
elements. The index is a varint up to 2⁶⁴, so an attacker simply raises it until OOM —
this is a denial-of-service on untrusted input, not just an interop wart.

> Measure with the driver **unconstrained** (`/usr/bin/time -f '%M'`). Capping with
> `ulimit -v` does not work here: the sanitizer builds reserve a large shadow mapping, so
> ASan fails to initialize and the run dies for an unrelated reason.

**F-0008's own NOTES predicted this** — "The heap profile (`cpp`, `std::vector`) grows and
terminates (**or OOMs for a huge id**)" — and `docs/SOFABGEN.md`'s G-0011 row repeats it
("heap `std::vector` grows/terminates"). The hang was treated as the whole bug, so
generator#126 bounded only the fixed-capacity profile. That fix is what made the two
profiles disagree on the *value*: before it, both were wrong (one spun, one over-allocated);
after it, the fixed profile is right and the heap profile is now the lone outlier.

The `_FixedStrSeq` comment #126 added asserts a parity that does not hold:

> "Drop the element instead … mirroring how an unhandled field / over-capacity native-array
> element is dropped (MESSAGE_SPEC S5.1). Two open sequences at EOF then surface INCOMPLETE,
> **matching the heap profile / C / Go / Rust**."

True for the **liveness/verdict** claim (all return `I` on F-0008's truncated input); false
for the **value** — the heap profile keeps the element. The comment reads as though the
heap profile were the reference; it is the outlier.

## Which camp is right?

The **drop** camp, on the current spec:

- **MESSAGE_SPEC §5.1** — excess array elements are dropped; this is the rule the C/Zig
  native-array fills and the #126 fixed-capacity guard already implement.
- **Family precedent** — the union suite (`scripts/run-union.sh`) established that an
  **unknown member id** is skipped by all 12; an out-of-range element index is the same
  shape of "an id the schema does not define".
- **F-0003** settled that an over-**count** scalar array is `INVALID` — the count-prefixed
  analogue. It is worth asking upstream whether an over-**index** element should likewise be
  `R` rather than a silent drop; §5.1's "drop" and §3's "reject" pull in different
  directions here, so the *verdict* may be a genuine spec hole even though the *value*
  question is not.

Either way the heap backends are wrong: they neither drop nor reject — they keep, and
allocate unboundedly to do it.

## Fix direction (G-0013)

Bound the index-keyed fill by the schema `count` in **every** backend, not just where the
container happens to be fixed-capacity — i.e. give the heap fill the guard `#126` gave the
fixed one:

```cpp
if (static_cast<std::size_t>(id) >= 5 /* schema count */) return;   // then fill as today
```

The schema count is already known at generation time (it is what produces
`InlineVector<..., 5>` / `heapless::Vec<_, 5>`); the heap backends simply don't emit it.
Same guard for `_BlobSeq` and each heap backend's equivalent (go/py/java/ts/cs/zig/rust-std).
Should the spec instead say `INVALID`, the guard becomes a reject — but the allocation must
be bounded either way, since that is the DoS.

## Gate status

`overindex_clean.bin` is **kept out of** `corpus/regression/` (it diverges by design until
G-0013 lands). The two files here are generated by
`engine/structured/isolates.py` from the reference encoder, so they cannot silently desync
from the wire format. Once fixed, promote `overindex_clean.bin` into
`corpus/regression/` as `F0013_overindex_clean.bin`.
