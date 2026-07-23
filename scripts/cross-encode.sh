#!/usr/bin/env sh
# Crucible cross-encode / structured-value oracle (PLAN §6, 3rd oracle).
#
# The malformed track (mutator + hand seeds) feeds *wire* and mostly exercises
# decoders on reject/incomplete paths. This suite instead generates *valid,
# value-rich* messages (float specials, unicode, boundary ints) and runs them
# through the existing round-trip + decode-agreement oracle. Because the family is
# byte-canonical (every encoder emits identical wire for a value), "encode in A,
# decode in B, compare" reduces to "all drivers must emit the same A <hex>" — so a
# divergence here is a real encoder/decoder asymmetry between languages.
#
# Two passes: the full-scale `probe` value space, and (WP-02) the `union` value space
# over schema/probe-union.sofab.yaml — each union member at boundary values, the
# default_id case, and tag+member+trailer combos. The union pass rebuilds the roster
# against probe-union and restores probe binaries after (the SCHEMA-switch discipline,
# as scripts/sweep.sh and run-union.sh do).
#
#   ./scripts/cross-encode.sh          # regenerate both corpora, run both differentials
#   REGEN=0 ./scripts/cross-encode.sh  # skip regeneration, just re-run
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ "${REGEN:-1}" = "1" ]; then
    python3 "$ROOT/engine/structured/gen.py" "$ROOT/corpus/structured"
    python3 "$ROOT/engine/structured/gen.py" --union "$ROOT/corpus/structured-union"
fi

echo "==> [cross-encode] probe value differential (corpus/structured)" >&2
CORPUS="$ROOT/corpus/structured" "$ROOT/scripts/run.sh" "$@"

echo "==> [cross-encode] union value differential (corpus/structured-union, probe-union)" >&2
SCHEMA="$ROOT/schema/probe-union.sofab.yaml" CORPUS="$ROOT/corpus/structured-union" \
    "$ROOT/scripts/run.sh" "$@"

echo "==> [cross-encode] restoring probe binaries" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null
