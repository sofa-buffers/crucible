#!/usr/bin/env sh
# Build the Crucible Zig replay driver: regenerate the probe module from the
# schema via sofabgen, then `zig build-exe` driver.zig with the corelib wired in
# as the `sofab` module. Emits the built binary path on stdout.
#
# Module wiring (Zig 0.16 CLI): the root module (driver.zig) depends on `sofab`,
# defined from the corelib's src/root.zig. driver.zig file-imports message.zig,
# whose `@import("sofab")` resolves via the root module's dep.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-zig"
BUILD="$HERE/build"
ZIG="${ZIG:-zig}"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -f "$CORELIB/src/root.zig" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }
command -v "$ZIG" >/dev/null || { echo "zig not found on PATH" >&2; exit 1; }

echo "==> [zig] generating probe module from schema" >&2
rm -rf "$BUILD"; mkdir -p "$BUILD/src"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$BUILD/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang zig --in "$SCHEMA" --out "$BUILD" >&2  # writes $BUILD/src/message.zig
cp "$HERE/driver.zig" "$BUILD/src/driver.zig"

# Generate the schema-agnostic materialized-value walker from the descriptor
# (oracle/materialized-schema.json) — regenerated every build so a schema change
# reshapes the walker with zero hand-editing. driver.zig @import("materialize_gen.zig")
# resolves to this file (same $BUILD/src dir as the copied driver.zig).
echo "==> [zig] generating materialized-value walker from descriptor" >&2
python3 "$HERE/materialize_gen.py" "$BUILD/src/materialize_gen.zig" >&2

# Strict UTF-8 (MESSAGE_SPEC §8 / CORELIB_PLAN §6.4): corelib-zig's utf8.zig reads
# `@import("build_options").strict_utf8`, a module `build.zig` supplies via
# addOptions. We build the corelib as a bare module with `zig build-exe` (no
# build.zig), so we synthesize that module here. The fuzzer runs the check ON
# (zig's own default), so an invalid-UTF-8 string is rejected family-uniformly.
printf 'pub const strict_utf8: bool = true;\n' > "$BUILD/src/build_options.zig"

echo "==> [zig] zig build-exe (ReleaseSafe: safety checks stay on)" >&2
"$ZIG" build-exe \
    --dep sofab -Mroot="$BUILD/src/driver.zig" \
    --dep build_options -Msofab="$CORELIB/src/root.zig" \
    -Mbuild_options="$BUILD/src/build_options.zig" \
    -femit-bin="$BUILD/driver" \
    -OReleaseSafe >&2

echo "$BUILD/driver"
