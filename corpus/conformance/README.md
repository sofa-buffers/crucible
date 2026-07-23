# corpus/conformance — §2/§3 canonicality conformance seeds (WP-08)

Small hand-built seed set pinning three MESSAGE_SPEC §2/§3 canonicality rules that were
only *incidentally* covered (every message happens to exercise them, but nothing asserted
them by name). Run as a blocking gate: `CORPUS=corpus/conformance ./scripts/run.sh` — all
13 drivers must agree, and the round-trip re-encode must be canonical.

| seed | rule | assertion |
|---|---|---|
| `a_nested_all_default_empty_frame.bin` | **§2:77-86** — a `sequence` (struct/union/wrapper) is never omitted as a whole; an all-default nested struct is emitted as an **empty frame** (`sequence_begin(id) sequence_end`), *not* dropped. | the message sets only `u8=1`; `nested` (id 10) is all-default → `seq[10]()` on the wire. All 13 re-encode it **with** the empty frame (a whole-object comparison that dropped it would diverge). |
| `b_array_trailing_defaults_noncanonical.bin` | **§3:185-195** — a decoder **MUST accept** a non-canonical trailing-default array run (encoders **MUST NOT** emit it), and re-encode it **canonically** (trailing run trimmed — the F-0010 rule). | `arrays.u8` = `[1,2,3,0,0]` (count 5, two trailing defaults) → all 13 accept and re-encode to **count 3 `[1,2,3]`** (identical to `b_array_canonical_ctl.bin`). |
| `b_array_canonical_ctl.bin` | control | the canonical `[1,2,3]` form — round-trips identically and equals `b`'s re-encode, proving the trim. |

**Not here yet — (c), blocked on WP-05.** §2:112-121 (an explicit `[]` overrides a
**non-empty** field default) is untestable today: no `probe` field declares a non-zero
`default:`. It lands when WP-05 folds `struct_array` into the schema (its `struct{k,v}`
element can carry a non-empty default) — see `docs/improvements.md` WP-08(c) /
corelib-c-cpp#109.
