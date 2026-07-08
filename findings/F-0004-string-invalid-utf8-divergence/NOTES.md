# F-0004 — invalid UTF-8 in a string: three different behaviors

**Status:** open — pending spec decision (PLAN §8; UTF-8 policy)
**Found:** Phase 3, C-pacemaker → differential loop (one of a cluster of
string-handling divergences the pacemaker surfaced)
**Axis:** verdict + accept_value (hard)

## The three camps

For a `string` field whose wire bytes are **not valid UTF-8**, the family does
three different things:

| camp | impls | behavior |
|---|---|---|
| **preserve raw** | `corelib-c-cpp` (C + C++ wrapper), `corelib-cpp` | accept; keep the raw bytes verbatim (re-encode reproduces them) |
| **lossy replace** | `corelib-java`, `corelib-cs` | accept; decode via UTF-8 with replacement → the string becomes U+FFFD (`ef bf bd`) per bad sequence, and re-encode emits those |
| **reject** | `corelib-go`, `corelib-ts`, `corelib-zig`, `corelib-py` | reject the whole message (`R invalid_msg`) |

Reproducer `invalid_utf8.bin` (a nested-struct string with `ff…` bytes):

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0004-string-invalid-utf8-divergence/invalid_utf8.bin | drivers/c/build/driver
#   c   -> A ...ff...        (raw bytes kept)
#   java-> A ...efbfbd...    (U+FFFD replacement)
#   go  -> R invalid_msg     (rejected)
```

## Why it matters

This is the most consequential kind of interop bug: **the same bytes mean three
different things**. A C producer that round-trips a raw-byte "string" will have
its value silently mangled by a Java/C# consumer and outright rejected by a
Go/TS/Zig/Python consumer. No implementation crashes — they just disagree.

It generalizes docs/SOFABGEN.md G-0002 (which noted the *std vs no_std Rust*
invalid-UTF-8 divergence): the whole family disagrees, in three ways.

## Resolution path

A `MESSAGE_SPEC.md` decision (PLAN §8), and the highest-value one Crucible has
forced so far. Options: (a) strings are UTF-8 and invalid UTF-8 is a decode error
→ everyone rejects (Go/TS/Zig/Python camp is right); (b) strings are opaque byte
sequences → everyone preserves raw (C/C++ camp is right). The lossy-replace camp
(Java/C#) is defensible for neither — silent corruption. Whichever the spec
chooses, this reproducer becomes a conformance fix for the other two camps.

## Note

This is one representative of a **cluster** of string/verdict divergences the
pacemaker found on its first run (2 crashes + ~1330 raw divergence rows over 309
discovered inputs, most tracing to this UTF-8 split, the F-0001 truncated-input
split, and F-0003). Clustering the full pacemaker output into distinct root
causes is ongoing Phase-3 work; F-0004 captures the dominant string class.
