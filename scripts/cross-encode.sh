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
#   ./scripts/cross-encode.sh          # regenerate corpus/structured, run the differential
#   REGEN=0 ./scripts/cross-encode.sh  # skip regeneration, just re-run
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ "${REGEN:-1}" = "1" ]; then
    python3 "$ROOT/engine/structured/gen.py" "$ROOT/corpus/structured"
fi
CORPUS="$ROOT/corpus/structured" exec "$ROOT/scripts/run.sh" "$@"
