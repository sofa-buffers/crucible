#!/usr/bin/env sh
# Build a Crucible Rust replay driver for one corelib variant.
#
#   build.sh rs         -> corelib-rs        (std, maxspeed)
#   build.sh rs-no-std  -> corelib-rs-no-std (no_std, embedded)
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
               PREAMBLE='mod message;\nuse message::Probe;\n' ;;
    rs-no-std) CORELIB="$ROOT/vendor/corelib-rs-no-std"; CFG="targets: { rust: { corelib: rs-no-std } }";
               PREAMBLE='use sofabuffers_generated::Probe;\n' ;;
    *) echo "unknown variant '$VARIANT' (want: rs | rs-no-std)" >&2; exit 2 ;;
esac

# Limit mode (crucible#10 / generator#102): SCHEMA selects the schema (default the
# bounded probe); LIMITS, when set, bakes identical max_dyn_* caps into the
# generated code so an unbounded field over the cap decodes to LIMIT_EXCEEDED (the
# `L` verdict). Only the std corelib (rs) supports it — rs-no-std is fixed-capacity
# and cannot represent an unbounded field, and its Error has no LimitExceeded.
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
if [ -n "${LIMITS:-}" ] && [ "$VARIANT" = "rs-no-std" ]; then
    echo "==> [rust:rs-no-std] LIMITS is unsupported: the fixed-capacity profile has no unbounded fields" >&2
    exit 2
fi

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
