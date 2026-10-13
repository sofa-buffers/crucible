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
#   CLUSTER=1 BASELINE=results/known-clusters-materialized.txt \
#     CORPUS=corpus/interesting ./scripts/materialize.sh
#                                            # over a FUZZED corpus: reduce to camps and diff
#                                            # them against the accounted-for set, the way
#                                            # scripts/run.sh does. Use this rather than the
#                                            # plain form there — policy exceptions are keyed to
#                                            # an input file, so an already-explained divergence
#                                            # on a fuzzed input cannot match one (see the
#                                            # baseline file for the camp this exists for)
#   SCHEMA=schema/probe-union.sofab.yaml ./scripts/materialize.sh
#                                            # a UNION schema: the value table is derived from
#                                            # $SCHEMA, every walker reports the HELD option
#                                            # (`{<id>:<value>}`), corpus defaults to structured-union
#
# The full driver roster emits the SOFAB_MATERIALIZE dump. C is the schema-agnostic
# anchor (object-descriptor walk); the others carry a schema-type table until a generated
# one lands. engine/structured/materialize.py is the conformance ground truth (a
# family-wide-wrong dump is agreement-green but reference-red).
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# A non-probe schema (the union suites) is walked from a table derived from THAT schema. The
# default stays schema/probe.sofab.yaml with the committed oracle/materialized-schema.json.
UNION_MODE=0
UNION_REF=0      # engine/structured/materialize.py has a reference for probe-union's messages only
case "${SCHEMA:-}" in
    ""|*/probe.sofab.yaml|probe.sofab.yaml) ;;
    *) UNION_MODE=1 ;;
esac
case "${SCHEMA:-}" in
    */probe-union.sofab.yaml|probe-union.sofab.yaml) UNION_REF=1 ;;
esac
if [ "$UNION_MODE" = "1" ]; then
    CORPUS="${CORPUS:-$ROOT/corpus/structured-union}"
else
    CORPUS="${CORPUS:-$ROOT/corpus/structured}"
fi

[ -x "$ROOT/tools/sofabgen" ] || "$ROOT/scripts/bootstrap.sh"

# The generated schema-type table (oracle/materialized-schema.json) is derived from
# schema/probe.sofab.yaml by engine/structured/schema.py. The reference reads the
# schema live, so it never drifts; this keeps the *committed* artifact honest too.
if [ "$UNION_MODE" = "1" ]; then
    # Derived, not committed: one table per schema. Exported BEFORE the roster build, because
    # the generated walkers (cpp, dart, kotlin, rust, zig) read it at build time, and the
    # runtime walkers (go, java, ts, cs, python) at run time.
    MAT_SCHEMA_JSON=$(mktemp)
    trap 'rm -f "$MAT_SCHEMA_JSON"' EXIT
    echo "==> [materialize] deriving the schema-type table from $SCHEMA" >&2
    python3 "$ROOT/engine/structured/schema.py" --json "$MAT_SCHEMA_JSON" --schema "$SCHEMA"
else
    MAT_SCHEMA_JSON="$ROOT/oracle/materialized-schema.json"
    echo "==> [materialize] checking the generated schema-type table is current" >&2
    _tmp=$(mktemp)
    python3 "$ROOT/engine/structured/schema.py" --json "$_tmp"
    if ! cmp -s "$_tmp" "$ROOT/oracle/materialized-schema.json"; then
        echo "ERROR: oracle/materialized-schema.json is stale — regenerate:" >&2
        echo "       python3 engine/structured/schema.py --json" >&2
        rm -f "$_tmp"; exit 1
    fi
    rm -f "$_tmp"
fi
export SOFAB_MATERIALIZE_SCHEMA="$MAT_SCHEMA_JSON"

echo "==> [materialize] building the roster (drivers/roster)" >&2
ROSTER_TAG="${ROSTER_TAG-blocking}"
DRIVER_ARGS=$("$ROOT/scripts/roster.sh" build "$ROSTER_TAG")
_oldifs=$IFS
IFS='
'
# shellcheck disable=SC2086
set -- $DRIVER_ARGS
IFS=$_oldifs

TIMEOUT_ARG=""
[ -n "${TIMEOUT:-}" ] && TIMEOUT_ARG="--timeout $TIMEOUT"

# Before the differential: an anchor that prints `?` has not learned a field-type tag,
# and every dump it produces then disagrees with the roster — a red differential that
# says nothing about the family (crucible#190/#192). Fail on that first, by name.
C_BIN=$("$ROOT/scripts/roster.sh" list | awk '$1 == "c" { print $5 }')
echo "==> [materialize] C anchor vocabulary (no \`?\` = every field-type tag known)" >&2
if [ "$UNION_MODE" = "1" ] && [ "$UNION_REF" = "1" ]; then
    python3 "$ROOT/engine/structured/materialize.py" --anchor-vocab-union "$ROOT/$C_BIN"
