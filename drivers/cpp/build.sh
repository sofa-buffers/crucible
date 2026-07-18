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

# HASLIM: the pure-C++ corelib's sofab::Error carries LimitExceeded (the heap
# profile, generator#102); the c-cpp wrapper's Error does NOT (fixed-capacity), so
# the shared driver.cpp guards its L verdict behind this macro. Only the cpp variant
# is in limit mode — the c-cpp fixed-capacity profile cannot generate an unbounded
# field (see scripts/run-limits.sh).
# STRICT: strict UTF-8 (MESSAGE_SPEC §8 / CORELIB_PLAN §6.4). The fuzzer runs the
# check ON so an invalid-UTF-8 `string` is family-uniformly rejected (F-0004). The
# pure-C++ corelib (cpp) defaults SOFAB_STRICT_UTF8=1 already; only the c-cpp
# (C-corelib) profile defaults OFF for footprint and must opt in explicitly.
case "$VARIANT" in
    cpp)   CORELIB="$ROOT/vendor/corelib-cpp";   INC="-I$CORELIB/include";     CFG="targets: { cpp: {} }";              CSRC=""; HASLIM="-DCRUCIBLE_HAS_LIMIT_EXCEEDED"; STRICT="" ;;
    c-cpp) CORELIB="$ROOT/vendor/corelib-c-cpp"; INC="-I$CORELIB/src/include"; CFG="targets: { cpp: { corelib: c-cpp } }"; CSRC="$CORELIB/src/object.c $CORELIB/src/istream.c $CORELIB/src/ostream.c $CORELIB/src/utf8.c"; HASLIM=""; STRICT="-DSOFAB_ENABLE_STRICT_UTF8" ;;
    *) echo "unknown variant '$VARIANT' (want: cpp | c-cpp)" >&2; exit 2 ;;
esac

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

# Limit mode (crucible#10 / generator#102): SCHEMA selects the schema; LIMITS bakes
# identical max_dyn_* caps into the generated code. Only the pure-C++ (cpp) variant
# supports it — the c-cpp fixed-capacity profile cannot represent an unbounded field.
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
if [ -n "${LIMITS:-}" ] && [ "$VARIANT" = "c-cpp" ]; then
    echo "==> [cpp:c-cpp] LIMITS is unsupported: the fixed-capacity profile has no unbounded fields" >&2
    exit 2
fi

GEN="$HERE/gen/$VARIANT"
OUT="$HERE/build/$VARIANT"
echo "==> [cpp:$VARIANT] generating probe types from ${SCHEMA##*/}${LIMITS:+ (limits=$LIMITS)}" >&2
rm -rf "$GEN" "$OUT"; mkdir -p "$GEN" "$OUT"
printf '%s\n' "$CFG" > "$GEN/cfg.yaml"
if [ -n "${LIMITS:-}" ]; then
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" >> "$GEN/cfg.yaml"
fi
"$SOFABGEN" --config "$GEN/cfg.yaml" --lang cpp --in "$SCHEMA" --out "$GEN" >&2

SAN=""
[ "${SANITIZE:-1}" = "1" ] && SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g"

# c-cpp compiles the C corelib sources (C99) with the same sanitizers, then links.
COBJS=""
if [ -n "$CSRC" ]; then
    echo "==> [cpp:$VARIANT] compiling corelib C sources" >&2
    for c in $CSRC; do
        o="$OUT/$(basename "$c" .c).o"
        # shellcheck disable=SC2086
        "$CC" -std=c11 -O1 $SAN $STRICT -I"$CORELIB/src/include" -c "$c" -o "$o" >&2
        COBJS="$COBJS $o"
    done
fi

echo "==> [cpp:$VARIANT] compiling driver ($CXX${SAN:+, sanitized})" >&2
# shellcheck disable=SC2086
"$CXX" -std=c++20 -O1 -Wall $SAN $HASLIM $STRICT -I"$GEN" $INC "$HERE/driver.cpp" $COBJS -o "$OUT/driver" >&2

echo "$OUT/driver"
