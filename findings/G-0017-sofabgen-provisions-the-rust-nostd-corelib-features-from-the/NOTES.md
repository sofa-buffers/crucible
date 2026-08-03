# G-0017 — sofabgen provisions the rust-nostd corelib features from the schema's *used* wire types, so the decoder can't §7.3-skip an array / fp64 field

**Status:** ✅ **RESOLVED (sofabgen bump 2026-07-23)** — [generator#215](https://github.com/sofa-buffers/generator/issues/215)
**closed 2026-07-23**; sofabgen now emits the full wire-type decoder feature set regardless of the schema's
used wire types. **Re-verified on CI build `0.0.0-20260723154129-241dc8f44efb`:** the wiretype (§7.3) union
sweep (drivers built against `probe-union`) is green — 77 vectors, 0 divergences — so the no-std decoder
now skips a mis-typed/unknown array or fp64 field instead of rejecting it. Finding
[`F-0027`](../findings/F-0027-nostd-feature-gated-skip-rejects-array-fp64/NOTES.md). Was generator-primary,
**corelib-rs-no-std implicated** (the F-0010 "occasionally both" shape). Found 2026-07-22 by the WP-01
union pass of the wiretype (§7.3) sweep — the first sweep run against a schema (`probe-union`) that
declares **no array and no fp field**.

corelib-rs-no-std is a streaming push-parser whose wire-type support is **cargo-feature-gated** (an
intentional embedded code-size knob — `vendor/corelib-rs-no-std/Cargo.toml` `[features]`: `array`,
`fixlen`, `fp64`, `sequence`, `value64`). The gate covers **parsing/skip**, not merely field storage:
in `src/istream.rs::on_header` the array arms are `#[cfg(feature = "array")]` and fall through to
`_ => Err(Error::InvalidMsg)` (:331) when off; the fp64 fixlen arm is `#[cfg(feature = "fp64")]`
(:386-392) and its subtype otherwise fails `FixlenType::from_raw` (:352). One dispatch serves both
decode-into-field and read-and-discard, so a build without a feature **cannot skip** that wire type.

sofabgen (`--lang rust`, `drivers/rust/build.sh:53`) writes the driver `Cargo.toml` and selects the
`sofab` dependency's feature list from the wire types the **schema declares**:

| schema | generated `features = [...]` | skip an array / fp64 field |
|---|---|---|
| `probe` (arrays + fp present) | `["array","fixlen","fp64","sequence","value64"]` | ✅ `A` (skipped, §7.3) |
| `probe-union` (no array, no fp) | `["fixlen","sequence"]` | ❌ `R invalid_msg` |

(The feature list is sofabgen's, not `build.sh`'s — `build.sh` only appends the `limit` feature,
lines 83-88.) **Why it is a bug:** §7.3 skip-ability is **schema-independent** — a field can receive
*any* wire type as a mismatch, and an *unknown* id can carry *any* construct, both of which MUST be
skipped. Provisioning the corelib with only the wire types the schema *uses* therefore compiles a
**§7.3-non-conformant decoder**: it rejects (`InvalidMsg`) a well-formed skippable array/fp64 field that
all 12 other drivers — including `rust-std`, whose corelib is not feature-gated this way — skip. Minimal
isolate `0300` (a 2-byte empty `VARINTARRAY_U` at id0).

**Established as generator (with corelib implicated), not decode-logic codegen:** the generated decode
logic is identical for `rs` and `rs-no-std` (one `driver.rs`), and `rust-std` accepts — so it is not the
emitted decode template. The two-way sibling split (CLAUDE.md diagnostic step 3) — `rust-std` agrees with
the family, `rust-nostd` on `probe` (features on) skips fine, only `probe-union` + no-std rejects — pins
it to the **feature configuration**, which only codegen derives from the schema and only codegen writes.
Per the triage's step-2 test, the corelib was *handed* a feature config and faithfully rejected → the
caller (codegen) is the bug.

**Fix (sofabgen):** for the **decoder**, emit the full wire-type feature set
(`array` + `fixlen` + `fp64` + `sequence`, keeping the existing `value64`/width policy) regardless of
which wire types the schema declares — a skip path must exist for every wire type. **Corelib-side
alternative (implicated other end):** make corelib-rs-no-std's skip path feature-independent
(read-and-discard any wire construct even when its decode-into-field arm is compiled out), so a
`--features fixlen,sequence` build stays §7.3-conformant. Either closes the divergence; the sofabgen
change is the smaller, schema-driven one and is where attribution says to start.
