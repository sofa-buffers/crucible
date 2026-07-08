# F-0002 — corelib-c-cpp encoder: left shift of a negative value (UB)

**Status:** open — corelib bug (fix upstream in corelib-c-cpp)
**Found:** Phase 3, first run after switching the canonical form to round-trip
re-encoding (which exercises the *encoder*, under the C driver's UBSan build)
**Axis:** memory-safety / UB (sanitizer, not a differential divergence)

## What

`src/ostream.c` `_zigzag_encode` shifts a **signed** value left:

```c
static inline sofab_unsigned_t _zigzag_encode (sofab_signed_t v) {
    const int bits = sizeof(v) * 8;
    return ((sofab_unsigned_t)(v << 1)) ^ (sofab_unsigned_t)(v >> (bits - 1));
    //                         ^^^^^^  UB: left shift of a negative value
}
```

For any negative signed field value, `v << 1` is undefined behavior in C (C11
§6.5.7/4: left shift with a negative left operand is UB). UBSan reports:

```
src/ostream.c:39:34: runtime error: left shift of negative value -7
```

(The companion `v >> (bits - 1)` is an arithmetic right shift of a negative
value — implementation-defined, not flagged here but also non-portable.)

## Reproducer

`i_negative.bin` (2 bytes: `09 0d`) decodes to `{ i = -7 }`; re-encoding it in the
round-trip driver triggers the UB. Any message with a negative signed field
(i8/i16/i32/i64 < 0) triggers it.

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0002-encoder-negative-left-shift-ub/i_negative.bin | ./drivers/c/build/driver
# stderr: ostream.c:39:34: runtime error: left shift of negative value -7
# stdout: A 090d   (the wire is still correct, so the differential loop stays green)
```

## Why it was not caught before

corelib-c-cpp's own in-tree fuzzer exercises only the **decoder** (`istream`).
Crucible's round-trip canonical form (`decode -> re-encode -> hex`,
oracle/canonical.md) exercises the **encoder** on every accepted input, under the
C driver's `-fsanitize=undefined` build — so the encoder UB surfaced immediately.
This is the sanitizer "second net" (PLAN §9) doing its job on a path a
decode-only fuzzer never reaches.

## Impact & fix

Not a wire divergence: two's-complement makes the result correct in practice, so
all drivers still agree (the loop is green). But it is real UB — undefined by the
C standard and a portability/compiler-hardening risk. Fix in corelib-c-cpp: cast
to unsigned *before* shifting, e.g.

```c
return (((sofab_unsigned_t)v) << 1) ^ (sofab_unsigned_t)(v >> (bits - 1));
```

and consider an unsigned/logical form for the sign-replication term too.

## Loop handling

The C replay driver runs UBSan **non-halting** (default), so a negative-signed
input logs to stderr but the driver still emits its canonical line and the
differential loop completes. The coverage pacemaker (libFuzzer build) would halt
on this — which is the correct behavior there, and is how continuous fuzzing will
re-surface it until fixed.
