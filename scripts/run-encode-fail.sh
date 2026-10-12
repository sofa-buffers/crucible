#!/usr/bin/env sh
# The `E` verdict, exercised for real — the destination-failure gate.
#
# `oracle/canonical.md`'s fifth verdict says what a driver must answer when its decode
# accepted a value and the re-encode of that value was refused. Reaching that from the
# wire takes a DECODER bug: every value a driver re-encodes came out of its own decoder
# and is in-bounds by construction, which is exactly why the verdict starts green. So
# until this gate, the mapping in every one of the eleven driver sources had never run —
# not in a gate, not in a nightly, not once. A verdict whose handling nothing exercises
# is decoration, and this repo has written that sentence down more than once.
#
# `SOFAB_ENCODE_FAIL=n` (drivers/common/CONTRACT.md) hands the encoder a destination of
# n bytes with **no sink** behind it. Every corelib answers a full sink-less buffer the
# same way — CORELIB_PLAN §6.3's `BufferFull` — so the refusal is real, it comes from the
# corelib rather than from an injected exception, and the driver has to map it.
#
# **It is differential, unlike the other intra-driver axes.** The family is byte-canonical:
# one value has one encoding and therefore one length. With the same `n`, every
# implementation must refuse the SAME records and re-encode the rest byte-identically. So
# this needs no oracle of its own — it is the ordinary comparator, with
# `--allow-encode-refused` to say that here an `E` is the expected answer and the question
# is whether everyone agrees on which records get it (without the flag the comparator
# fails on every `E` per line, which is right everywhere else).
#
#   ./scripts/run-encode-fail.sh              # a sweep of destination sizes
#   FAIL_SIZES="1 8" ./scripts/run-encode-fail.sh
#   CORPUS=path ./scripts/run-encode-fail.sh
#
# Defaults to corpus/structured: only an ACCEPTED input re-encodes, so `I` and `R` records
# have nothing to refuse, and that corpus is the value-rich one.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/structured}"

# The sizes to hand over. 1 is the extreme — every non-empty message is refused, so the
# verdict is `E` for everything but the all-default record, which is where `A ` with
# empty hex and a refusal would collide if a driver confused them (findings/G-0047).
# The middle sizes split the corpus: some records fit, some do not, and the gate then
# also asserts that the ones that fit are unaffected.
FAIL_SIZES="${FAIL_SIZES:-1 16 64}"

# WHO PARTICIPATES IS DERIVED, not typed: `roster.sh caps encode_fail` reads
# `encode_fail=` from each `drivers/<builder>/meta`, so a new driver is in this gate by
# construction and staying out takes a `no` that someone wrote down.
SUPPORTED="${SOFAB_ENCODE_FAIL_DRIVERS:-$("$ROOT/scripts/roster.sh" caps encode_fail "${ROSTER_TAG-blocking}" | tr '\n' ' ')}"
if [ -z "$SUPPORTED" ]; then
    echo "==> [encode-fail] no driver declares encode_fail — nothing to check." >&2
    echo "    This gate cannot pass vacuously; see drivers/common/CONTRACT.md." >&2
    exit 0
fi

echo "==> [encode-fail] building drivers" >&2
# PIN THE CORPUS: run.sh reads CORPUS from the environment and would otherwise compare
# this gate's corpus here, before the real pass runs (the same trap run-encode.sh pins).
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

DRIVER_ARGS=$("$ROOT/scripts/roster.sh" build "${ROSTER_TAG-blocking}")
_oldifs=$IFS
IFS='
'
# shellcheck disable=SC2086
set -- $DRIVER_ARGS
IFS=$_oldifs

n_inputs=$(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$')
rc=0
for n in $FAIL_SIZES; do
    echo "==> [encode-fail] destination of $n byte(s) over $n_inputs input(s), drivers: $SUPPORTED" >&2
    # Every driver gets the same n, so they must agree. SOFAB_ENCODE stays unset: the
    # axis replaces the re-encode path wholesale (CONTRACT.md), and asking for a surface
    # as well would only test which branch the driver takes to reach the same stream.
    SOFAB_ENCODE_FAIL="$n" python3 "$ROOT/oracle/comparator.py" \
        --corpus "$CORPUS" --policy "$ROOT/oracle/policy.yaml" \
        --allow-encode-refused "$@" || rc=1
done

if [ "$rc" != 0 ]; then
    echo "==> [encode-fail] FAILED — with one destination size the family must refuse the" >&2
    echo "    same records: one value has one encoding, so it has one length." >&2
fi
exit "$rc"
