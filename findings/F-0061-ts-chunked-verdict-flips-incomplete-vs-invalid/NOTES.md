# F-0061 — the generated TypeScript chunked decoder flips the *verdict* between INCOMPLETE and INVALID

**Status:** 🔴 **OPEN** — filed against the generator ([`results/FINDINGS.md`](../../results/FINDINGS.md)
owns this finding's state; this file is the evidence). Also logged as codegen defect **G-0038**.

**Found 2026-08-05**, by re-measuring after the F-0060 fix (generator#297 → #298) rather than
taking the closed issue as proof. The fix is real and large — **12 436 mismatches → 716** — but not
complete, and what is left is a *different and more serious* class than what it replaced.

F-0060 was about the **type of the exception** (a platform `TypeError` escaping instead of
`SofabError`); both paths still rejected. This is about the **verdict itself**.

## Re-measured 2026-08-06 — still red, and `r3` lost its clean baseline

Against sofabgen `0.0.0-20260806101130-dec1e42049cd`, corpus grown to 9502:

| | 2026-08-05 | now |
|---|---|---|
| whole `I` → chunked `R invalid_msg` | 300 | **174** |
| whole `R invalid_msg` → chunked `I` | 5 | **5** |
| total / distinct inputs | 305 / 52 | **179 / 30** |

Direction A keeps shrinking with each generator build; **direction B has not moved at all** — the
same five mismatches, all of them `r3`. That asymmetry is the finding's most useful signal now: the
two halves are not being fixed by the same work, which supports the two-mechanism reading below.

**`r3`'s whole-message baseline moved, and the write-up above must be read with that in mind.**
When it was promoted it was unanimous `R invalid_msg` across all 15. Today the family says `I` and
**typescript alone says `R`** — it is now the whole-message camp of F-0043's finer-offset row
(`overindex_trunc_in_fixlen_word`), where typescript is the *correct* one. So `r3` is entangled
after all, the way `r1` was with documentation#33 — not because it changed, but because the family
moved around it.

It still demonstrates this finding: chunk invariance is an intra-driver property, and typescript
saying `R` whole and `I` chunked is a break whatever the others do. What it no longer carries on
its own is the "nothing here is spec latitude" argument, since the whole-feed verdict is now itself
contested. **generator#300 was updated on 2026-08-05 with the unanimity claim, which is stale as of
this build** — worth a correction there.

## Re-measured 2026-08-05 (late) — the fix is partial; the axis stays red

[generator#300](https://github.com/sofa-buffers/generator/issues/300) was closed 15:28 UTC and the
sofabgen CI build installed for this run (`0.0.0-20260805161231-f5457b755f53`, 16:12 UTC) carries
it. Re-measured rather than believed — which is this finding's own rule, and it was right again:

| | before (2026-08-05, filing) | now |
|---|---|---|
| `r0_unanimous_I_flips_to_R` | typescript `R`, family `I` | **passes** — 0 mismatches |
| `r1_entangled_with_doc33` | flips under chunking | **passes** — 0 mismatches |
| whole `I` → chunked `R invalid_msg` | 427 | **300** |
| whole `R invalid_msg` → chunked `I` | 182 | **5** |
| total, `corpus/interesting` × 6 chunk sizes | 609 | **305**, over **52** distinct inputs |

So both filed reproducers are genuinely repaired and direction B all but collapsed — and the class
survives at half its size. The 52 inputs fail at **every** chunk size that cuts them (52 at `n`=1,
2, 3; 51 at 5, 8; 47 at 16), so what is left is a property of the *input*, not of where the
boundary happens to fall.

**This is the third fix in three days to close its issue, repair its reproducer, and leave the axis
red** — after generator#293→#295 (zig) and generator#297→#298 (this finding's own predecessor,
F-0060). The pattern is now the finding, not the incident.

[generator#300](https://github.com/sofa-buffers/generator/issues/300) was **reopened 2026-08-05**
with these counts and `r3` rather than filed as a successor issue: the reported path is repaired,
but the defect the issue names — the verdict flipping with the chunk boundary — is the same one
still standing.

### `r3` — a clean direction-B reproducer, which this finding did not have

`c6 0c 02 0a 41 07 c6 0c 8a 0a c2` (11 B) — `r3_wrapper_reopen_overindex_trunc.bin`:

- `c6 0c` — `string_array` wrapper at field 200, opened;
- `02 0a 41` — element 0, fixlen subtype String, length 1, payload `A`;
- `07` — sequence end, closing the wrapper;
- `c6 0c` — the **same wrapper re-opened** (§7.4);
- `8a 0a` — an element header with id **161**, past the schema `count` — §7.1 `INVALID`;
- `c2` — the fixlen word starts and the message ends inside it.

| | verdict |
|---|---|
| whole (one feed) | **all 15 drivers: `R invalid_msg`** |
| `SOFAB_CHUNK` = 1, 2, 3, 5, 8 | 14 drivers `R invalid_msg`, **typescript `I`** |

The baseline is unanimous, so unlike `r1` this input carries the argument on its own: no spec
latitude, no [documentation#33](https://github.com/sofa-buffers/documentation/issues/33)
entanglement. It is also the **whole** of direction B in the corpus — its five mismatches are the
five counted above — which makes it the isolate for that half rather than merely an example of it.

Note it is a *lost* `INVALID`, not a spurious one: the over-index violation is fully on the wire
before the truncation, §5.2 makes `INVALID` dominate, and every other implementation says so under
the same cuts. Whatever the accumulator does across a boundary, it drops a verdict that was already
decided.

## The clean reproducer (as filed — **now passes**, see the re-measurement above)

`a6 06 56 08 05 0c 7f` — seven bytes:

| | verdict |
|---|---|
| whole (one feed) | **all 15 drivers: `I`** |
| `SOFAB_CHUNK=1` and `=2` | 14 drivers `I`, **typescript `R invalid_msg`** |

The baseline is *unanimous*, so nothing here is spec latitude: the same bytes are INCOMPLETE when
fed whole and INVALID when fed in pieces, in one implementation. CORELIB_PLAN §6.4 and §7.2 item 4
state the rule directly — **a chunk boundary MUST NOT affect the outcome.**

## Both directions occur (counts as filed — re-measured above)

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
