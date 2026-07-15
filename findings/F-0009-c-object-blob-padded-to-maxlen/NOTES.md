# F-0009 — C object API pads a sub-`maxlen` blob to `maxlen` (and drops an all-zero blob)

**Status:** 🔎 **candidate — needs triage before filing** (the F-0008 lesson:
trace decode-vs-encode and codegen-vs-corelib before choosing a repo).
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
faithfully carry a blob shorter than its declared `maxlen`. The C++ wrapper over the
*same* C corelib gets it right, so it is not the C `ostream` — it points at the
generated C **object struct/encode** (likely a fixed `uint8_t[maxlen]` whose real
length is not tracked/emitted), i.e. a **sofabgen C-backend** codegen issue rather
than a corelib one. To confirm before filing:

1. **decode vs encode** — does the C decoder store the real length (inspect the
   decoded `message_probe_t.nested.bytes_field` length) or is the loss purely in
   encode?
2. **codegen vs corelib** — is `bytes_field` generated as a fixed array without a
   companion length, or does the C `ostream` blob path ignore a tracked length?
3. **strings too?** — `string` (`str`, `maxlen: 32`) is the sibling fixed-storage
   type; check whether a sub-maxlen string round-trips (it appears to — strings are
   NUL-relevant — but verify).

Then file against **generator** (if codegen) or **corelib-c-cpp** (if the C ostream),
with the exact code location — do **not** file on the differential symptom alone.

## Harness note

The green cross-encode gate (`corpus/structured/`) uses only full-`maxlen` blobs so
it stays a clean regression gate; the sub-`maxlen` reproducers live here as the
finding, mirroring how open findings are kept out of the green seed gate.
