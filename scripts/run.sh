#!/usr/bin/env sh
# Crucible Phase-1 differential loop: build every driver, then feed the seed
# corpus through all of them and report divergence.
#
#   ./scripts/run.sh                # build C + Go, compare on corpus/seeds
#   CORPUS=path ./scripts/run.sh    # use a different corpus dir
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/seeds}"

# Bootstrap vendor/ + tools/ if missing.
[ -x "$ROOT/tools/sofabgen" ] || "$ROOT/scripts/bootstrap.sh"

echo "==> building drivers" >&2
C_BIN=$(sh "$ROOT/drivers/c/build.sh")
GO_BIN=$(sh "$ROOT/drivers/go/build.sh")
RS_BIN=$(sh "$ROOT/drivers/rust/build.sh" rs)
NOSTD_BIN=$(sh "$ROOT/drivers/rust/build.sh" rs-no-std)
CPP_BIN=$(sh "$ROOT/drivers/cpp/build.sh" cpp)
CCPP_BIN=$(sh "$ROOT/drivers/cpp/build.sh" c-cpp)
PYC_BIN=$(sh "$ROOT/drivers/python/build.sh" cython)
PYP_BIN=$(sh "$ROOT/drivers/python/build.sh" pure)
JAVA_BIN=$(sh "$ROOT/drivers/java/build.sh")
TS_BIN=$(sh "$ROOT/drivers/ts/build.sh")
CS_BIN=$(sh "$ROOT/drivers/cs/build.sh")
ZIG_BIN=$(sh "$ROOT/drivers/zig/build.sh")
echo "==> c:          $C_BIN" >&2
echo "==> go:         $GO_BIN" >&2
echo "==> rust-std:   $RS_BIN" >&2
echo "==> rust-nostd: $NOSTD_BIN" >&2
echo "==> cpp:        $CPP_BIN" >&2
echo "==> cpp-c-cpp:  $CCPP_BIN" >&2
echo "==> py-cython:  $PYC_BIN" >&2
echo "==> py-pure:    $PYP_BIN" >&2
echo "==> java:       $JAVA_BIN" >&2
echo "==> typescript: $TS_BIN" >&2
echo "==> csharp:     $CS_BIN" >&2
echo "==> zig:        $ZIG_BIN" >&2

# The driver roster, shared by the comparator and the clusterer.
set -- \
    --driver "c:$C_BIN" \
    --driver "go:$GO_BIN" \
    --driver "rust-std:$RS_BIN" \
    --driver "rust-nostd:$NOSTD_BIN" \
    --driver "cpp:$CPP_BIN" \
    --driver "cpp-c-cpp:$CCPP_BIN" \
    --driver "py-cython:$PYC_BIN" \
    --driver "py-pure:$PYP_BIN" \
    --driver "java:$JAVA_BIN" \
    --driver "typescript:$TS_BIN" \
    --driver "csharp:$CS_BIN" \
    --driver "zig:$ZIG_BIN"

# Optional per-driver hang budget (seconds); unset → the tools compute
# max(30, 0.25 x corpus size). A hanging driver is a finding, not a wedged run.
TIMEOUT_ARG=""
[ -n "${TIMEOUT:-}" ] && TIMEOUT_ARG="--timeout $TIMEOUT"

if [ "${CLUSTER:-0}" = "1" ]; then
    # Reduce the divergences to root-cause clusters (best over a big fuzzed corpus).
    echo "==> clustering divergences over $(ls "$CORPUS" | grep -vc -e gitkeep -e "\.md$") input(s)" >&2
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/cluster.py" --corpus "$CORPUS" --top "${TOP:-20}" $TIMEOUT_ARG "$@"
else
    echo "==> differential comparison over $(ls "$CORPUS" | grep -vc -e gitkeep -e "\.md$") input(s)" >&2
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/comparator.py" --corpus "$CORPUS" --policy "$ROOT/oracle/policy.yaml" $TIMEOUT_ARG "$@"
fi
