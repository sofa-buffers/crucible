# F-0012 — corelib-ts skip path: INCOMPLETE instead of INVALID for a malformed fixlen word in an unknown field

**Status:** open — **corelib-ts bug**, filed **[corelib-ts#49](https://github.com/sofa-buffers/corelib-ts/issues/49)**. TS-only.
**Found:** 2026-07-16 by the **coverage-guided fuzzer** (`scripts/fuzz.sh`, 43k-input
`corpus/interesting`) — the **single largest divergence class** (Cluster 1, ~66% of the
clustered divergences: TS `I` vs the other 11 `R invalid_msg`).
**Axis:** verdict (INVALID vs INCOMPLETE — the §5.2 precedence family).

## The divergence (clean 11-vs-1)

A message that carries a **malformed fixlen word in a skipped (unknown) field** and then
truncates: corelib-ts reports **`I` (INCOMPLETE)**; all 11 other drivers report **`R`
(INVALID)**.

`aa7e79` — field id 2021 (unknown), FIXLEN word `0x79` = subtype 1 (fp64), declared
length 15 (≠8), truncated:

| | verdict |
|---|---|
| c, go, rust×2, cpp, cpp-c-cpp, py×2, java, csharp, zig | `R invalid_msg` |
| **typescript** | **`I`** |

`5df35d07` (unknown field 11, ARRAY_FIXLEN reserved subtype, truncated) splits the same way.

## Root cause (traced to corelib-ts, not codegen)

`src/decode/cursor.ts` `skipValue` — the unknown-field **skip path** validates only
`len > FIXLEN_MAX`, then `take(len)`:
```ts
case WireType.Fixlen: { this.readVarint(); const len = this.upper();
    if (len > FIXLEN_MAX) throw invalidMsgError("fixlen length out of range");
    this.take(len); return; }              // truncation here → INCOMPLETE
```
It never inspects the **subtype**, so a reserved subtype (0x4–0x7) or a wrong-width
`fp32`/`fp64` is not rejected — `take()` runs and throws `INCOMPLETE` on truncation.
The **known-field** path validates eagerly (`assertFixlen`, cursor.ts ~348-349:
`if (sub !== wantSub) …; if (len !== wantLen) …`), which is why `56 0a 59` (wrong-width
fp at *known* field 10) is correctly `R` in TS, but the same word at an *unknown* field
is not. Violates MESSAGE_SPEC §5.2 (INVALID over INCOMPLETE) / §4.6.

## Controls (the trigger is the malformed word, not the unknown id)

- `aa7e124142` — unknown field 2021, **valid** string len2 "AB", complete → **all 12
  skip it and accept** (`A 5607a60656…`). Unknown-id handling is fine.
- `aa7e1241` — same, truncated → **all 12 `I`** (a well-formed-but-truncated skip is
  correctly INCOMPLETE). TS agrees here.

So only a **malformed fixlen word** in the skip path is mis-reported.

## Relationship to prior findings / the audit

Direct TS analogue of the fixed **F-0006** (corelib-py#38) and **F-0007** (corelib-c-cpp#82),
and of the adopted **§5.2 precedence clause** (documentation#17). The PR #37 compliance
audit reported "§5.2 — all 12 compliant", but that only tested wrong-width fp at *known*
small field ids (`56 0a 59` …); the fuzzer exposed the *skip / unknown-field* gap the
targeted audit missed — a good demonstration of the coverage-guided oracle reaching
constructs the hand-written vectors didn't.

## Reproducers

- `unknown_fp64_wrongwidth_trunc.bin` — `aa 7e 79`
- `unknown_arrayfixlen_reserved_trunc.bin` — `5d f3 5d 07`
- `control_valid_skip_complete.bin` — `aa 7e 12 41 42` (all 12 accept; not a divergence)

## Related clusters (a broader skip-path precedence pattern)

Smaller clusters show analogous skip-path precedence gaps in **other** impls on different
constructs (e.g. the C family `c`/`cpp-c-cpp` is the lenient `I` camp in cluster 5, and the
eager `R` camp in cluster 12). TS (Cluster 1) is by far the dominant and cleanest; the
others are worth a follow-up pass once TS lands. `reject_class` differences
(usage/other/invalid_msg) across the family remain **soft** (verdict agrees).

## Harness note

Kept OUT of the green gates (like the other divergent-input findings). The seed +
cross-encode + union + limit gates stay green (well-formed inputs); this lives in the
fuzzer corpus.