elif [ "$UNION_MODE" = "1" ]; then
    python3 "$ROOT/engine/structured/materialize.py" --anchor-vocab-dir "$ROOT/$C_BIN" "$CORPUS"
else
    python3 "$ROOT/engine/structured/materialize.py" --anchor-vocab "$ROOT/$C_BIN"
fi

N_INPUTS=$(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$')

# Both branches inherit the environment, so the drivers see SOFAB_MATERIALIZE and the
# descriptor path (drivers that consume the generated table read the latter; the C
# descriptor / hardcoded walkers ignore it).
#
# CLUSTER=1 [BASELINE=<file>] routes through the same camp machinery scripts/run.sh uses,
# on the materialized payload instead of the re-encoded hex. That is what makes this pass
# usable over a FUZZED corpus: `oracle/policy.yaml`'s exceptions name an input *file*
# (`c-embedded-nul-string-projection` -> F-0018's `embedded_nul.bin`), so a fuzzed input
# that hits the same root cause can never match one and lands as a hard `accept_value`
# divergence — 19 of them over corpus/interesting on 2026-10-13, all one input. A camp
# signature does not depend on which input produced it, so a baseline recognises it.
# See results/known-clusters-materialized.txt.
#
# The status is CAPTURED rather than left to `set -e`: the conformance anchor below is the
# half of this oracle that catches a family-wide-wrong dump, and it used to be skipped
# exactly when a divergence existed.
DIFF_STATUS=0
if [ "${CLUSTER:-0}" = "1" ]; then
    echo "==> [materialize] clustering divergences over $N_INPUTS input(s) — SOFAB_MATERIALIZE=1" >&2
    BASE_ARG=""
    [ -n "${BASELINE:-}" ] && BASE_ARG="--baseline $BASELINE"
    # shellcheck disable=SC2086
    SOFAB_MATERIALIZE=1 SOFAB_MATERIALIZE_SCHEMA="$MAT_SCHEMA_JSON" \
        python3 "$ROOT/oracle/cluster.py" \
        --corpus "$CORPUS" --top "${TOP:-20}" $TIMEOUT_ARG $BASE_ARG "$@" || DIFF_STATUS=$?
else
    echo "==> [materialize] differential over $N_INPUTS input(s) — SOFAB_MATERIALIZE=1" >&2
    # shellcheck disable=SC2086
    SOFAB_MATERIALIZE=1 SOFAB_MATERIALIZE_SCHEMA="$MAT_SCHEMA_JSON" \
        python3 "$ROOT/oracle/comparator.py" \
        --corpus "$CORPUS" --policy "$ROOT/oracle/policy.yaml" $TIMEOUT_ARG "$@" || DIFF_STATUS=$?
fi

# Conformance: the differential only proves the roster AGREES — a family-wide-wrong dump
# is agreement-green. Anchor it by checking the schema-agnostic C driver against the
# reference over corpus/structured (the value space the reference is defined on):
# C == reference AND all == C  ⟹  all == reference. Fails (set -e) on any mismatch.
#
# This runs whatever the differential said. It is a DIFFERENT question — "is the family
# right?", not "does the family agree?" — and answering it is cheap, so a divergence above
# must not cost it. Until 2026-10-13 the differential's exit met `set -e` here and the
# anchor never ran on any corpus that diverged at all.
if [ "$UNION_MODE" = "1" ] && [ "$UNION_REF" = "0" ]; then
    # No reference exists for this schema: agreement among the 17 drivers, anchored by the C
    # descriptor walk, is the whole oracle. Said here so a green run is not read as more.
    echo "==> [materialize] conformance: no reference for $(basename "$SCHEMA") -- agreement + the C anchor only" >&2
    exit "$DIFF_STATUS"
fi
echo "==> [materialize] conformance: C anchor vs the reference (engine/structured/materialize.py)" >&2
if [ "$UNION_MODE" = "1" ]; then
    # the union reference is defined on corpus/structured-union (gen.py's union messages)
    python3 "$ROOT/engine/structured/materialize.py" --driver-union "$ROOT/$C_BIN"
else
    python3 "$ROOT/engine/structured/materialize.py" --driver "$ROOT/$C_BIN"
fi

# The anchor passed (set -e would have ended the run otherwise); the differential's verdict
# is the remaining one.
exit "$DIFF_STATUS"
