#!/usr/bin/env sh
# Crucible materialized-value oracle (oracle/materialized.md) — the element-access
# differential.
#
# Where scripts/run.sh compares the round-trip re-encoding (schema-agnostic, but blind
# to a decode that differs only where the sparse-canonical wire elides — canonical.md
# §Tradeoff), this runs every materialize-capable driver with SOFAB_MATERIALIZE=1 so
# each emits a full walk of the DECODED value (every field + every array element) as
# its `A` payload. The comparator diffs that payload exactly as it does the hex, on the
# same hard accept_value axis — no comparator change.
#
#   ./scripts/materialize.sh                 # over corpus/structured (the value-rich gate)
#   CORPUS=path ./scripts/materialize.sh     # a different corpus
#
# The full 12-driver roster emits the SOFAB_MATERIALIZE dump. C is the schema-agnostic
# anchor (object-descriptor walk); the others carry a schema-type table until a generated
# one lands. engine/structured/materialize.py is the conformance ground truth (a
# family-wide-wrong dump is agreement-green but reference-red).
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/structured}"

[ -x "$ROOT/tools/sofabgen" ] || "$ROOT/scripts/bootstrap.sh"

echo "==> [materialize] building the 12-driver roster" >&2
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

TIMEOUT_ARG=""
[ -n "${TIMEOUT:-}" ] && TIMEOUT_ARG="--timeout $TIMEOUT"

echo "==> [materialize] differential over $(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$') input(s) — SOFAB_MATERIALIZE=1" >&2
# The comparator inherits the environment, so the drivers see SOFAB_MATERIALIZE.
# shellcheck disable=SC2086
SOFAB_MATERIALIZE=1 python3 "$ROOT/oracle/comparator.py" \
    --corpus "$CORPUS" --policy "$ROOT/oracle/policy.yaml" $TIMEOUT_ARG "$@"

echo "==> [materialize] conformance check vs the reference (engine/structured/materialize.py)" >&2
echo "    (a differential-green but reference-red result = a family-wide-wrong dump)" >&2
