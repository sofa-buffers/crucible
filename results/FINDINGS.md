# Findings

Triaged divergences the differential loop has surfaced. Each has a reproducer
under `findings/<id>/` and a verdict path (corelib bug fix, or a `policy.yaml`
allow-entry once the spec rules). Transient, un-triaged crash/divergence
artifacts live under `corpus/crashes/` (gitignored); promoted findings land here.

| id | title | impls | axis | status |
|---|---|---|---|---|
| [F-0001](../findings/F-0001-truncated-trailing-varint/NOTES.md) | truncated trailing varint: two camps — C/C++/Rust accept, Go+Python reject (5 vs 3) | {c,cpp,c-cpp,rust-std,rust-nostd} vs {go,py-cython,py-pure} | verdict | open — pending spec (PLAN §8) |

Generated-code (codegen, not corelib) weaknesses are tracked separately in
[`docs/SOFABGEN.md`](../docs/SOFABGEN.md) (G-0001..G-0004).

## Phase 1 note

The loop found F-0001 on its **first run** over hand-written seeds — before any
coverage-guided or structure-aware fuzzing. That is the differential oracle
working as designed: a divergence no single-implementation fuzzer could report,
because no impl crashes — they simply disagree. Phase 2 (adding Rust, C++, and
Python) grew it from 1-vs-1 into a 5-accept-vs-3-reject **two-camp** split — two
independent lineages (Go, Python) reject where the C/C++/Rust lineage accepts.
That is exactly the extra signal more implementations buy: a lone outlier is
ambiguous; two independent rejects point at the answer.
