#!/usr/bin/env sh
# Build the Crucible C replay driver: regenerate the probe types from the schema
# via sofabgen, then compile the driver + generated code against corelib-c-cpp.
#
# Emits the built binary path on stdout (last line); logs go to stderr.
# Env:
#   SANITIZE=1   (default) build with ASan+UBSan   [needs a sanitizer-capable gcc/clang]
#   SANITIZE=0   plain build
#   CC=...       compiler (default: cc)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-c-cpp"
GEN="$HERE/gen"
OUT="$HERE/build"
CC="${CC:-cc}"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB/src/include" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

echo "==> [c] generating probe types from schema" >&2
rm -rf "$GEN"
# SCHEMA overrides the default full-scale probe (e.g. schema/probe-union.sofab.yaml
# for the union suite); the driver is schema-agnostic (round-trip form), so only the
# generated types change.
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
"$SOFABGEN" --lang c --in "$SCHEMA" --out "$GEN" >&2

mkdir -p "$OUT"
SAN=""
if [ "${SANITIZE:-1}" = "1" ]; then
    SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g"
fi

# Strict UTF-8 (MESSAGE_SPEC §8 / CORELIB_PLAN §6.4): the C corelib defaults the
# check OFF (footprint), so the fuzzer must opt in — otherwise an invalid-UTF-8
# `string` is accepted here while the strict family rejects it (F-0004). Pulls in
# utf8.c (defines sofab_utf8_valid, referenced by istream.c/ostream.c under the flag).
echo "==> [c] compiling replay driver ($CC${SAN:+, sanitized}, strict UTF-8)" >&2
# shellcheck disable=SC2086
"$CC" -std=c11 -O1 -Wall -Wextra $SAN -DSOFAB_ENABLE_STRICT_UTF8 \
    -I"$GEN" -I"$CORELIB/src/include" \
    "$HERE/driver.c" "$GEN/probe.c" \
    "$CORELIB/src/object.c" "$CORELIB/src/istream.c" "$CORELIB/src/ostream.c" "$CORELIB/src/utf8.c" \
    -o "$OUT/driver" >&2

echo "$OUT/driver"
