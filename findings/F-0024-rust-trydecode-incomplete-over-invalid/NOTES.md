# F-0024 — generated Rust `try_decode` returns INCOMPLETE where INVALID must win (§5.2 precedence)

**Impls:** rust-std, rust-nostd (lone `I`; the other 10 emit `R`)
**Axis:** verdict (INVALID-vs-INCOMPLETE precedence)
**Attribution:** **generator (sofabgen Rust backend)** — codegen defect **G-0016**. Generator-only; no corelib change.
**Status:** 🆕 open — filed [generator#190](https://github.com/sofa-buffers/generator/issues/190). Found 2026-07-20 by the 8 h pacemaker round (2.24 G execs); dominant divergence
class of the run (**63 %** of sampled verdict-splits). Delta-debugged 146 B → **11 B**.

## The divergence

Reproducer `repro_invalid_utf8_then_trunc.bin` (11 B): `c6 0c 07 c6 0c 02 12 ff ff 07 8a`

| bytes | meaning |
|---|---|
| `c6 0c` | seq_begin field **200** = `string_array` (open) |
| `07` | seq_end (close — empty) |
| `c6 0c` | `string_array` reopened |
| `02 12` | string element, length 2, subtype *string* |
| `ff ff` | the 2 string bytes → **invalid UTF-8** |
| `07` | seq_end |
| `8a` | varint header start — message **ends mid-varint** (truncation) |

Verdicts: **10 drivers → `R invalid_msg`** (c/cpp/cpp-c-cpp\* /go/java/ts/csharp/zig; \*cpp-c-cpp/py report
the soft `R usage` reject-class), **rust-std + rust-nostd → `I`**.

The message is **INVALID**: it carries an invalid-UTF-8 string. MESSAGE_SPEC §5.2 — *"malformed
regardless of what follows"* — makes INVALID dominate INCOMPLETE, so the trailing truncation does not
matter: the correct verdict is `R`. Rust returns `I`.

## Four controls pin it to precedence, not validation

| vector | bytes | expected | result |
|---|---|---|---|
| `control_valid_complete` | `…12 41 42 07` (string "AB") | A | **all 12 `A`** ✓ |
| `control_invalid_utf8_complete` | `…12 ff ff 07` (bad UTF-8, no trunc) | R | **all 12 `R`** ✓ (rust too) |
| `control_valid_then_trunc` | `…12 41 42 07 8a` (valid + trunc) | I | **all 12 `I`** ✓ |
| **`repro_invalid_utf8_then_trunc`** | `…12 ff ff 07 8a` (bad UTF-8 **+** trunc) | **R** | **10 `R`, rust `I`** ✗ |

`control_invalid_utf8_complete` proves Rust **does** detect the invalid UTF-8 (→ `R`) when the message is
complete. The bug appears **only** when a truncation is *also* present: Rust lets INCOMPLETE override the
already-detected INVALID. This is a pure **ordering** bug, not a missing check.

## Root cause — the `?` in the generated `try_decode`

Generated `message.rs` (sofabgen Rust backend), `probe_dec::try_decode`:

```rust
pub fn try_decode(data: &[u8]) -> Result<Probe, sofab::Error> {
    let invalid;
    {
        let mut v = V { …, inv: false, … };
        is.feed(data, &mut v)?;            // (234)  ← `?` returns feed's Err(Incomplete) HERE
        invalid = v.inv;                    // (236)  ← never reached under truncation
    }
    …
    if invalid { return Err(sofab::Error::InvalidMsg); }   // (240)  ← never reached
    …
}
```

The generated visitor sets the sticky `v.inv = true` for every **schema-bound** violation — invalid UTF-8
(`message.rs:325`/`329`, `core::str::from_utf8(..) => Err => self.inv = true`), over-count arrays
(`:275-292`, `else { self.inv = true }`), over-length string/blob (`:314/315/343`, `if total > N`),
`string_array` element id ≥ 5 (`:335`). But when the input **also** ends in a truncation, `feed` returns
`Err(Error::Incomplete)`, and the **`?` on line 234 propagates it immediately** — before `v.inv` is read
(236) or acted on (240). The INVALID signal is silently dropped in favour of INCOMPLETE.

This is why the whole run's 15-signature cluster collapses to **one** cause: every schema-bound `inv` path,
combined with a trailing truncation, hits the same `?`.

## Attribution — generator, not corelib (established, not inferred)

- **corelib-rs `IStream::feed` is correct.** It reports the *structural* three-valued outcome
  (`istream.rs:170-176`): `Err(Incomplete)` when not `at_boundary()`. Detecting invalid UTF-8 or
  schema bounds is deliberately **not** its job — `deliver_payload` returns `usize` (no error) and the
  `string` visitor callback is default-empty (`istream.rs:57`). The corelib has no way to know the field is
  a `string` or that count ≤ 5; only generated code does. Per the CLAUDE.md triage table, schema-bound
  facts belong to **generated code**.
- **The other 4 shared-callback backends (csharp/java/zig) and all 6 non-callback backends emit `R`** on the
  same input — i.e. their generated decode checks the invalid flag *before* propagating incomplete. The wrong
  ordering is **specific to the sofabgen Rust backend's `try_decode` template**.

## Fix (generator-only, symmetric)

Reorder the emitted template so INVALID wins per §5.2:

```rust
let r = is.feed(data, &mut v);
if v.inv { return Err(sofab::Error::InvalidMsg); }   // §5.2: INVALID dominates INCOMPLETE
r?;                                                   // only then surface a clean truncation as Incomplete
```

Same change for `decode`/`try_decode` in both `rs` and `rs-no-std` output (one template).

## Relation to prior findings

Same **§5.2 precedence family** as the resolved F-0006/F-0007 (C/Py scalar fixlen), F-0012 (TS skip path),
F-0014 (array element word) — but those were each a *missing/late check*; this is a *correct check whose
result is discarded by a `?`*. Rust was never the lone outlier in the earlier cases, so its `try_decode`
ordering was never exercised at a truncation boundary until the 8 h fuzz corpus hit it. Distinct from the
open F-0022/F-0023 (those are §7.3 wire-type **skip** on the same `string_array` field; this is §5.2
**precedence**).
