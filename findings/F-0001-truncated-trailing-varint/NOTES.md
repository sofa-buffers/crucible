# F-0001 — a truncated trailing varint: Go rejects, C/Rust accept

**Status:** open — pending spec decision (PLAN §8)
**Found:** Phase 1, first differential run (C + Go); refined in Phase 2 (+ Rust)
**Axis:** verdict (hard, per `oracle/policy.yaml`)

## The split (3 accept, 1 reject)

| impl | verdict on `80` / `ff ff ff` |
|---|---|
| `corelib-go` | **`R invalid_msg`** (reject) |
| `corelib-c-cpp` | `A u=0 i=0 f=00000000 s=` (accept, all defaults) |
| `corelib-rs` (std) | `A …` (accept) |
| `corelib-rs-no-std` | `A …` (accept) |

Three of four corelibs tolerate an incomplete trailing field-header varint and
return the all-defaults message; **Go alone rejects it**. So the question is
sharpened: is Go too strict, or are the other three too lenient? The wire is an
incomplete varint (continuation bit set, no terminating byte). Reproduce:

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0001-truncated-trailing-varint/06_dangling_varint.bin | ./drivers/c/build/driver
# -> A u=0 ...   (Go's driver -> R invalid_msg)
```

## Analysis

`corelib-c-cpp`, `corelib-rs`, and `corelib-rs-no-std` tolerate an incomplete
trailing varint: the bytes leave the decoder mid-varint, no complete field was
consumed, and `feed` returns OK — yielding the all-defaults message.
`corelib-go`'s cursor treats trailing bytes that cannot form a complete field as
an invalid message.

This is **not** a driver artifact (verified by hand against all four corelibs;
the Rust verdict comes from `IStream::feed`'s real `Result`, not the infallible
generated `decode` — see docs/SOFABGEN.md G-0001) and **not** the empty-input
precondition (handled separately; see ARCHITECTURE). It is a real leniency
difference on truncated input, and the 3-vs-1 split makes the majority lenient.

## Resolution path

This is the canonical case behind PLAN §8: is decoding of truncated input
**specified** (one correct verdict → one of the two corelibs has a bug) or
**undefined** (both legal → record in `policy.yaml` as allowed)? The finding
stays open until `documentation/MESSAGE_SPEC.md` rules. Whichever way it goes,
this reproducer becomes either a corelib bug fix or a `policy.yaml` allow-entry.
