# Findings

Triaged divergences the differential loop has surfaced. Each has a reproducer
under `findings/<id>/` and a verdict path (corelib bug fix, or a `policy.yaml`
allow-entry once the spec rules). Transient, un-triaged crash/divergence
artifacts live under `corpus/crashes/` (gitignored); promoted findings land here.

| id | title | impls | axis | status |
|---|---|---|---|---|
| [F-0001](../findings/F-0001-truncated-trailing-varint/NOTES.md) | truncated trailing varint: two camps — C/C++/Rust/Java/C# accept, Go+Python+TS+Zig reject (7 vs 5) | {c,cpp,c-cpp,rust-std,rust-nostd,java,csharp} vs {go,py-cython,py-pure,typescript,zig} | verdict | open — pending spec (PLAN §8) |
| [F-0002](../findings/F-0002-encoder-negative-left-shift-ub/NOTES.md) | corelib-c-cpp encoder left-shifts a negative value (UB) | corelib-c-cpp | ub (sanitizer) | open — corelib bug, fix upstream |

Generated-code (codegen, not corelib) weaknesses are tracked separately in
[`docs/SOFABGEN.md`](../docs/SOFABGEN.md) (G-0001..G-0004).

## Phase 1 note

The loop found F-0001 on its **first run** over hand-written seeds — before any
coverage-guided or structure-aware fuzzing. That is the differential oracle
working as designed: a divergence no single-implementation fuzzer could report,
because no impl crashes — they simply disagree. Phase 2 (adding Rust, C++,
Python, Java, TypeScript, C#, and Zig) grew it from 1-vs-1 into a
7-accept-vs-5-reject **two-camp** split — four independent lineages (Go, Python,
TypeScript, Zig) reject where the C/C++/Rust/Java/C# camp accepts. That is exactly
the extra signal more implementations buy: a lone outlier is ambiguous; four
independent rejects point firmly at the answer — and the split cuts across the
systems/managed line, so it is a genuine per-decoder design difference.
