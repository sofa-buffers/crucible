# Findings

Triaged divergences the differential loop has surfaced. Each has a reproducer
under `findings/<id>/` and a verdict path (corelib bug fix, or a `policy.yaml`
allow-entry once the spec rules). Transient, un-triaged crash/divergence
artifacts live under `corpus/crashes/` (gitignored); promoted findings land here.

| id | title | impls | axis | status |
|---|---|---|---|---|
| [F-0001](../findings/F-0001-truncated-trailing-varint/NOTES.md) | C accepts a truncated trailing varint that Go rejects | c vs go | verdict | open — pending spec (PLAN §8) |

## Phase 1 note

The two-language loop found F-0001 on its **first run** over 8 hand-written
seeds — before any coverage-guided or structure-aware fuzzing. That is the
differential oracle working as designed: a divergence no single-implementation
fuzzer could report, because neither impl crashes — they simply disagree.
