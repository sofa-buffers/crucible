#!/usr/bin/env sh
# Build the Crucible Go replay driver: regenerate the probe types from the schema
# via sofabgen into ./message, then `go build` against the vendored corelib-go.
#
# Emits the built binary path on stdout (last line); logs go to stderr.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-go"
GEN="$HERE/message"
OUT="$HERE/build"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

echo "==> [go] generating probe types from schema" >&2
rm -rf "$GEN"
"$SOFABGEN" --lang go --in "$ROOT/schema/probe.sofab.yaml" --out "$GEN" >&2

# Workaround for sofabgen G-0006 (docs/SOFABGEN.md): a blob field in a nested
# struct emits `bytes.Equal` into types.go without importing "bytes". Inject the
# missing import into any generated file that needs it. Remove once fixed upstream.
for f in "$GEN"/*.go; do
    if grep -q 'bytes\.' "$f" && ! grep -q '"bytes"' "$f"; then
        sed -i '0,/^import (/s//import (\n\t"bytes"/' "$f"
        echo "==> [go] G-0006 workaround: injected \"bytes\" import into $(basename "$f")" >&2
    fi
done

mkdir -p "$OUT"
echo "==> [go] go build" >&2
# GOFLAGS=-mod=mod so the committed require+replace resolves without `go mod tidy`.
( cd "$HERE" && GOFLAGS=-mod=mod GOTOOLCHAIN=local go build -o "$OUT/driver" . >&2 )

echo "$OUT/driver"
