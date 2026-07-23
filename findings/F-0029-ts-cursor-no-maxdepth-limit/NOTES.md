# F-0029 — corelib-ts (cursor decoder) reports INCOMPLETE for nesting past MAX_DEPTH

**Status:** 🔴 **OPEN** — [corelib-ts#65](https://github.com/sofa-buffers/corelib-ts/issues/65).
Found 2026-07-23 by the **WP-04 framing & ceilings sweep** (`engine/structured/sweep_framing.py`).

**Axis:** framing/ceilings (§4.9/§6.2), verdict split. **Impls:** `typescript` (1) reports `I` vs the
other **12** reject (`R`). **Corelib, not codegen**; the fix location is pinned to one of corelib-ts's
three decode paths.

## The split

Nesting past **MAX_DEPTH** (255, CORELIB_PLAN §4.9/§6.2:646) is `INVALID` (§6.2) — and it is in the
**adopted §5.2 "INVALID regardless of what follows" list** ([documentation#17](https://github.com/sofa-buffers/documentation/pull/17):
"nesting beyond MAX_DEPTH"), so it dominates INCOMPLETE even though the deeply-nested message is also
unterminated. The reproducer opens 300 sequences (`0x06` × 300) with nothing to close them.

| camp | behaviour | drivers |
|---|---|---|
| **reject** (conformant §4.9/§6.2 + §5.2) | rejects at the 256th open → `R invalid_msg` | c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython, py-pure, java, csharp, zig, dart (12) |
| **incomplete** | tracks no depth ceiling → 300 open sequences → EOF with depth > 0 → `I` | **typescript (1)** |

Because MAX_DEPTH exceedance is adopted-INVALID, `I` here is a conformance violation, **not** the open
INVALID-vs-INCOMPLETE precedence hole (documentation#15) — that hole is over-*schema*-count/length +
truncated, a different construct.

## Reproducers

- `depth_over_maxdepth.bin` = `0x06` × 300 — 300 `sequence_start(id 0)`, no closes. **ts:** `I`;
  **12 others:** `R`.
- `depth_ok_ctl.bin` = `0x06`×8 + `0x07`×8 — a balanced 8-deep nest, valid → **all 13 `A`**. Isolates
  the divergence to *exceeding the depth ceiling*, not to nesting per se.

```sh
CORPUS=findings/F-0029-ts-cursor-no-maxdepth-limit ./scripts/run.sh
# 2 inputs: control agrees (all 13 A); depth_over_maxdepth diverges (ts I vs 12 R)
```

## Root cause — the `cursor` decode path tracks depth for balancing but never checks MAX_DEPTH

corelib-ts has **three** decode paths, and two of them enforce MAX_DEPTH while the third does not:

| path | MAX_DEPTH check |
|---|---|
| `src/decode/fast.ts` | ✅ `:195-198` — `if (stack.length - 1 >= MAX_DEPTH) throw invalidMsgError("nesting exceeds MAX_DEPTH …")` |
| `src/decode/state.ts` | ✅ `:331-335` — the identical guard |
| **`src/decode/cursor.ts`** | ❌ **none** — it maintains `private depth` (`:115`) and `depth++`/`depth--` on sequence start/end (`:170`, `:165`), uses it only for the **stray-end** check (`depth === 0`, `:162`) and the **EOF-incomplete** check (`depth > 0` → `I`, `:151`); it never compares `depth` to `MAX_DEPTH`. |

So the `cursor` decoder increments `depth` to 300 without a ceiling, then reports `I` at EOF because the
sequences are unclosed. The fix is a one-line guard mirroring `fast.ts:197` / `state.ts:334` at the
`depth++` site (`cursor.ts:170`): `if (this.depth >= MAX_DEPTH) throw invalidMsgError(...)`.

## Attribution — corelib-ts, not codegen

Per the triage: *does the fix need knowledge only the schema has?* **No.** `MAX_DEPTH` is a format-wide
constant (255); the check is pure wire mechanics, present in corelib-ts's own `fast.ts`/`state.ts` and in
every other corelib. This is an **internal inconsistency** within corelib-ts (`cursor` vs `fast`/`state`)
— the strongest evidence that the constant and the intended behaviour already exist and only the `cursor`
path is missing the guard. Generated code is uninvolved (no schema knowledge decides a format ceiling).
Filed against **corelib-ts** (`src/decode/cursor.ts`).

## Regression-gate & promotion

Held out of the blocking `corpus/regression/` gate and the framing axis kept **report-only** until the
fix lands. When it lands: re-bootstrap, verify `depth_over_maxdepth` → all 13 `R`, promote the reproducer
+ the `depth_ok_ctl` control into the gate, flip the framing axis's MAX_DEPTH vectors to blocking.
(The `ID_MAX` split is the sibling F-0028; `FIXLEN_MAX`/`ARRAY_MAX`/stray-end are green on the same axis.)
