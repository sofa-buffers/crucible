#!/usr/bin/env sh
# Build the Crucible Dart replay driver: regenerate the probe types from the
# schema via sofabgen (--lang dart), wire the vendored corelib-dart in via a pub
# path dependency, `dart pub get`, and AOT-compile the driver to a native exe.
#
# Emits the built binary path on stdout (last line); logs go to stderr.
#
# Honors SCHEMA (union/dyn schemas) and LIMITS (limit mode caps) from the
# environment, exactly like the peer build.sh scripts.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-dart"
OUT="$HERE/build"
BIN="$OUT/bin"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }
command -v dart >/dev/null 2>&1 || { echo "missing dart SDK (see .devcontainer)" >&2; exit 1; }

echo "==> [dart] generating probe types from schema" >&2
rm -rf "$OUT"
mkdir -p "$BIN"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$OUT/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang dart --in "$SCHEMA" --out "$BIN" >&2

# The driver source lives beside the generated message.dart (one package dir), so
# its `import 'message.dart';` resolves relatively.
cp "$HERE/driver.dart" "$BIN/driver.dart"

# A minimal package with a path dependency on the vendored corelib. dev deps of
# the corelib (test/lints) are not fetched transitively, so pub get needs nothing
# hosted.
cat > "$OUT/pubspec.yaml" <<EOF
name: crucible_dart_driver
description: Crucible replay driver for corelib-dart.
publish_to: none
environment:
  sdk: ^3.8.0
dependencies:
  sofabuffers:
    path: $CORELIB
EOF

echo "==> [dart] pub get" >&2
( cd "$OUT" && dart pub get >&2 )

echo "==> [dart] compile exe" >&2
( cd "$OUT" && dart compile exe bin/driver.dart -o "$OUT/driver" >&2 )

echo "$OUT/driver"
