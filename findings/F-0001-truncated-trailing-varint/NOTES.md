# F-0001 — C accepts a truncated trailing varint that Go rejects

**Status:** open — pending spec decision (PLAN §8)
**Found:** Phase 1, first differential run (8 seeds, C + Go)
**Axis:** verdict (hard, per `oracle/policy.yaml`)

## Reproducers

| file | bytes | C (`corelib-c-cpp`) | Go (`corelib-go`) |
|---|---|---|---|
| `06_dangling_varint.bin` | `80` | `A u=0 i=0 f=00000000 s=` (accept, all defaults) | `R invalid_msg` (reject) |
| `07_garbage.bin` | `ff ff ff` | `A u=0 i=0 f=00000000 s=` (accept, all defaults) | `R invalid_msg` (reject) |

Both inputs are an incomplete field-header varint (continuation bit set, no
terminating byte). Reproduce:

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0001-truncated-trailing-varint/06_dangling_varint.bin | ./drivers/c/build/driver
# -> A u=0 ...   (Go's driver -> R invalid_msg)
```

## Analysis

`corelib-c-cpp`'s streaming decoder tolerates an incomplete trailing varint: the
bytes leave it mid-varint, it has consumed no complete field, and `feed`
returns OK — yielding the all-defaults message. `corelib-go`'s cursor treats
trailing bytes that cannot form a complete field as an invalid message.

This is **not** a driver artifact (verified by hand against both corelibs) and
**not** the empty-input precondition (that is handled separately; see
ARCHITECTURE). It is a real leniency difference on truncated input.

## Resolution path

This is the canonical case behind PLAN §8: is decoding of truncated input
**specified** (one correct verdict → one of the two corelibs has a bug) or
**undefined** (both legal → record in `policy.yaml` as allowed)? The finding
stays open until `documentation/MESSAGE_SPEC.md` rules. Whichever way it goes,
this reproducer becomes either a corelib bug fix or a `policy.yaml` allow-entry.
