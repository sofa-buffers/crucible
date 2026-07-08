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
"$SOFABGEN" --lang zig --in "$ROOT/schema/probe.sofab.yaml" --out "$BUILD" >&2  # writes $BUILD/src/message.zig
cp "$HERE/driver.zig" "$BUILD/src/driver.zig"

echo "==> [zig] zig build-exe (ReleaseSafe: safety checks stay on)" >&2
"$ZIG" build-exe \
    --dep sofab -Mroot="$BUILD/src/driver.zig" \
    -Msofab="$CORELIB/src/root.zig" \
    -femit-bin="$BUILD/driver" \
    -OReleaseSafe >&2

echo "$BUILD/driver"
