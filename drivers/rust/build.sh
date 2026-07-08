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

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

OUT="$HERE/build/$VARIANT"
echo "==> [rust:$VARIANT] generating probe project from schema" >&2
rm -rf "$OUT"
mkdir -p "$OUT"
printf 'generic: { emit: project }\n%s\n' "$CFG" > "$OUT/cfg.yaml"
"$SOFABGEN" --config "$OUT/cfg.yaml" --lang rust --in "$ROOT/schema/probe.sofab.yaml" --out "$OUT" >&2

# Replace the generated JSON harness with our replay driver (preamble brings
# `Probe` into scope for the variant's crate layout).
printf "$PREAMBLE" > "$OUT/src/main.rs"
cat "$HERE/driver.rs" >> "$OUT/src/main.rs"

# Point the crate at the vendored corelib (the generated Cargo.toml has a
# ${SOFAB_RS_CORELIB} placeholder).
sed -i "s#\${SOFAB_RS_CORELIB}#$CORELIB#" "$OUT/Cargo.toml"

echo "==> [rust:$VARIANT] cargo build" >&2
( cd "$OUT" && cargo build -q >&2 )

echo "$OUT/target/debug/harness"
