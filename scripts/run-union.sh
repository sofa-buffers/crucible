#!/usr/bin/env sh
# Crucible union suite — the differential + round-trip oracles over a schema with a
# `union` (the one wire feature the full-scale `probe` message lacks). The drivers
# are schema-agnostic (round-trip form), so this just builds them against
# schema/probe-union.sofab.yaml and runs the standard differential over corpus/union.
#
#   ./scripts/run-union.sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export SCHEMA="$ROOT/schema/probe-union.sofab.yaml"
CORPUS="$ROOT/corpus/union" exec "$ROOT/scripts/run.sh" "$@"
