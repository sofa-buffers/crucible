# F-0060 — the generated TypeScript chunked decoder lets a raw `TypeError` escape where the one-shot path throws `SofabError`

**Status:** 🔴 **OPEN** — filed against the generator ([`results/FINDINGS.md`](../../results/FINDINGS.md)
owns this finding's state; this file is the evidence). Also logged as codegen defect **G-0037**.

**Found 2026-08-04**, on the **first run of the chunked axis over a fuzzed corpus**
(`corpus/interesting`, 9038 inputs). It is the reason that run was worth doing: TypeScript is
green on every hand-written corpus — seeds, conformance, the 188-input regression set, the 108
structured value vectors — and produces **12 436 mismatches** on fuzzed input.

## The reproducer

`56 12 12 ff ff 07` — six bytes, `nested.str` carrying two bytes that are not valid UTF-8:

| | whole | `SOFAB_CHUNK=1` |
|---|---|---|
| `56 12 12 61 62 07` (`"ab"`) — **control** | all 15 accept | all 15 accept |
| `56 12 12 ff ff 07` | all 15 → `R invalid_msg` | 14 → `R invalid_msg`, **typescript → `R other`** |

No truncation, no `INCOMPLETE` ambiguity, no disagreement about the *verdict* — every
implementation rejects, both ways. What differs is the **type of the exception** the chunked path
raises, and only in TypeScript.

`R other` is this driver's label for "the exception was not a `SofabError` at all". The actual
throw:

```
TypeError: The encoded data was not valid for encoding utf-8
    at TextDecoder.decode (node:internal/encoding:494:28)
    at _ProbeNestedVis.string (message.ts)
    at DecoderState.emitBytes (corelib-ts cursor)
```

## The cause — the corelib converts, the generated code does not

corelib-ts's `Cursor.readString` gets this **right**, and says why:

```ts
// take() (truncation → INCOMPLETE) runs before the decode, so a short
// payload stays INCOMPLETE; only genuinely malformed UTF-8 bytes reach the
// fatal decoder. Its TypeError becomes the INVALID outcome (§8/§6.4/§5.2).
const bytes = this.take(len);
try {
  return _utf8.decode(bytes);
} catch {
  throw invalidMsgError("invalid UTF-8 in string");
}
```

The **generated** visitor — the path the chunked decoder uses — declares its own fatal decoder and
calls it bare:

```ts
const _dec = new TextDecoder("utf-8", { fatal: true });
...
string(id: number, total: number, offset: number, chunk: Uint8Array): void {
  ...
  const p = this.a.take(total, offset, chunk);
  if (p === null) return;
  this.out[id] = _dec.decode(p);        // <-- no try/catch: the TypeError escapes
}
```

Same `TextDecoder`, same `fatal: true`, but not the conversion. So the two decode paths of one
implementation raise different exception types for the same bytes:

| path | used by | throws |
|---|---|---|
| `Cursor.readString` | one-shot `Probe.decode` | `SofabError(InvalidMsg)` |
| generated visitor | `ProbeDecoder.feed` (chunked) | **`TypeError`** |

## Why it matters

A consumer written against the documented API catches `SofabError`. This one escapes it — a
`TypeError` from `node:internal/encoding` propagates out of `feed()` past any
`catch (e) { if (e instanceof SofabError) … }`, which for a decoder being fed untrusted bytes is
the difference between a rejected message and an unhandled exception.

It also means the *same corelib* reports the same malformed input two different ways depending on
which decode entry point the caller used, which is the shape MESSAGE_SPEC §7.1 exists to prevent
between implementations — here it is inside one.

## Scope

12 436 mismatches over `corpus/interesting`, spread evenly across every chunk size (≈1780 each at
`n` = 1, 2, 3, 5, 8, 16), i.e. roughly a fifth of the corpus. That is unsurprising: the corpus is
fuzzed, so invalid UTF-8 in a string field is common, and every one of them takes this path.

## Attribution — the generator

`const _dec = new TextDecoder("utf-8", { fatal: true })` and the bare `_dec.decode(p)` are both
emitted into `message.ts`; neither is corelib code. The corelib not only handles this correctly
but carries a comment explaining the conversion, so the pattern to copy was one file away. No
schema fact is involved — this is "convert a platform exception into the API's error type", which
under CLAUDE.md's split is the emitting side's job because the emitting side is what makes the
call.

## Suggested fix

Wrap the generated `_dec.decode(...)` the way `Cursor.readString` does, or — better — have the
generated visitor call a corelib helper so there is one fatal decoder and one conversion in the
family rather than two decoders and one conversion. The second shape also removes the chance of
this diverging again the next time either side changes.

## Effect on the Crucible gates

`typescript` is held out of `scripts/run-chunked.sh`'s opt-in roster while this is open, alongside
`zig` (F-0058 residual, generator#295). It stays in the **encode** roster, which is unaffected.
Recorded in `docs/TODO.md` with the finding named, so it can be lifted mechanically when this
closes.

## What this says about the corpus

The axis had been run only over hand-written corpora until now, where TypeScript was green
throughout. The defect needs invalid UTF-8 *reaching a materialized string* — something a
value-oriented corpus does not produce and a fuzzer produces constantly. Worth remembering when
judging what an axis has actually been exercised against: 311 chunkings over 6 seeds is not the
same kind of evidence as 7 chunkings over 9038 fuzzed inputs.
