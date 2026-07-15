#!/usr/bin/env sh
# Crucible limit-mode differential loop (crucible#10 / generator#102).
#
# Limit mode exercises the receiver-side decode caps (max_dyn_array_count /
# max_dyn_string_len / max_dyn_blob_len) that bind only schema-*unbounded* fields.
# It builds a HEAP-ONLY roster from the unbounded probe (schema/probe-dyn.sofab.yaml)
# with identical caps baked into every driver, then feeds the corpus/limits vectors
# and checks the roster agrees on A (under cap) vs L (over cap). Because the caps are
# identical across the roster, a disagreement is a real verdict finding — see
# oracle/canonical.md ("The fourth verdict `L`").
#
#   ./scripts/run-limits.sh          # cap = 8, corpus/limits
#   LIMITS=16 ./scripts/run-limits.sh
#   CORPUS=path ./scripts/run-limits.sh
#
# Roster (heap targets only): the fixed-capacity profiles — c, c-cpp, rust-nostd —
# refuse to generate an unbounded field, so they are out by construction. cpp now
# runs the FULL heap roster in every dimension: G-0009 / generator#112 (sofabgen
# 0.16.0 emitted the unbounded array as std::array<T,0>, decoding an accepted array
# to empty) is FIXED in sofabgen 0.16.1 (commit 7899c4b -> std::vector); verified
# 2026-07-15 that cpp matches the family on the arr vectors (under/at/over-cap) and
# on the old repro `03 03 07 08 09` -> `[7,8,9]`. cpp's string/blob caps were always
# correct.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CAP="${LIMITS:-8}"
CORPUS="${CORPUS:-$ROOT/corpus/limits}"

# Bootstrap vendor/ + tools/ if missing.
[ -x "$ROOT/tools/sofabgen" ] || "$ROOT/scripts/bootstrap.sh"

echo "==> building heap roster in limit mode (schema=probe-dyn, caps=$CAP)" >&2
# Every heap driver's build.sh reads SCHEMA + LIMITS from the environment.
export SCHEMA="$ROOT/schema/probe-dyn.sofab.yaml"
export LIMITS="$CAP"
GO_BIN=$(sh "$ROOT/drivers/go/build.sh")
RS_BIN=$(sh "$ROOT/drivers/rust/build.sh" rs)
CPP_BIN=$(sh "$ROOT/drivers/cpp/build.sh" cpp)
PYC_BIN=$(sh "$ROOT/drivers/python/build.sh" cython)
PYP_BIN=$(sh "$ROOT/drivers/python/build.sh" pure)
JAVA_BIN=$(sh "$ROOT/drivers/java/build.sh")
TS_BIN=$(sh "$ROOT/drivers/ts/build.sh")
CS_BIN=$(sh "$ROOT/drivers/cs/build.sh")
ZIG_BIN=$(sh "$ROOT/drivers/zig/build.sh")
unset SCHEMA LIMITS  # don't leak the limit config into anything downstream

for line in \
    "go:$GO_BIN" "rust-std:$RS_BIN" "cpp:$CPP_BIN" \
    "py-cython:$PYC_BIN" "py-pure:$PYP_BIN" "java:$JAVA_BIN" \
    "typescript:$TS_BIN" "csharp:$CS_BIN" "zig:$ZIG_BIN"; do
    echo "==> ${line%%:*}: ${line#*:}" >&2
done

# The full heap roster runs every dimension (arr included — G-0009 fixed @0.16.1).
ALL="--driver go:$GO_BIN --driver rust-std:$RS_BIN --driver cpp:$CPP_BIN \
     --driver py-cython:$PYC_BIN --driver py-pure:$PYP_BIN --driver java:$JAVA_BIN \
     --driver typescript:$TS_BIN --driver csharp:$CS_BIN --driver zig:$ZIG_BIN"

fail=0
run_dim() {
    dim="$1"; shift
    [ -d "$CORPUS/$dim" ] || { echo "==> [$dim] no vectors at $CORPUS/$dim — skipping" >&2; return; }
    n=$(find "$CORPUS/$dim" -type f -name '*.bin' | wc -l | tr -d ' ')
    echo "==> limit mode :: $dim dimension ($n vector(s))" >&2
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/comparator.py" --corpus "$CORPUS/$dim" --policy "$ROOT/oracle/policy.yaml" "$@" || fail=1
}

run_dim arr $ALL
run_dim str $ALL
run_dim blb $ALL

if [ "$fail" -ne 0 ]; then
    echo "==> limit mode: DIVERGENCE(S) found" >&2
    exit 1
fi
echo "==> limit mode: roster agrees across all dimensions" >&2
