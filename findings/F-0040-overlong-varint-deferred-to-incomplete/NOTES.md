# F-0040 — corelib-c-cpp reports `INCOMPLETE` for a varint that is already overlong

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Issue:** [corelib-c-cpp#118](https://github.com/sofa-buffers/corelib-c-cpp/pull/118), [corelib-c-cpp#116](https://github.com/sofa-buffers/corelib-c-cpp/issues/116)

**Found 2026-07-29** in the post-bootstrap cluster triage of `corpus/interesting`
(1121 inputs) on corelibs **0.9.0 @ main** / sofabgen **0.21.0** — cluster 6, 4 inputs.

## The split (10-byte isolate)

`varint10_all_continuation.bin` = `80 80 80 80 80 80 80 80 80 80` — ten varint bytes,
**every one with the continuation flag set**, so the encoding cannot terminate before
its eleventh byte.

| camp | verdict | drivers |
|---|---|---|
| `INVALID` (**correct**) | `R invalid_msg` | cpp, csharp, dart, go, java, py-cython, py-pure, rust-std, rust-nostd, typescript, zig (11) |
| `INCOMPLETE` | `I` | **c, cpp-c-cpp** (2) |

The two are exactly the drivers built on **corelib-c-cpp** (`c` = generated C, `cpp-c-cpp`
= generated C++ over the same corelib); `cpp` — the same generated C++ over corelib-cpp —
rejects with the family, which pins the difference to the corelib and not to codegen.

Two controls isolate the axis:

| control | result | what it rules out |
|---|---|---|
| `ctl_nonminimal_10b.bin` (`80×9 00 01` — a legal, **non-minimal** 10-byte varint = 0, then a value) | all 13 `A 0001` | not the length — §4.1's accept-and-normalize of a non-minimal varint works everywhere, including at ten bytes |
| `ctl_varint11.bin` (`80×10 00` — eleven bytes) | all 13 `R invalid_msg` | not the rule — corelib-c-cpp *does* implement the overlong check; only the **boundary** differs |

So the defect is neither the rule nor the width: it is **when** the verdict is reached.

## What the spec requires

CORELIB_PLAN §4.1, **normative**:

> **The 64-bit bound (normative).** A varint encoding **exceeds the 64-bit value range**
> — the `INVALID` decode outcome (§5.2) — iff it is longer than **10 bytes**, or any of
> its payload bits would land at bit position ≥ 64. Both tests are on the *encoding*,
> not the decoded value.

After ten bytes that all set the continuation flag, the encoding is *already* determined
to be at least eleven bytes long. §5.2's precedence then settles the outcome:

> **Precedence — `INVALID` wins over `INCOMPLETE` (normative).** When the bytes consumed
> so far contain a construct that is malformed **independently of any bytes that might
> follow** … the outcome is **`INVALID`**, even if the input is *also* truncated.
> … a decoder **MUST NOT** report `INCOMPLETE` for input it has already determined to be
> malformed.

No continuation of this stream can be valid, so `INCOMPLETE` — which tells the caller
"feed me more" — is the one answer the spec rules out.

## Attribution: corelib-c-cpp, `src/istream.c`

`_varint_decode()` checks the accumulated shift **on entry, for the next byte**:

```c
const int bits = sizeof(sofab_unsigned_t) * 8;   /* 64 */

// already consumed a full value type's worth of bits => value too wide
if (ctx->varint_shift >= bits)
    return -2;                                    /* -> INVALID */
```

Feeding the isolate: bytes 0..8 raise `varint_shift` to 63; byte 9 (the tenth) passes
both guards — `63 < 64`, and its payload is `0x00`, so the `room < 7` test finds no bit
landing at ≥ 64 — leaving `varint_shift = 70` with the continuation flag set, i.e.
"need more data" (`-1` → `INCOMPLETE`). The `>= bits` guard would fire only on an
**eleventh** byte, which is why `ctl_varint11.bin` is rejected correctly.

**Fix shape:** decide on exit as well as on entry — after consuming a byte whose
continuation flag is set, `varint_shift >= bits` means the encoding can no longer
terminate within ten bytes, so return the overflow code immediately instead of asking
for more input.

## Resolution

**Impls:** corelib-c-cpp (`src/istream.c`, `_varint_decode`) — `c` + `cpp-c-cpp`; `cpp` (same generated C++ over corelib-cpp) rejects with the family, which pins it to the corelib · **Axis:** verdict

✅ **RESOLVED 2026-07-29** — [corelib-c-cpp#118](https://github.com/sofa-buffers/corelib-c-cpp/pull/118) merged, issue [#116](https://github.com/sofa-buffers/corelib-c-cpp/issues/116) closed. One added guard in `_varint_decode()`: the width test now also runs on **exit**, so a tenth byte that still sets the continuation flag is INVALID immediately instead of asking for an eleventh that can never make it valid. 17 repo CI checks green (incl. powerpc-be); `c` and `cpp-c-cpp` flip `I` → `R invalid_msg`, the other 11 unchanged. **Re-verified 2026-07-29** on corelibs @ main + sofabgen `7dfb61b`: all isolates and controls agree across the 13-driver roster, and the vectors are promoted into `corpus/regression/` (97 → 103 inputs, green). *History:* §4.1 (INVALID iff longer than 10 bytes) + §5.2 precedence (malformed *regardless of what follows*). The width guard is evaluated on **entry for the next byte**, so `varint_shift` reaches 70 and the verdict waits for an 11th byte that never comes. Controls: a legal non-minimal 10-byte varint → all 13 `A`; an 11-byte varint → all 13 `R`, so neither the rule nor the width is wrong, only the boundary. **Found 2026-07-29**, cluster 6
