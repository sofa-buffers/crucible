#!/usr/bin/env sh
# Build a Crucible Rust replay driver for one corelib variant.
#
#   build.sh rs             -> corelib-rs        (std, maxspeed)
#   build.sh rs-no-std      -> corelib-rs-no-std (no_std, embedded), heapless 0.8
#   build.sh rs-no-std-h09  -> the same, against heapless 0.9 (generator#727)
#
# The two no_std variants generate BYTE-IDENTICAL source — generator docs/generator/
# rust.md: "The generated source is the same for both ... and only Cargo.toml differs".
# They are worth running side by side anyway, because `heapless` is where this profile's
# bound enforcement lives: with `allow_dynamic: false` a schema-bounded field IS a
# `heapless::String<N>` / `Vec<T, N>`, which refuses on assignment instead of being
# guarded by generated code (generator ARCHITECTURE §9.6.1, and the `container` row in
# scripts/check-encode-bounds.py). Two majors are two implementations of that refusal,
# and of the decode-side fill above it, under one generated API — the same reason the
# four C++ rows and the two Python engines are in the roster. heapless 0.9 needs rustc
# 1.87, which the generated Cargo.toml declares, so an older toolchain is refused by
# cargo up front rather than failing inside heapless.
#
# Regenerates the probe project from the schema via sofabgen, swaps the generated
# JSON harness (src/main.rs) for our replay driver, points the crate at the
# vendored corelib, and `cargo build`s. Emits the built binary path on stdout.
set -eu

VARIANT="${1:-rs}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"

case "$VARIANT" in
    rs)        CORELIB="$ROOT/vendor/corelib-rs";        CFG="targets: { rust: {} }";
               PREAMBLE='mod message;\nuse message::{Probe, DecodeError};\n' ;;
    rs-no-std) CORELIB="$ROOT/vendor/corelib-rs-no-std"; CFG="targets: { rust: { corelib: rs-no-std } }";
               PREAMBLE='use sofabuffers_generated::{Probe, DecodeError};\n' ;;
    # The value must be QUOTED in the config: an unquoted 0.9 is a YAML number and the
    # config schema rejects it (generation fails rather than falling back to 0.8 — which
    # is the behaviour that makes this variant honest about what it tested).
    rs-no-std-h09) CORELIB="$ROOT/vendor/corelib-rs-no-std";
               CFG='targets: { rust: { corelib: rs-no-std, heapless: "0.9" } }';
               PREAMBLE='use sofabuffers_generated::{Probe, DecodeError};\n' ;;
    *) echo "unknown variant '$VARIANT' (want: rs | rs-no-std | rs-no-std-h09)" >&2; exit 2 ;;
esac

# Limit mode (crucible#10 / generator#102): SCHEMA selects the schema (default the
# bounded probe); LIMITS, when set, bakes identical max_dyn_* caps into the
# generated code so an unbounded field over the cap decodes to LIMIT_EXCEEDED (the
# `L` verdict). Only the std corelib (rs) supports it — rs-no-std is fixed-capacity
# and cannot represent an unbounded field, and its Error has no LimitExceeded.
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
case "${LIMITS:+set}:$VARIANT" in
    set:rs-no-std*)
        echo "==> [rust:$VARIANT] LIMITS is unsupported: the fixed-capacity profile has no unbounded fields" >&2
        exit 2 ;;
esac

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

OUT="$HERE/build/$VARIANT"
echo "==> [rust:$VARIANT] generating probe project from ${SCHEMA##*/}${LIMITS:+ (limits=$LIMITS)}" >&2
rm -rf "$OUT"
mkdir -p "$OUT"
# Merge the max_dyn_* caps into the generic block (block style so the caps sit
# alongside `emit: project`), mirroring the cpp backend's single-cfg approach.
{
    printf 'generic:\n  emit: project\n'
    if [ -n "${LIMITS:-}" ]; then
        printf '  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
            "$LIMITS" "$LIMITS" "$LIMITS"
    fi
    printf '%s\n' "$CFG"
} > "$OUT/cfg.yaml"
"$SOFABGEN" --config "$OUT/cfg.yaml" --lang rust --in "$SCHEMA" --out "$OUT" >&2

# Replace the generated JSON harness with our replay driver (preamble brings
# `Probe` into scope for the variant's crate layout).
printf "$PREAMBLE" > "$OUT/src/main.rs"
cat "$HERE/driver.rs" >> "$OUT/src/main.rs"

# Generate the materialized-value walker (SOFAB_MATERIALIZE path) from the schema
# descriptor and drop it beside main.rs, where driver.rs `include!`s it. Rust has no
# runtime reflection, so the walker is straight-line source unrolled from the
# descriptor — a schema change regenerates it here with no hand-editing. Runs every
# build ($OUT is wiped above), for both variants, from the one generator.
echo "==> [rust:$VARIANT] generating materialized walker (materialize_gen.rs)" >&2
python3 "$HERE/materialize_gen.py" "$OUT/src/materialize_gen.rs" "$SCHEMA"

# Point the crate at the vendored corelib (the generated Cargo.toml has a
# ${SOFAB_RS_CORELIB} placeholder).
sed -i "s#\${SOFAB_RS_CORELIB}#$CORELIB#" "$OUT/Cargo.toml"

# The `L` (LimitExceeded) verdict arm in driver.rs is std-only — declare + enable
# the `limit` cargo feature that gates it for the std corelib (rs) only. rs-no-std's
# Error has no LimitExceeded variant, so the arm must stay compiled out there.
#
# rs-no-std still needs the feature *declared* (not enabled): the arm uses
# `#[cfg(feature = "limit")]`, and an undeclared feature makes that an *unknown*
# cfg value — cargo's `unexpected_cfgs` lint then warns on every rs-no-std build
# (noise that can mask real warnings). Declaring it silences the lint while the arm
# stays compiled out (the feature is never enabled for rs-no-std).
FEATURES=""
if [ "$VARIANT" = "rs" ]; then
    printf '\n[features]\nlimit = []\n' >> "$OUT/Cargo.toml"
    FEATURES="--features limit"
elif grep -q '^\[features\]' "$OUT/Cargo.toml"; then
    sed -i '/^\[features\]/a limit = []' "$OUT/Cargo.toml"   # declare, don't enable
else
    printf '\n[features]\nlimit = []\n' >> "$OUT/Cargo.toml"
fi

echo "==> [rust:$VARIANT] cargo build${FEATURES:+ ($FEATURES)}" >&2
# shellcheck disable=SC2086
( cd "$OUT" && cargo build -q $FEATURES >&2 )

echo "$OUT/target/debug/harness"
