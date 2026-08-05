# F-0061 — the generated TypeScript chunked decoder flips the *verdict* between INCOMPLETE and INVALID

**Status:** 🔴 **OPEN** — filed against the generator ([`results/FINDINGS.md`](../../results/FINDINGS.md)
owns this finding's state; this file is the evidence). Also logged as codegen defect **G-0038**.

**Found 2026-08-05**, by re-measuring after the F-0060 fix (generator#297 → #298) rather than
taking the closed issue as proof. The fix is real and large — **12 436 mismatches → 716** — but not
complete, and what is left is a *different and more serious* class than what it replaced.

F-0060 was about the **type of the exception** (a platform `TypeError` escaping instead of
`SofabError`); both paths still rejected. This is about the **verdict itself**.

## The clean reproducer

`a6 06 56 08 05 0c 7f` — seven bytes:

| | verdict |
|---|---|
| whole (one feed) | **all 15 drivers: `I`** |
| `SOFAB_CHUNK=1` and `=2` | 14 drivers `I`, **typescript `R invalid_msg`** |

The baseline is *unanimous*, so nothing here is spec latitude: the same bytes are INCOMPLETE when
fed whole and INVALID when fed in pieces, in one implementation. CORELIB_PLAN §6.4 and §7.2 item 4
state the rule directly — **a chunk boundary MUST NOT affect the outcome.**

## Both directions occur

Over `corpus/interesting` (9038 fuzzed inputs), chunk modes only:

| direction | cases |
|---|---|
| whole `I` → chunked `R invalid_msg` | 427 |
| whole `R invalid_msg` → chunked `I` | 182 |

Spread evenly across every chunk size (≈100 each at `n` = 1, 2, 3, 5, 8, 16). That both directions
appear rules out a single one-way ordering slip.

`r1_entangled_with_doc33.bin` (`56 1a 73`, three bytes) is the smallest of the second direction, but
it is **not clean**: the family is already split 8-vs-7 on that input when fed whole, which is the
mid-payload UTF-8 `MAY` of
[documentation#33](https://github.com/sofa-buffers/documentation/issues/33). TypeScript moving
between the camps under chunking is still a chunk-invariance break, but the input cannot carry the
argument on its own. `r0` can, which is why it is the headline.

## Hypothesis — unverified

The F-0060 fix added a `_str()` helper that converts *every* `TextDecoder` failure into
`SofabError(InvalidMsg)`:

```ts
function _str(bytes: Uint8Array): string {
  try { return _dec.decode(bytes); }
  catch { throw new SofabError(SofabErrorCode.InvalidMsg, "invalid UTF-8 in string"); }
}
```

corelib-ts's own `Cursor.readString` does the same conversion but is explicit about what must come
first:

> `take()` (truncation → INCOMPLETE) runs **before** the decode, so a short payload stays
> INCOMPLETE; only genuinely malformed UTF-8 bytes reach the fatal decoder.

If the chunked visitor can reach `_str` with bytes the one-shot path would have resolved as
INCOMPLETE, the unconditional conversion would turn those into INVALID — which is direction A
exactly. **This is reasoning from the two code shapes, not something pinned**: the generated
accumulator's `take(total, offset, chunk)` returns `null` while a payload is still short, which on
its face should prevent it, and it does not explain direction B at all. Left for whoever knows the
accumulator.

## Attribution — the generator

`_str`, the accumulator and the visitor are all emitted into `message.ts`. The corelib both gets
this right and documents the ordering constraint that makes it right, one file away. No schema fact
participates.

## Effect on the Crucible gates

`typescript` stays out of `scripts/run-chunked.sh`'s opt-in roster — it was held out for F-0060 and
the reason simply changed. It remains in the **encode** roster, unaffected. `docs/TODO.md` carries
the re-add item, now naming this finding.

## The lesson, again

This is the second time in two days that a fix closed its issue, genuinely repaired the reported
path, and left the axis red — after generator#293 → #295 for zig. Both were caught by re-running
the measurement rather than reading the ticket. Worth stating as a rule: **a closed upstream issue
is a reason to re-measure, never a substitute for it.**
