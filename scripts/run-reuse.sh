#!/usr/bin/env sh
# Reuse-invariance gate — a decode into a reused destination against a fresh one.
#
# The generated decode of most backends writes into a destination the caller owns and
# may keep across messages (generator#755 and its siblings), and promises that the
# result reads as a fresh decode: nothing of the previous message survives. Every other
# gate decodes each record into a fresh message, so that promise is never exercised.
#
# Under SOFAB_REUSE=1 a driver keeps ONE destination for the whole run; each record's
# canonical line must equal the one it prints with a fresh destination. Not
# differential — a driver against itself, like run-chunked.sh and run-encode.sh.
#
#   ./scripts/run-reuse.sh                       # corpus/regression, primed by corpus/structured
#   CORPUS=path PRIMERS=path ./scripts/run-reuse.sh
#
# Defaults to corpus/regression because it mixes accepts with rejects and incompletes,
# so a record also follows a refusal; corpus/structured primes the destination with
# value-rich messages first. See oracle/reuse_invariance.py.
#
# Driver contract: drivers/common/CONTRACT.md ("Reused destination").
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/regression}"
PRIMERS="${PRIMERS:-$ROOT/corpus/structured}"
TAG="${ROSTER_TAG-blocking}"

# Who participates is derived from `meta`'s reuse_decode, never typed. Every roster row
# that is NOT a participant is checked for the hard-fail instead, so no row is silent.
SUPPORTED="${SOFAB_REUSE_DRIVERS:-$("$ROOT/scripts/roster.sh" caps reuse "$TAG" | tr '\n' ' ')}"
ABSENT=""
if [ -z "${SOFAB_REUSE_DRIVERS:-}" ]; then
    for n in $("$ROOT/scripts/roster.sh" list "$TAG" | awk '{print $1}'); do
        case " $SUPPORTED " in *" $n "*) ;; *) ABSENT="$ABSENT $n" ;; esac
    done
fi

if [ -z "$SUPPORTED" ]; then
    echo "==> [reuse] no driver implements SOFAB_REUSE — nothing to check (skipping loudly)." >&2
    exit 0
fi

echo "==> [reuse] building drivers" >&2
# Pin the corpus for the build-only run.sh call, as run-chunked.sh and run-encode.sh do.
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [reuse] reuse invariance over $(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$') input(s)" >&2
python3 "$ROOT/oracle/reuse_invariance.py" --corpus "$CORPUS" --primers "$PRIMERS" \
    --drivers "$SUPPORTED" --absent "$ABSENT" "$@"
