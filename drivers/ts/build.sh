#!/usr/bin/env sh
# Build the Crucible TypeScript replay driver: regenerate the probe class from the
# schema via sofabgen, then bundle driver.ts + message.ts + corelib-ts SOURCE into
# one CJS file with esbuild. Emits an executable wrapper path on stdout.
#
# We bundle from the corelib's src/ (aliased) rather than its committed dist/ so
# the driver tests the current source and does not depend on a possibly-stale
# built dist. esbuild comes from corelib-ts's node_modules.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-ts"
BUILD="$HERE/build"
ESBUILD="$CORELIB/node_modules/.bin/esbuild"
SRC_ENTRY="$CORELIB/src/index.ts"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }
[ -f "$SRC_ENTRY" ] || { echo "missing $SRC_ENTRY (corelib-ts source)" >&2; exit 1; }
if [ ! -x "$ESBUILD" ]; then
    echo "==> [ts] installing corelib-ts deps (esbuild)" >&2
    ( cd "$CORELIB" && npm ci >&2 2>/dev/null || npm install >&2 )
fi

echo "==> [ts] generating probe class from schema" >&2
rm -rf "$BUILD"; mkdir -p "$BUILD"
"$SOFABGEN" --lang typescript --in "$ROOT/schema/probe.sofab.yaml" --out "$BUILD" >&2
cp "$HERE/driver.ts" "$BUILD/driver.ts"

echo "==> [ts] esbuild bundle (driver + message + corelib source)" >&2
"$ESBUILD" "$BUILD/driver.ts" \
    --bundle --platform=node --format=cjs \
    --alias:@sofa-buffers/corelib="$SRC_ENTRY" \
    --outfile="$BUILD/driver.cjs" \
    --log-level=warning >&2

WRAP="$BUILD/driver"
cat > "$WRAP" <<EOF
#!/bin/sh
exec node "$BUILD/driver.cjs"
EOF
chmod +x "$WRAP"

echo "$WRAP"
