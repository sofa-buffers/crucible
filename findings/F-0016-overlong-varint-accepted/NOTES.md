# F-0016 — an overlong (>64-bit) varint is accepted and silently truncated instead of rejected

**Status:** ✅ **RESOLVED** — all 7 corelib fixes landed and verified. **Re-measured 2026-07-17**
(corelibs@main): both over-64-bit vectors → **all 12 `R invalid_msg`** (baseline 8A/4R), the
2⁶⁴−1 control still `A` on all 12. All 3 vectors are in the green `corpus/regression/` gate.
Each fix added the pre-shift room check the 3 correct impls already had. *(Harness note: java
first read as still-broken — a stale `vendor/corelib-java/target/sofab.jar` from Jul 15; the
driver's skip-if-present jar build masked the corelib bump. Fixed `drivers/java/build.sh` to
rebuild when the corelib source is newer than the jar — the class of stale-cache bug that has
bitten this repo before.)*
**Found:** 2026-07-17 by the **coverage-guided fuzzer** (2nd 1 h round, sofabgen 0.17.5) —
the residual cluster 2 (TS lone `I`) minimized to this, and the general isolate exposed a
family-wide 8-vs-4 split.
**Axis:** verdict + accept_value (a malformed input is accepted *and* decodes to a wrong value).
**Attribution:** **corelib** — the varint reader is wire mechanics, not schema-dependent
(CLAUDE.md rule). Confirmed by reading each reader + a sibling diff.

## The divergence — 8 accept, 4 reject; the value is silently corrupted

A varint encodes 7 payload bits/byte. A 64-bit value takes ≤10 bytes, and **in the 10th
byte only the low 1 bit may be set** — anything above is >64-bit overflow, which
MESSAGE_SPEC/CORELIB_PLAN §4.1/§6.3 already call `INVALID` (*"an overlong (>64-bit)
varint"*).

`30 ff ff ff ff ff ff ff ff ff 02` — a `u64` field (id 6) whose varint carries the 65th bit:

| | verdict / value |
|---|---|
| **reject (4 drivers / 3 corelibs)** — `c`, `cpp-c-cpp` (corelib-c-cpp), `rust-std` (corelib-rs), `zig` | `R invalid_msg` ✅ |
| **accept (8 drivers / 7 corelibs)** — `go`, `rust-nostd`, `cpp` (corelib-cpp), `py-cython`+`py-pure`, `java`, `typescript`, `csharp` | `A` + a **truncated** value ❌ |

Two boundaries confirm it is the overflow, not the length:
- `…ff 01` (= 2⁶⁴−1, the valid max) → **all 12 accept**. Not an off-by-one.
- `…ff 02` re-encodes to `…ffff7f`, `…ff 7f` re-encodes to `…ffff01` — **different malformed
  inputs collapse to different wrong u64 values**. Silent data corruption, the exact class
  Crucible exists to catch.

## Root cause — the same shape in all 7: byte-count capped, 10th byte not overflow-checked

Each accepting reader loops `value |= (byte & 0x7f) << shift`, stops on the byte without the
continuation bit, and only rejects when `shift >= 64` — which requires an **11th** byte. On a
terminating **10th** byte `shift == 63`, so `(byte & 0x7f) << 63` drops bits 1–6 (or, in
Python, `& MASK64` narrows them) and the value is accepted.

The **3 correct rejecters** do the missing check *before* OR-ing the payload bits — reject if
they would spill past bit 63:
- corelib-c-cpp `istream.c:109-110`: `room = bits - shift; if (room < 7 && ((byte & 0x7F) >> room) != 0) → INVALID`
- corelib-rs `varint.rs:52/79`, corelib-zig `varint.zig:48/70`: `if shift+7 >= 64 && (byte & 0x7F) >> (64-shift) != 0 { InvalidMsg }`

Per-impl (verified against source):

| corelib (driver) | reader @ file:line | what's missing |
|---|---|---|
| **corelib-cpp** (`cpp`) | `getVarint` @ include/sofab/sofab.hpp:981-984 (+ `skipVarint` :1003-1005) | 10th-byte `<< 63` truncates; `shift >= 64` guard only fires on an 11th byte |
| **corelib-go** (`go`) | `(*cursor).uvarint` @ cursor.go:38-45 | `shift >= 64` checked *after* `shift += 7` → catches the 11th byte only |
| **corelib-rs-no-std** (`rust-nostd`) | `VarintDecoder::push` @ src/varint.rs:57 | comment says *"matches the C reference"* but drops the bits; the real corelib-rs has the check |
| **corelib-py** (`py-cython`, `py-pure`) | `Decoder._varint` @ src/sofab/decoder.py:169-174 (+ `_varint.py`, native `_speedups.pyx`) | `& MASK64` on return silently narrows instead of rejecting |
| **corelib-ts** (`typescript`) | `readVarint` @ src/decode/fast.ts:353-356 (verbatim copy in cursor.ts) | `(b & 0x7f) << 31` is a 32-bit JS shift → bits fall off top; only continuation bit throws |
| **corelib-java** (`java`) | fast path @ IStream.java:236-241 + `varintPush` :672-686 (+ mirror copies) | `while (b < 0 && shift < VALUE_BITS)`; only the continuation bit (`b < 0`) throws |
| **corelib-cs** (`csharp`) | `ReadVarint` @ src/SofaBuffers/IStream.cs:568-575 (+ `ReadVarintChecked`) | same shape as Java |

## Reproducers

- `u64_over_65bit.bin` — `30 ff ff ff ff ff ff ff ff ff 02` (65-bit)
- `u64_over_70bit.bin` — `30 ff ff ff ff ff ff ff ff ff 7f` (70-bit; different wrong value)
- `control_u64_max.bin` — `30 ff ff ff ff ff ff ff ff ff 01` (= 2⁶⁴−1, valid → all 12 `A`)

## Filed

[corelib-cpp#39](https://github.com/sofa-buffers/corelib-cpp/issues/39), [corelib-go#48](https://github.com/sofa-buffers/corelib-go/issues/48), [corelib-rs-no-std#45](https://github.com/sofa-buffers/corelib-rs-no-std/issues/45), [corelib-py#43](https://github.com/sofa-buffers/corelib-py/issues/43), [corelib-ts#53](https://github.com/sofa-buffers/corelib-ts/issues/53), [corelib-java#41](https://github.com/sofa-buffers/corelib-java/issues/41), [corelib-cs#37](https://github.com/sofa-buffers/corelib-cs/issues/37).

## Gate status

Kept out of `corpus/regression/` until the family converges (target: all 12 → `R invalid_msg`;
the control stays `A`). Promote the two over-64-bit vectors once fixed; the control can go in
now (already green).
