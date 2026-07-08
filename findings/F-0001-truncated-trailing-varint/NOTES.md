# F-0001 — a truncated trailing varint: Go rejects, C/Rust accept

**Status:** open — pending spec decision (PLAN §8)
**Found:** Phase 1 (C + Go); refined through Phase 2 (all 12 drivers)
**Axis:** verdict (hard, per `oracle/policy.yaml`)

## The split — two camps (7 accept, 5 reject)

| impl | verdict on `80` / `ff ff ff` |
|---|---|
| `corelib-c-cpp` | `A u=0 i=0 f=00000000 s=` (accept, all defaults) |
| `corelib-cpp` | `A …` (accept) |
| `corelib-c-cpp` (C++ wrapper) | `A …` (accept) |
| `corelib-rs` (std) | `A …` (accept) |
| `corelib-rs-no-std` | `A …` (accept) |
| `corelib-java` | `A …` (accept) |
| `corelib-cs` | `A …` (accept) |
| `corelib-go` | **`R invalid_msg`** (reject) |
| `corelib-py` (Cython) | **`R invalid_msg`** (reject) |
| `corelib-py` (pure) | **`R invalid_msg`** (reject) |
| `corelib-ts` | **`R invalid_msg`** (reject) |
| `corelib-zig` | **`R invalid_msg`** (reject) |

Note: the camps do **not** split along systems-vs-managed lines — Zig (systems)
rejects while C/C++/Rust (systems) accept, and Java/C# (managed) accept while
Go/Python/TS (managed) reject. It is a per-decoder-design difference.

The C/C++/Rust/Java/C# camp tolerates an incomplete trailing field-header varint and returns the all-defaults message (corelib-cpp does so by design — its `feed`
buffers "an incomplete trailing field … into the accumulator for the next
feed()" and returns `None`). **Four independent lineages — Go, Python, TypeScript, and Zig — reject it.** This
is no longer a lone outlier: four unrelated implementations agreeing on *reject*
is strong evidence the lenient camp is wrong. The wire is an incomplete varint (continuation bit set, no terminating
byte). Reproduce:

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0001-truncated-trailing-varint/06_dangling_varint.bin | ./drivers/c/build/driver
# -> A u=0 ...   (Go's driver -> R invalid_msg)
```

## Analysis

The C/C++/Rust/Java/C# camp tolerates an incomplete trailing varint: the bytes
leave the decoder mid-varint, no complete field was consumed, and `feed` returns OK —
yielding the all-defaults message (corelib-cpp does this deliberately, buffering
the tail for a future `feed`). Go's cursor, Python's decoder (raising `SofaDecodeError`), TypeScript's `Cursor`
(throwing `SofabError`), and Zig's istream (returning `error.InvalidMessage`) all
treat trailing bytes that cannot form a complete field as an invalid message.

This is **not** a driver artifact (verified by hand against all twelve drivers;
the Rust/C++ verdicts come from the corelib's real `feed` `Result`, not the
infallible generated `decode` — see docs/SOFABGEN.md G-0001/G-0005) and **not**
the empty-input precondition (handled separately; see ARCHITECTURE). It is a real
leniency difference on truncated input. The 7-vs-5 **two-camp** split (rather than
a lone outlier) is stronger evidence for resolving PLAN §8: four independent
lineages reject, so "reject truncated input" is the better-supported reading.

## Resolution path

This is the canonical case behind PLAN §8: is decoding of truncated input
**specified** (one correct verdict → one of the two corelibs has a bug) or
**undefined** (both legal → record in `policy.yaml` as allowed)? The finding
stays open until `documentation/MESSAGE_SPEC.md` rules. Whichever way it goes,
this reproducer becomes either a corelib bug fix or a `policy.yaml` allow-entry.

## Implementation

Resolved in MESSAGE_SPEC §7 (three-state feed COMPLETE/INCOMPLETE/INVALID + finish; a valid message is consumed exactly). Family-wide implementation tracked in [generator#86](https://github.com/sofa-buffers/generator/issues/86): the lenient corelibs (c-cpp, cpp, rs, rs-no-std, java, cs) add the INCOMPLETE state + a finish that rejects a truncated tail; the strict corelibs (go, py, ts, zig) already reject truncated and align the feed/finish API. Crucible verifies (truncated seeds → F-0001 green).
