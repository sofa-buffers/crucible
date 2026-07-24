# F-0032 — a schema-bound INVALID that is also truncated is reported INCOMPLETE (§5.2 precedence), varying by bound & backend

**Status:** 🟢 **RESOLVED** (2026-07-24) — all 13 drivers now `R` on every (bound, backend) truncation.
Found 2026-07-23 by the **WP-09 broadened malform×truncation** axis
(`engine/structured/sweep_malform_truncate.py`); [generator#216](https://github.com/sofa-buffers/generator/issues/216)
(the F-0024 §5.2-ordering class).

## Resolution — the cpp residual was in THIS driver, not generator codegen

The go/ts/dart/zig/rust splits closed in the generator (generator#222/#224, header-hook ordering).
The last-standing **cpp** residual was **not** the generated decode's check ordering (this NOTES' original
attribution): the generator side (generator#223 + corelib-cpp#50) is correct — `Probe::try_decode` installs
the measure-phase `sofab::schema` via `setSchema`, which rejects an over-count/over-maxlen/over-index field
at its deciding word, so all three reproducers decode to `R` through that entry. **This C++ driver bypassed
it**: it built a bare `sofab::IStreamObject` and called `feed()` directly, never installing the schema, so
the pure-corelib-cpp measure-then-deliver walk reported `I` (INCOMPLETE). `cpp-c-cpp` was `R` because the
fixed-capacity wrapper is statically bound-checked and needs no measure schema — which is exactly why the
split was cpp-only. Fix: route `decode_and_report` through the generated `message::Probe::try_decode`
(installs the schema on pure-cpp, a plain feed on c-cpp). Verified: the four F-0032 vectors → `R`; an
in-bound truncation stays `I`; a complete over-count stays `R`; valid messages accept and re-encode.

**Axis:** malform×truncation (§5.2), verdict split. **Corelib-agnostic / codegen** — maxlen/count/id are
schema facts, so the bound check *and its ordering* are generated code (CLAUDE.md triage; F-0024 was this
exact bug in the Rust backend).

## The rule and the split

MESSAGE_SPEC §5.2 (**documentation#15, CLOSED/adopted**): INVALID is *"malformed regardless of what
follows"* and **dominates** INCOMPLETE — a message that is *both* a definitive violation *and* truncated
is **`R`**, never `I`. A **structural** violation (reserved subtype, a bad array element-word) is INVALID
at the field's *word*, so every decoder rejects it before the payload — those broadened truncations are
green (all 13 `R`, blocking). A **schema-bound** violation (over-maxlen / over-count / over-index /
invalid-UTF-8) is instead checked *after* the content is read, so a decoder that reads first hits the
truncation and reports `I` before the bound check — the §5.2 violation. The split varies by (bound,
backend):

| malformation (declared bound, then truncated payload) | `R` (conformant) | `I` (§5.2 violation) |
|---|---|---|
| over-maxlen string (`len 33 > 32`, payload cut) | c, rust-std, rust-nostd, cpp-c-cpp, py-cython, py-pure, java, csharp, zig (9) | **go, cpp, typescript, dart (4)** |
| over-count array (`count 6 > 5`, elements cut) | c, cpp-c-cpp, java, csharp (4) | **go, rust-std, rust-nostd, cpp, py-cython, py-pure, typescript, zig, dart (9)** |
| over-index wrapper element (`id 5 ≥ count`, then EOF) | 12 | **cpp (1)** |

(`over_len_string_complete_ctl.bin` — the *complete* over-maxlen — is `R` on all 13, so the malformation
itself is definitively INVALID; only the *truncated* form splits.)

## Why it varies

Each backend checks each bound at a different point. Over-**maxlen** is checkable at the fixlen *word*
(the length is there) — most check it there, 4 don't. Over-**count** is checkable at the *count* varint,
but most backends only compare after consuming `count` elements, so a truncated array can't finish → `I`
(9 backends, even Rust — F-0024's fix covered UTF-8/over-len but not the compact-array count path).
Over-**index** is checked at the element header by almost all (only cpp defers). So this is one class —
the F-0024 INVALID-vs-INCOMPLETE ordering — **incompletely fixed**: resolved for some (bound, backend)
pairs, open for others.

## Attribution — generator (codegen), the F-0024 family

Per the triage table: `count`/`maxlen`/`id` are **schema facts → only generated code** knows them, so
the bound check and the decision to check it *at the word/header* (before propagating a truncation
`Incomplete`) are codegen. F-0024 fixed exactly this in the Rust backend (generator#190 / G-0016: read
the sticky `inv` before `feed`'s `Err(Incomplete)`); the same fix pattern must be applied to **every
schema-bound check in every backend** — check the bound as soon as the deciding word/header is read.
→ **G-0018**, filed against `generator`.

## Reproduce

```sh
CORPUS=findings/F-0032-schema-bound-invalid-vs-truncation-go-cpp-ts-dart ./scripts/run.sh
# *_complete_ctl → R on all 13; the *_trunc_* forms split R-vs-I per the table above.
```

## Regression-gate & promotion

The broadened `sweep_malform_truncate` axis keeps the **structural** malformations' into-payload
truncations blocking (green) and the `_complete` + mid-varint-`_trunc_tail` of every malformation blocking
(all `R`); the **schema-bound** malformations' into-payload truncations are carved OUT (the `STRUCTURAL`
set in the axis) as F-0032 reproducers until the fix landed (generator#222/#223/#224 for the codegen
splits; this driver's `try_decode` switch for the cpp residual). Promotion: drop the carve-out,
regenerate, verify every (bound, backend) truncation → `R` across all 13 drivers.
