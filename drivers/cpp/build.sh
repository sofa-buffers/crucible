#!/usr/bin/env sh
# Build a Crucible C++ replay driver for one of the FOUR C++ configurations.
#
#   build.sh cpp        -> corelib-cpp    heap      (std::string / std::vector)
#   build.sh cpp-fixed  -> corelib-cpp    heap-free (FixedString / FixedBytes / InlineVector)
#   build.sh c-cpp      -> corelib-c-cpp  heap-free (the C corelib's default)
#   build.sh c-cpp-dyn  -> corelib-c-cpp  heap
#
# Two corelibs x both `allow_dynamic` settings (crucible#129). `allow_dynamic` used to
# be a c-cpp-only knob; generator#289 extended it to `corelib: cpp`, and corelib-cpp#70
# made readString/readBlob/StringSeq/BlobSeq storage-agnostic so the heap-free
# containers work there too. The heap-free path is a DIFFERENT branch inside the
# corelib's typed reads — it rejects an over-capacity payload against the container's
# capacity, not only against the declared maxlen, and its destination is address-stable
# and fixed-size, so truncation and over-long payloads exercise code the growable path
# never reaches.
#
# The wire format is byte-identical across all four, which is what makes them worth
# running side by side: the same schema and the same input MUST produce the same
# outcome in every configuration, so a divergence between them is a bug by
# construction. driver.cpp and materialize_gen.py need no variant handling — both are
# written against only the member API the storage flavours share.
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
CCPP_SRC="src/object.c src/istream.c src/ostream.c src/utf8.c"
case "$VARIANT" in
    cpp)       CORELIB="$ROOT/vendor/corelib-cpp";   INC="-I$CORELIB/include";     CFG="targets: { cpp: {} }";                                     CSRC=""; HASLIM="-DCRUCIBLE_HAS_LIMIT_EXCEEDED"; STRICT="" ;;
    cpp-fixed) CORELIB="$ROOT/vendor/corelib-cpp";   INC="-I$CORELIB/include";     CFG="targets: { cpp: { allow_dynamic: false } }";               CSRC=""; HASLIM="-DCRUCIBLE_HAS_LIMIT_EXCEEDED"; STRICT="" ;;
    c-cpp)     CORELIB="$ROOT/vendor/corelib-c-cpp"; INC="-I$CORELIB/src/include"; CFG="targets: { cpp: { corelib: c-cpp } }";                     CSRC=""; HASLIM=""; STRICT="-DSOFAB_ENABLE_STRICT_UTF8" ;;
    c-cpp-dyn) CORELIB="$ROOT/vendor/corelib-c-cpp"; INC="-I$CORELIB/src/include"; CFG="targets: { cpp: { corelib: c-cpp, allow_dynamic: true } }"; CSRC=""; HASLIM=""; STRICT="-DSOFAB_ENABLE_STRICT_UTF8" ;;
    *) echo "unknown variant '$VARIANT' (want: cpp | cpp-fixed | c-cpp | c-cpp-dyn)" >&2; exit 2 ;;
esac
# Both c-cpp configurations compile and link the C corelib's sources; only the
# generated field storage differs between them.
case "$VARIANT" in
    c-cpp|c-cpp-dyn) for _c in $CCPP_SRC; do CSRC="$CSRC $CORELIB/$_c"; done ;;
esac

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

# Limit mode (crucible#10 / generator#102): SCHEMA selects the schema; LIMITS bakes
# identical max_dyn_* caps into the generated code. Only `cpp` supports it, and it
# takes BOTH halves to qualify: a heap profile, because a fixed-capacity one cannot
# represent an unbounded field at all (that rules out cpp-fixed and c-cpp), and a
# corelib whose Error carries LimitExceeded, so the driver can emit the `L` verdict
# (that rules out c-cpp-dyn — the C wrapper's Error has no such code even though its
# storage is growable).
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
if [ -n "${LIMITS:-}" ] && [ "$VARIANT" != "cpp" ]; then
    echo "==> [cpp:$VARIANT] LIMITS is unsupported: needs a heap profile whose corelib reports LIMIT_EXCEEDED (only 'cpp')" >&2
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

# Generate the materialized-value walker (SOFAB_MATERIALIZE) from the schema
# descriptor — straight-line, schema-agnostic, variant-agnostic C++ that driver.cpp
# #includes. Regenerated every build so a schema change needs zero hand-editing.
echo "==> [cpp:$VARIANT] generating materialized walker (materialize_gen.inc)" >&2
python3 "$HERE/materialize_gen.py" "$GEN/materialize_gen.inc" "$SCHEMA" >&2

SAN=""
[ "${SANITIZE:-1}" = "1" ] && SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g"

# Limit mode (LIMITS set) runs against the *unbounded* probe-dyn schema, which has no
# §5.2 schema bounds — so the driver decodes with a bare feed there, not the generated
# try_decode (see driver.cpp). Signal it to the driver.
LIMMODE=""
[ -n "${LIMITS:-}" ] && LIMMODE="-DCRUCIBLE_LIMIT_MODE"

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
"$CXX" -std=c++20 -O1 -Wall $SAN $HASLIM $LIMMODE $STRICT -I"$GEN" $INC "$HERE/driver.cpp" $COBJS -o "$OUT/driver" >&2

echo "$OUT/driver"
