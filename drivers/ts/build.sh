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
TSC="$CORELIB/node_modules/.bin/tsc"
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
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$BUILD/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang typescript --in "$SCHEMA" --out "$BUILD" >&2
cp "$HERE/driver.ts" "$BUILD/driver.ts"

# TYPE-CHECK BEFORE BUNDLING. esbuild strips types without checking them, so a
# corelib API change lands in the bundle intact and only fails when a record reaches
# the changed call — as a crash the comparator reports as a divergence, on whatever
# input happens to be first. Both breaks corelib-ts#161 caused here were of that shape:
# `new OStream()` lost its allocating form (the buffer is the caller's, §6.6) and threw
# on record #0, and `FlushSink` gained `(buffer, start, end)` coordinates, which the
# old one-argument sink would have silently read as "copy the whole window". tsc sees
# both at build time; nothing else in this build did.
[ -x "$TSC" ] || { echo "missing $TSC — corelib-ts devDependencies are not installed" >&2; exit 1; }
echo "==> [ts] type-check (driver + generated, against corelib source)" >&2
cat > "$BUILD/tsconfig.check.json" <<EOF
{
  "compilerOptions": {
    "noEmit": true,
    "strict": true,
    "target": "ES2022",
    "module": "Preserve",
    "moduleResolution": "bundler",
    "skipLibCheck": true,
    "typeRoots": ["$CORELIB/node_modules/@types"],
    "types": ["node"],
    "paths": { "@sofa-buffers/corelib": ["$SRC_ENTRY"] }
  },
  "files": ["driver.ts", "message.ts"]
}
EOF
"$TSC" -p "$BUILD/tsconfig.check.json" >&2

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
