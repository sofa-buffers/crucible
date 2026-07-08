#!/usr/bin/env sh
# Run the Crucible C pacemaker — the coverage-guided fuzzing engine (PLAN §3).
#
# Builds the C driver's libFuzzer front-end (clang -fsanitize=fuzzer,address,
# undefined; the `CRUCIBLE_LIBFUZZER` path in drivers/c/driver.c) and runs it,
# seeded from corpus/seeds + accumulated corpus/interesting + the findings
# reproducers. New coverage-increasing inputs grow corpus/interesting/; crashes
# land in corpus/crashes/. Feed the grown corpus through all drivers with
#   CORPUS=corpus/interesting ./scripts/run.sh
# to turn coverage discoveries into differential findings.
#
# Env:
#   FUZZ_TIME=<seconds>   wall-clock budget (default 120)
#   FUZZ_JOBS=<n>         parallel libFuzzer jobs (default 1)
#   CC=clang              needs a libFuzzer-capable clang (devcontainer)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-c-cpp"
CC="${CC:-clang}"
FUZZ_TIME="${FUZZ_TIME:-120}"
FUZZ_JOBS="${FUZZ_JOBS:-1}"

GEN="$ROOT/drivers/c/fuzz-gen"
BIN="$ROOT/drivers/c/build/pacemaker"
CORP="$ROOT/corpus/interesting"
CRASH="$ROOT/corpus/crashes"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
if ! command -v "$CC" >/dev/null || ! "$CC" --version 2>/dev/null | grep -qi clang; then
    echo "error: the pacemaker needs a libFuzzer-capable clang (set CC=clang; use the devcontainer)." >&2
    exit 1
fi

echo "==> [pacemaker] generating C types from schema" >&2
rm -rf "$GEN"; mkdir -p "$GEN" "$CORP" "$CRASH" "$ROOT/drivers/c/build"
"$SOFABGEN" --lang c --in "$ROOT/schema/probe.sofab.yaml" --out "$GEN" >&2

echo "==> [pacemaker] building libFuzzer target (clang: fuzzer+ASan+UBSan)" >&2
"$CC" -DCRUCIBLE_LIBFUZZER -std=c11 -O1 -g \
    -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer \
    -I"$GEN" -I"$CORELIB/src/include" \
    "$ROOT/drivers/c/driver.c" "$GEN/probe.c" \
    "$CORELIB/src/object.c" "$CORELIB/src/istream.c" "$CORELIB/src/ostream.c" \
    -o "$BIN" >&2

echo "==> [pacemaker] fuzzing ${FUZZ_TIME}s (corpus: corpus/interesting; seeds: corpus/seeds + findings)" >&2
# First positional dir is the writable corpus; the rest are read-only seed dirs.
SEEDS="$ROOT/corpus/seeds"
FINDINGS=""
for d in "$ROOT"/findings/*/; do [ -d "$d" ] && FINDINGS="$FINDINGS $d"; done
# shellcheck disable=SC2086
ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=0}" \
"$BIN" "$CORP" "$SEEDS" $FINDINGS \
    -max_total_time="$FUZZ_TIME" -jobs="$FUZZ_JOBS" -print_final_stats=1 \
    -artifact_prefix="$CRASH/" 2>&1 | grep -iE "^#|cov:|NEW|crash|ERROR|DONE|stat::|SUMMARY" || true

echo "==> [pacemaker] corpus/interesting: $(ls "$CORP" | grep -vc gitkeep) inputs; crashes: $(ls "$CRASH" | grep -vc gitkeep)" >&2
echo "==> next: CORPUS=corpus/interesting ./scripts/run.sh   # differential over the grown corpus" >&2
