# F-0004 — invalid UTF-8 in a string: four behaviors, driven by the string type

**Status:** ✅ **RESOLVED 2026-07-18** (sofabgen 0.18.0 + corelibs@main, Crucible
[#55](https://github.com/sofa-buffers/crucible/issues/55)). With the strict-UTF-8
check ON family-wide, an invalid-UTF-8 `string` is rejected `R invalid_msg` by **all
12 drivers** (was the 4-way raw/U+FFFD/empty/reject split); valid controls still
accept and round-trip. See the resolution section at the end. Spec basis:
`MESSAGE_SPEC.md` §8 (opt-in strict UTF-8 check, default-off allowed; conformance +
this fuzzer run it ON); implementation epic [generator#85](https://github.com/sofa-buffers/generator/issues/85).
**Found:** Phase 3, C-pacemaker → differential loop; **corrected** with a clean
isolate (the original write-up was skewed — see below)
**Axis:** verdict + accept_value (hard, when the check is on)

## The true split (clean isolate)

Reproducer `invalid_utf8.bin` = a well-formed message whose only anomaly is a
`nested.str` payload `41 ff 42` ("A", `0xff`, "B") — `0xff` alone is not valid
UTF-8. Feeding it to every driver:

| behavior | impls | why — the decode target's string type |
|---|---|---|
| **preserve raw** (`…41 ff 42…`) | c, cpp, cpp-c-cpp, **zig** | byte-container string, no UTF-8 check: `char[]`, `std::string`, `[]const u8` |
| **U+FFFD replace** (`…41 efbfbd 42…`) | java, csharp, **typescript** | Unicode string whose constructor replaces: `new String(b, UTF_8)`, `Encoding.UTF8.GetString`, `TextDecoder` |
| **empty / dropped** | rust-std, rust-nostd | Rust `String` via `from_utf8(..).unwrap_or_default()` (std) / `unwrap_or("")` (no-std) — the two profiles agree via the G-0002 fix ([#91](https://github.com/sofa-buffers/generator/pull/91)) |
| **reject** (`R invalid_msg`) | go, py | explicit strict check: Go `utf8.Valid(b)`; Python `bytes.decode("utf-8")` (strict by default) |

The behavior **falls out of the target string type**, not a deliberate corelib
choice: Unicode-string types (Rust/Java/C#/JS/Python `str`) cannot hold non-UTF-8
bytes at all, so they replace, empty, or reject; byte-container types (C/C++/Go/Zig)
carry raw bytes, and only Go (explicit `utf8.Valid`) and Python (strict `.decode`)
actually reject. (Rust's `str` yields **empty** rather than U+FFFD since the
G-0002 fix — see the dated update.)

## Correction to the original write-up

The first version claimed a 3-way split with TypeScript and Zig in the *reject*
camp. That was wrong: it was based on a **complex** pacemaker input where TS/Zig
rejected for *other* structural reasons — and all rejects look identical
(`R invalid_msg`) because the reject class is coarse. Isolated cleanly, **TS does
U+FFFD** and **Zig preserves raw**. Lesson: characterize a divergence with a
*minimal* input that isolates the one behavior, not a raw fuzzer finding.

## Update 2026-07-09 — rust-std moved to the empty camp (G-0002)

The G-0002 fix changed the std Rust string emit from `from_utf8_lossy` (U+FFFD)
to `from_utf8(..).unwrap_or_default()` (empty), so the two Rust profiles now
**agree** on invalid UTF-8 (both empty) — codegen weakness **G-0002**
([generator#80](https://github.com/sofa-buffers/generator/issues/80) /
[PR #91](https://github.com/sofa-buffers/generator/pull/91), shipped sofabgen
0.15.1). This is the *intra-Rust* fix, distinct from the *family-wide*
strict-UTF-8 policy this finding tracks (§8 / #85).

**Verified empirically** at the current generator (sofabgen 0.15.2) by re-running
the same reproducer through the built Rust drivers: `rust-std` and `rust-nostd`
now emit **byte-identical** output (`A 5607a606560707c60c07`), where before
rust-std embedded `efbfbd` (U+FFFD).
Net effect on the split: rust-std leaves the U+FFFD row and joins rust-nostd in
the empty row. The **family** is still 4-way divergent (raw / U+FFFD / empty /
reject) until the corelibs adopt the opt-in `SOFAB_STRICT_UTF8` check (#85), so
F-0004's status is unchanged — only the camp membership above.

## Resolution — MESSAGE_SPEC.md §8

`string` is UTF-8; `blob` is the type for opaque bytes. The **strict, conformant**
behavior is to reject invalid UTF-8 as `INVALID` (§7). Because validation has a
cost and several native string types don't check, the corelib **MAY gate the
check behind a config flag that MAY default OFF**:

- **check on** → reject invalid UTF-8 (family-uniform, conformant);
- **check off** (default allowed) → implementation-defined (raw bytes, or the
  Unicode type's replacement) — zero-cost decode, outside the strict contract.

Conformance testing and this differential fuzzer run with the check **on**, so all
implementations agree.

**Implementation tracked:** [generator#85](https://github.com/sofa-buffers/generator/issues/85)
(epic: `SOFAB_STRICT_UTF8` flag + check across corelibs, codegen call sites for
rust/java/cs/zig, and Crucible verification). The check's *placement* follows each
corelib's memory model — corelib-internal where the corelib builds the string
(c/cpp/go/py/ts), codegen-invoked where the generated code builds it
(rust/java/cs/zig).

## Resolution 2026-07-18 — strict UTF-8 ON family-wide (sofabgen 0.18.0, crucible#55)

The `SOFAB_STRICT_UTF8` epic (generator#85) landed across the whole family:
**sofabgen 0.18.0** ships the codegen call sites for rust/java/cs/zig
([generator#162](https://github.com/sofa-buffers/generator/pull/162)); the
corelib-internal builders (c/cpp/go/py/ts) enforce it directly (per-corelib PRs).
Default strict-state per corelib: **ON** for go/zig/cpp and the Unicode-typed
corelibs (py/ts/java/cs/rs/rs-no-std, always strict); **OFF (footprint)** only for
the C corelib (`corelib-c-cpp`), which must opt in with `-DSOFAB_ENABLE_STRICT_UTF8`.

**Crucible side (this repo):**
- **Drivers built with the check ON.** The two corelib-c-cpp-based drivers opt in:
  `drivers/c/build.sh` and `drivers/cpp/build.sh` (`c-cpp` variant) add
  `-DSOFAB_ENABLE_STRICT_UTF8` and compile `corelib-c-cpp/src/utf8.c` (defines
  `sofab_utf8_valid`). The zig driver supplies the `build_options.strict_utf8=true`
  module its `zig build-exe` needs (corelib-zig reads it via `@import`). All others
  are strict by default — no change.
- **Seeds:** `engine/structured/utf8_seeds.py` embeds each malformed form as the
  `nested.str` payload of an otherwise-valid `probe`, reusing corelib-c-cpp's
  `assets/test_vectors.json` `invalid_utf8` group (11 vectors: overlong incl.
  `C0 80`, lone surrogate D800/DFFF, `> U+10FFFF`, bare continuation / lone `0xFF`,
  truncated 2-/3-byte) + 3 valid controls (`é`, `€`, ASCII).
- **Verified green family-wide.** All 11 malformed vectors → **all 12 drivers `R
  invalid_msg`**; all 3 valid controls → **all 12 `A`** and round-trip identically
  (no lossy U+FFFD). Promoted the 14 seeds into `corpus/regression/` (gate 29 → 43).

**Note — embedded U+0000 (out of scope here).** Embedded NUL is *valid* UTF-8 and is
correctly **accepted** by all 12 (the strict check does not over-reject). It is kept
out of the green gate because the C object API re-encodes `A\0B` → `A` (NUL-terminated
`char[]` storage) — a *value* divergence on a separate axis, tracked as **F-0018**,
which is classified **by-design** (a NUL-terminated C-string profile projects to
first-NUL; an allowed divergence in `oracle/policy.yaml`, not a bug).
