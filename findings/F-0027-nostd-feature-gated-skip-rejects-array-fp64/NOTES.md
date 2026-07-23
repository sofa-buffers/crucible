# F-0027 — rust-nostd rejects a §7.3-skippable array / fp64 field the schema never declares

**Status:** 🔴 **OPEN** — **[generator#215](https://github.com/sofa-buffers/generator/issues/215)**
(sofabgen) with **`corelib-rs-no-std`** implicated (the "occasionally both" shape of F-0010). Found 2026-07-22 by the **WP-01 union pass** of the wiretype
(§7.3) sweep (`engine/structured/wiretype_sweep.py::emit_union`), the first time the sweep family ran
against a schema (`schema/probe-union.sofab.yaml`) that declares **no array and no fp field**.

**Axis:** wiretype (§7.3), union pass — verdict split. **Impls:** `rust-nostd` alone (1) vs the other
**12** (incl. `rust-std`, which shares the *same generated code*). Report-only; the union pass is **not**
promoted to blocking until this resolves.

## The split

Feed a well-formed field whose wire type its id does **not** map to (a §7.3 mismatch), or an unknown id,
carrying an **array** wire type (`VARINTARRAY_U/S`, `FIXLENARRAY` = wire types 3/4/5) or an **fp64**
fixlen subtype. §7.3 requires it to be **skipped** exactly like an unknown id; the message then decodes
as all-default (here: an empty union → `default_id`, re-encoded `0e07`).

| camp | behaviour | drivers |
|---|---|---|
| **skip** (conformant §7.3) | field skipped → `A`, re-encodes `0e07` | c, go, rust-std, cpp, cpp-c-cpp, py-cython, py-pure, java, typescript, csharp, zig, dart (12) |
| **reject** | `R invalid_msg` | **rust-nostd (1)** |

The set that `rust-nostd` rejects is exactly **wire types 3/4/5 (all arrays)** and **fixlen subtype fp64**.
It skips `U`, `S`, `SEQ`, and fixlen `fp32`/`string`/`blob` fine — including an **8-byte blob**, the same
payload length as the rejected fp64, so it is the *subtype*, not the length.

## Reproducers, byte for byte  (run against `schema/probe-union.sofab.yaml`)

| file | bytes | meaning | rust-nostd | others |
|---|---|---|---|---|
| `skip_arr_empty.bin` | `0300` | id0, `VARINTARRAY_U`, count 0 — **minimal, 2 B** | `R` | `A` |
| `skip_arr_u.bin` | `030105` | id0, `VARINTARRAY_U`, count 1, value 5 | `R` | `A` |
| `skip_arr_fp64.bin` | `050141…f83f` | id0, `FIXLENARRAY`, one fp64 `1.5` | `R` | `A` |
| `skip_fix_fp64.bin` | `0241` + 8 B | id0, `FIXLEN` subtype fp64 (len 8) | `R` | `A` |
| `control_fix_fp32.bin` | `022000000000` | id0, `FIXLEN` subtype fp32 (len 4) | `A` | `A` |
| `control_fix_blob8.bin` | `0243` + 8×`11` | id0, `FIXLEN` subtype blob, **len 8** | `A` | `A` |
| `control_scalar.bin` | `0005` | id0 = tag (u32) = 5 — a real field decodes | `A` | `A` |

`control_fix_blob8` vs `skip_fix_fp64` isolate the trigger to the **fp64 subtype** (same 8-byte payload,
one skips, one rejects). The controls guarantee the mismatch is *only* the skippable wire type.

## Root cause — sofabgen provisions the corelib features from the schema's *used* wire types

corelib-rs-no-std is a streaming push-parser whose wire-type support is **cargo-feature-gated** (a
deliberate embedded code-size knob; `vendor/corelib-rs-no-std/Cargo.toml` `[features]`, README). In
`vendor/corelib-rs-no-std/src/istream.rs::on_header` the array arms are `#[cfg(feature = "array")]` and
fall through to `_ => Err(Error::InvalidMsg)` (istream.rs:331) when the feature is off; the fp64 fixlen
arm is `#[cfg(feature = "fp64")]` (istream.rs:386-392) and its subtype otherwise fails
`FixlenType::from_raw` (istream.rs:352). Skipping and decoding share this one dispatch — so a build
without `array`/`fp64` **cannot skip** those wire types, only reject them.

sofabgen (`--lang rust`, invoked at `drivers/rust/build.sh:53`) writes the driver's `Cargo.toml` and
selects the corelib feature set from the wire types the **schema declares**:

| schema | generated `sofab` dependency features | skip arr_u / fp64 |
|---|---|---|
| `probe` (has arrays + fp) | `["array","fixlen","fp64","sequence","value64"]` | ✅ `A` |
| `probe-union` (no array, no fp) | `["fixlen","sequence"]` | ❌ `R invalid_msg` |

(The feature list is sofabgen's, not `build.sh`'s — `build.sh` only ever appends the `limit` feature,
lines 83-88.) Because §7.3 skip-ability is **schema-independent** — any field can receive any wire type
as a mismatch, any unknown id can carry any construct — omitting `array`/`fp64` yields a
**§7.3-non-conformant decoder**. This is invisible on `probe` (arrays + fp64 are real fields, so the
features are on) and on every other language (none feature-gate wire-type *parsing*), and invisible to
`rust-std` (its corelib is not gated this way) — which is exactly why the sweep family had to reach a
union-only schema to surface it.

## Attribution — generator (sofabgen); corelib-rs-no-std implicated

CLAUDE.md triage — *does the corelib have the information to reject?* corelib-rs-no-std was **handed a
feature configuration** (`array`/`fp64` off) and faithfully compiled a decoder that rejects those wire
types (diagnostic step 2: "the corelib faithfully used what it was handed → the caller is the bug").
The schema→feature decision is made **only by codegen**, and only codegen writes the `Cargo.toml`. So the
fix starts in **sofabgen**: for the *decoder*, always enable the full wire-type feature set
(`array` + `fixlen` + `fp64` + `sequence`) regardless of which types the schema declares — a skip path
must exist for every wire type. → **G-0017** in [`results/FINDINGS.md`](../../results/FINDINGS.md), issue
against `generator`.

**The other side is implicated** (the F-0010 "occasionally both" caveat CLAUDE.md names): corelib-rs-no-std
feature-gates wire-type **parsing/skip**, not merely field *storage*, so the `["fixlen","sequence"]`
configuration is inherently non-conformant to §7.3. The robust corelib-side hardening is a
feature-independent *skip* path (read-and-discard any wire construct even when its decode-into-field arm
is compiled out). Either fix closes the divergence; the sofabgen one is the smaller, schema-driven change
and is where attribution says to start. Confirmed **not** a general corelib skip bug and **not** codegen
of the decode logic by the two-way sibling split (CLAUDE.md diagnostic step 3): `rust-std` (same generated
code, non-gated corelib) agrees with the family, and `rust-nostd` on `probe` (arrays/fp64 features on)
skips fine — only `probe-union` + no-std rejects.

## Reproduce

```sh
# built against probe-union (the union schema), NOT the default probe — go through run.sh
# so the roster is rebuilt for the right schema (never point the comparator at drivers/*/build/).
SCHEMA="$PWD/schema/probe-union.sofab.yaml" \
  CORPUS="$PWD/findings/F-0027-nostd-feature-gated-skip-rejects-array-fp64" \
  ./scripts/run.sh
# 7 inputs: 3 controls agree, 4 skip_* reproducers diverge (verdict) — rust-nostd 'R', 12 others 'A'.
# Restore the default binaries afterwards: CORPUS="$PWD/corpus/seeds" ./scripts/run.sh
```

## Regression-gate & promotion

Kept **out** of the blocking `corpus/regression/` gate and the union pass held **report-only**
(`scripts/sweep.sh`) until the generator fix lands — mirroring the F-0025/F-0026 arc. When it lands:
re-bootstrap (fresh sofabgen), rebuild `probe-union`, verify the wiretype union axis goes green
(all 13 skip), promote `skip_arr_empty.bin` (+ the `control_*` counter-direction) into the gate, and
flip the union wiretype axis to blocking in `scripts/sweep.sh` / `replay.yml`.
