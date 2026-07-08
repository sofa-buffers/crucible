#!/usr/bin/env sh
# Build a Crucible C++ replay driver for one corelib variant.
#
#   build.sh cpp     -> corelib-cpp    (pure C++20, header-only)
#   build.sh c-cpp   -> corelib-c-cpp  (C++ wrapper over the C corelib; compiles the C sources)
#
# Regenerates probe.hpp from the schema via sofabgen, then compiles driver.cpp
# against the variant's corelib. Emits the built binary path on stdout.
# Env: SANITIZE=1 (default) → ASan+UBSan; CXX (default g++), CC (default cc).
set -eu

VARIANT="${1:-cpp}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CXX="${CXX:-g++}"
CC="${CC:-cc}"

case "$VARIANT" in
    cpp)   CORELIB="$ROOT/vendor/corelib-cpp";   INC="-I$CORELIB/include";     CFG="targets: { cpp: {} }";              CSRC="" ;;
    c-cpp) CORELIB="$ROOT/vendor/corelib-c-cpp"; INC="-I$CORELIB/src/include"; CFG="targets: { cpp: { corelib: c-cpp } }"; CSRC="$CORELIB/src/object.c $CORELIB/src/istream.c $CORELIB/src/ostream.c" ;;
    *) echo "unknown variant '$VARIANT' (want: cpp | c-cpp)" >&2; exit 2 ;;
esac

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

GEN="$HERE/gen/$VARIANT"
OUT="$HERE/build/$VARIANT"
echo "==> [cpp:$VARIANT] generating probe types from schema" >&2
rm -rf "$GEN" "$OUT"; mkdir -p "$GEN" "$OUT"
printf '%s\n' "$CFG" > "$GEN/cfg.yaml"
"$SOFABGEN" --config "$GEN/cfg.yaml" --lang cpp --in "$ROOT/schema/probe.sofab.yaml" --out "$GEN" >&2

SAN=""
[ "${SANITIZE:-1}" = "1" ] && SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g"

# c-cpp compiles the C corelib sources (C99) with the same sanitizers, then links.
COBJS=""
if [ -n "$CSRC" ]; then
    echo "==> [cpp:$VARIANT] compiling corelib C sources" >&2
    for c in $CSRC; do
        o="$OUT/$(basename "$c" .c).o"
        # shellcheck disable=SC2086
        "$CC" -std=c11 -O1 $SAN -I"$CORELIB/src/include" -c "$c" -o "$o" >&2
        COBJS="$COBJS $o"
    done
fi

echo "==> [cpp:$VARIANT] compiling driver ($CXX${SAN:+, sanitized})" >&2
# shellcheck disable=SC2086
"$CXX" -std=c++20 -O1 -Wall $SAN -I"$GEN" $INC "$HERE/driver.cpp" $COBJS -o "$OUT/driver" >&2

echo "$OUT/driver"
