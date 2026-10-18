#!/usr/bin/env sh
# Crucible $ref suite (crucible#212) -- does writing a type through `$ref` change behaviour?
#
# schema/probe-ref.sofab.yaml uses every `$ref` form sofabgen accepts; its twin
# schema/probe-ref-inline.sofab.yaml is the same message with every `$ref` written out. One
# wire format, two spellings, so the roster is built against each and every driver must give
# every vector of corpus/ref (engine/structured/sweep_ref.py, which owns the expectations) the
# same answer under both:
#   1. inline twin  -- differential (run.sh) + conformance (sweep_run.py --ref), answers saved
#   2. $ref schema  -- differential + conformance, answers compared with pass 1 driver by driver
#   3. materialized, inline twin -- the decoded VALUE (materialize.sh: agreement + C anchor),
#                      every driver's dump saved
#   4. materialized, $ref schema -- the same, dumps compared with pass 3 driver by driver
#   5. chunk        -- decode of the $ref build is invariant under chunking (run-chunked.sh)
#   6. encode       -- every encode surface of the $ref build writes the same bytes (run-encode.sh)
# What the GENERATED CODE looks like under the two spellings is scripts/check-ref-codegen.py's.
#
#   ./scripts/run-ref.sh            # all six
#   ./scripts/run-ref.sh --quick    # passes 1 and 2 only (= --part 1)
#   ./scripts/run-ref.sh --part 2   # passes 3 to 6 only (replay.yml runs the two parts as two jobs)
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PART=all
case "${1:-}" in
    --quick) PART=1 ;;
    --part) PART="${2:-}" ;;
esac
case "$PART" in all|1|2) ;; *) echo "usage: run-ref.sh [--quick | --part 1|2]" >&2; exit 2 ;; esac
rc=0
ANSWERS=$(mktemp)
DUMPS=$(mktemp)
TABLE=$(mktemp)
trap 'rm -f "$ANSWERS" "$DUMPS" "$TABLE"' EXIT
INLINE="$ROOT/schema/probe-ref-inline.sofab.yaml"
REF="$ROOT/schema/probe-ref.sofab.yaml"

echo "==> [ref] regenerating corpus/ref" >&2
python3 "$ROOT/engine/structured/sweep_ref.py" "$ROOT/corpus/ref" >&2 || exit 1

if [ "$PART" != "2" ]; then
    echo "==> [ref] 1/6 inline twin: differential + conformance" >&2
    export SCHEMA="$INLINE"
    CORPUS="$ROOT/corpus/ref" "$ROOT/scripts/run.sh" || rc=1
    python3 "$ROOT/engine/structured/sweep_run.py" --ref --save-outputs "$ANSWERS" || rc=1

    echo "==> [ref] 2/6 \$ref schema: differential + conformance + same answers as the twin" >&2
    export SCHEMA="$REF"
    CORPUS="$ROOT/corpus/ref" "$ROOT/scripts/run.sh" || rc=1
    python3 "$ROOT/engine/structured/sweep_run.py" --ref --compare-outputs "$ANSWERS" || rc=1
fi

if [ "$PART" != "1" ]; then
    # materialize.sh builds the roster against $SCHEMA; the dumps are then taken from that
    # build, with the same derived table it used.
    for pass in 3 4; do
        if [ "$pass" = "3" ]; then export SCHEMA="$INLINE"; TWIN="--save-outputs $DUMPS"; what="inline twin"
        else export SCHEMA="$REF"; TWIN="--compare-outputs $DUMPS"; what="\$ref schema, same values as the twin"; fi
        echo "==> [ref] $pass/6 materialized: $what" >&2
        CORPUS="$ROOT/corpus/ref" "$ROOT/scripts/materialize.sh" || rc=1
        python3 "$ROOT/engine/structured/schema.py" --json "$TABLE" --schema "$SCHEMA" --types || rc=1
        # shellcheck disable=SC2086
        SOFAB_MATERIALIZE=1 SOFAB_MATERIALIZE_SCHEMA="$TABLE" \
            python3 "$ROOT/engine/structured/sweep_run.py" --ref --agreement-only $TWIN || rc=1
    done
    echo "==> [ref] 5/6 chunk invariance" >&2
    CORPUS="$ROOT/corpus/ref" "$ROOT/scripts/run-chunked.sh" --modes chunk || rc=1
    echo "==> [ref] 6/6 encode invariance" >&2
    CORPUS="$ROOT/corpus/ref" "$ROOT/scripts/run-encode.sh" || rc=1
fi

# RESTORE=0 skips it: in a CI job where nothing runs on these binaries afterwards, the rebuild
# is time spent for nobody (each replay.yml job builds what it needs; SKIP_BUILD can never
# reuse a build of another schema).
if [ "${RESTORE:-1}" != "0" ]; then
    echo "==> [ref] restoring probe binaries" >&2
    SCHEMA="$ROOT/schema/probe.sofab.yaml" CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null || true
fi
exit $rc
