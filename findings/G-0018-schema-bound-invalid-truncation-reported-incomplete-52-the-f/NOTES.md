# G-0018 — schema-bound INVALID + truncation reported INCOMPLETE (§5.2; the F-0024 class, still open across backends)

**Status:** ✅ **RESOLVED (re-verified 2026-07-25)** — [generator#216](https://github.com/sofa-buffers/generator/issues/216). Finding
**Issue:** [generator#216](https://github.com/sofa-buffers/generator/issues/216)

[`F-0032`](../findings/F-0032-schema-bound-invalid-vs-truncation-go-cpp-ts-dart/NOTES.md). The F-0024/G-0016
ordering class: the go/ts/dart/zig/rust codegen splits closed in the generator (#222/#223/#224); the **cpp**
residual was the Crucible driver bypassing the generated `try_decode` (fixed in crucible#107), and the cpp
measure-schema's §7.3 subtype-gate gap (corelib-cpp `80ec210`, = generator#229) is fixed. All 13 agree `R` on
the F-0032 vectors; wiretype §7.3 sweep green.

A message that is both a schema-bound violation (over-maxlen / over-count / over-index / invalid-UTF-8)
and truncated is reported `INCOMPLETE` by several backends where §5.2 (documentation#15, adopted) requires
`INVALID` — INVALID dominates INCOMPLETE. `count`/`maxlen`/`id` are schema facts, so the bound check and
the decision to check it **at the deciding word/header** (before propagating a truncation `Incomplete`)
are generated code. The split varies by bound: over-maxlen+trunc → go/cpp/ts/dart `I`; over-count+trunc →
9 backends `I` (even Rust — F-0024's fix covered UTF-8/over-len, not the compact-array count path);
over-index+trunc → cpp `I`. **Fix:** apply the F-0024 pattern (generator#190) to every schema-bound check
in every backend — reject as soon as the word/header shows the violation.
