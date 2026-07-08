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
echo "==> c:          $C_BIN" >&2
echo "==> go:         $GO_BIN" >&2
echo "==> rust-std:   $RS_BIN" >&2
echo "==> rust-nostd: $NOSTD_BIN" >&2
echo "==> cpp:        $CPP_BIN" >&2
echo "==> cpp-c-cpp:  $CCPP_BIN" >&2
echo "==> py-cython:  $PYC_BIN" >&2
echo "==> py-pure:    $PYP_BIN" >&2
echo "==> java:       $JAVA_BIN" >&2

echo "==> differential comparison over $(ls "$CORPUS" | wc -l) seed(s)" >&2
python3 "$ROOT/oracle/comparator.py" \
    --corpus "$CORPUS" \
    --policy "$ROOT/oracle/policy.yaml" \
    --driver "c:$C_BIN" \
    --driver "go:$GO_BIN" \
    --driver "rust-std:$RS_BIN" \
    --driver "rust-nostd:$NOSTD_BIN" \
    --driver "cpp:$CPP_BIN" \
    --driver "cpp-c-cpp:$CCPP_BIN" \
    --driver "py-cython:$PYC_BIN" \
    --driver "py-pure:$PYP_BIN" \
    --driver "java:$JAVA_BIN"
