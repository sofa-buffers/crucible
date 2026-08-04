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
# The roster — who is in the family — is stated once, in drivers/roster, and read by
# every consumer through scripts/roster.sh. `build` builds each entry and prints the
# comparator's `--driver name:path` arguments, one per line.
#
# A gate selects the `blocking` tag; `ROSTER_TAG=` (empty) selects the whole roster,
# quarantine included, which is how a quarantined driver is exercised. `-` not `:-`,
# so an explicitly empty value means "everything" rather than falling back.
ROSTER_TAG="${ROSTER_TAG-blocking}"
DRIVER_ARGS=$("$ROOT/scripts/roster.sh" build "$ROSTER_TAG")
_oldifs=$IFS
IFS='
'
# shellcheck disable=SC2086
set -- $DRIVER_ARGS
IFS=$_oldifs

# Optional per-driver hang budget (seconds); unset → the tools compute
# max(30, 0.25 x corpus size). A hanging driver is a finding, not a wedged run.
TIMEOUT_ARG=""
[ -n "${TIMEOUT:-}" ] && TIMEOUT_ARG="--timeout $TIMEOUT"

# MINIMIZE=<datei>: shrink one input while its camp partition holds, using the roster
# above. Same reason cluster.py takes --driver: the roster lives in exactly one place.
if [ -n "${MINIMIZE:-}" ]; then
    OUT="${MINIMIZE_OUT:-${MINIMIZE%.bin}.min.bin}"
    echo "==> minimizing $MINIMIZE -> $OUT" >&2
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/minimize.py" --input "$MINIMIZE" --output "$OUT" "$@"
    exit $?
fi

if [ "${CLUSTER:-0}" = "1" ]; then
    # Reduce the divergences to root-cause clusters (best over a big fuzzed corpus).
    echo "==> clustering divergences over $(ls "$CORPUS" | grep -vc -e gitkeep -e "\.md$") input(s)" >&2
    # shellcheck disable=SC2086
    # BASELINE=<file>: diff every camp against the accounted-for set; a camp that is
    # not in it exits non-zero (see results/known-clusters.txt for why).
    BASE_ARG=""
    [ -n "${BASELINE:-}" ] && BASE_ARG="--baseline $BASELINE"
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/cluster.py" --corpus "$CORPUS" --top "${TOP:-20}" $TIMEOUT_ARG $BASE_ARG "$@"
else
    echo "==> differential comparison over $(ls "$CORPUS" | grep -vc -e gitkeep -e "\.md$") input(s)" >&2
    # shellcheck disable=SC2086
    python3 "$ROOT/oracle/comparator.py" --corpus "$CORPUS" --policy "$ROOT/oracle/policy.yaml" $TIMEOUT_ARG "$@"
fi
