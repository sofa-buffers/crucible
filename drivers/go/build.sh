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
mkdir -p "$GEN"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$GEN/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang go --in "$SCHEMA" --out "$GEN" >&2

mkdir -p "$OUT"
echo "==> [go] go build" >&2
# GOFLAGS=-mod=mod so the committed require+replace resolves without `go mod tidy`.
# -buildvcs=false: don't stamp git VCS info into the driver binary — a fuzz driver
# doesn't need it, and in a CI container the checkout's ownership mismatch makes
# `go build`'s VCS probe fail ("error obtaining VCS status: exit status 128").
( cd "$HERE" && GOFLAGS=-mod=mod GOTOOLCHAIN=local go build -buildvcs=false -o "$OUT/driver" . >&2 )

echo "$OUT/driver"
