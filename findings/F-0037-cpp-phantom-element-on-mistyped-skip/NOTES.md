# F-0037 — the C++ generated decode materializes a phantom element when it skips a mistyped child inside `struct_array` (cpp + cpp-c-cpp)

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — vectors promoted 2026-08-16, replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Issue:** [generator#249](https://github.com/sofa-buffers/generator/issues/249)
**Codegen:** G-0022 | [generator#249](https://github.com/sofa-buffers/generator/issues/249) | the generator side of F-0037 — **the generated C++ decode materializes a phantom element when it skips a mistyped child inside `struct_array`** — a scalar at the elemen…

**Filed:** [generator#249](https://github.com/sofa-buffers/generator/issues/249)

**Family:** `poc/omit-all-default-sequences` (found 2026-07-27 by the §7.3 wiretype
sweep at the new WP-05 element position — all 8 mistyped constructs at the element
slot split identically).

## The split

`mistyped_elem_phantom.bin` — `u8=1` + `seq[202]( U-scalar id 0 = 7 )`: the child of
the wrapper is a **scalar**, not the SEQ frame the schema declares for an element.
§7.3 (adopted, documentation#23): a mistyped field is **skipped** like an unknown id.

| camp | re-encode |
|---|---|
| the other 11 | `0001` — the mistyped child is skipped, the wrapper stays all-default and is omitted (§2) |
| `cpp`, `cpp-c-cpp` | `0001` + `seq[202]( elem0() )` — the skip left a **default-initialized element 0 in the container** |

`ctl_unknown_id_skip.bin` (a well-typed element) agrees on all 13.

## Why it matters

The phantom is a **decoded-value** defect, not just a byte one: the container holds
1 element where the family holds 0. Once F-0036 (trailing-trim) lands family-wide,
the round-trip re-encode of `[default]` trims to the omitted wrapper and this
finding becomes **invisible to the round-trip oracle** — only the materialized
(element-access) dump still shows the phantom element. Classic canonical-form
masking (`oracle/materialized.md`, the F-0010 lesson).

## Attribution — codegen (generator C++ backend), G-0022

Both C++ profiles (`cpp` over corelib-cpp, `cpp-c-cpp` over corelib-c-cpp's C++
object layer) and **only** them — the shared artifact is sofabgen's generated C++
(`drivers/cpp/gen/{cpp,c-cpp}/probe.hpp`), so the defect sits in the generated
element-decode path, not in either corelib: corelib-cpp's `MessageSeq::deserialize`
is only *called* for a well-typed SEQ child, and the corelib skip path
(`sofab.hpp` §7.3 handling) has no access to the generated container to grow it.
The generated `case 202:` arm constructs the `MessageSeq` reader and hands it to
`is.read(_r0)` — the phantom appears when the surrounding read processes the
mistyped child; the exact line is for upstream to pin, but the camp boundary
(generated C++ only) already isolates it to the backend. The F-0020/F-0017
neighborhood: the C++ backend's wire-type gates lag the other backends.

## Repro

```
CORPUS=findings/F-0037-cpp-phantom-element-on-mistyped-skip ./scripts/run.sh
```

Carved out of the blocking wiretype axis at the (202,) element position until fixed
(the F-0034 pattern), and out of `sweep_empty_frame`'s element cells where the
phantom contributes to the split.

## Resolution

**Impls:** generator (**C++ backend**, codegen, **G-0022**) — `cpp` *and* `cpp-c-cpp` (the shared artifact is the generated `probe.hpp`; neither corelib can grow the container from its skip path) · **Axis:** accept_value (round-trip; a decoded-**value** defect)

✅ **RESOLVED in sofabgen 0.21.0** — [generator#249](https://github.com/sofa-buffers/generator/issues/249) closed. **Re-verified 2026-07-29** against corelibs **0.9.0 @ main** + sofabgen **0.21.0** — the first family carrying the merged sparse-array rewrite (documentation#29/#31). Both reproducers agree, and the §7.3 wiretype sweep no longer shows a `cpp` camp at the element position. *History:* Found 2026-07-27 by the §7.3 wiretype sweep at the new WP-05 element position (all 8 mistyped constructs split identically, poc family). NB once G-0021 lands, the trailing-trim hides this from the round-trip oracle — only the materialized dump still shows the phantom (the F-0010 masking lesson). The F-0017/F-0020 neighborhood (C++ backend wire-type gates). Carved out of the blocking wiretype-axis cells at the (202,) element position; reproducers in `findings/F-0037…/`
