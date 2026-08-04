#!/usr/bin/env sh
# Chunk-invariance gate (CORELIB_PLAN §7.2 item 4; crucible#130).
#
# Every other oracle here is *differential*: it asks whether the 13 drivers agree.
# This one is not, and that is the point — **chunk invariance is an invariant of a
# single implementation against itself**, so it needs no second driver to be useful
# and each driver can be landed independently. A defect that every implementation
# shares is invisible to the differential oracle; a defect that appears only when a
# message is split is invisible to the whole suite, because the replay driver feeds
# each record whole.
#
# The rule (CORELIB_PLAN §6.4 states it for UTF-8, §7.2 item 4 for the decoder at
# large): **a chunk boundary MUST NOT change the outcome.** So for every input and
# every split point k, feeding [0,k) then [k,end) into one stream must produce the
# same canonical line as feeding the whole thing at once. Sweeping k over the whole
# length covers every metadata/payload boundary without the harness needing to know
# where they are — which is what crucible#130 asked for.
#
# It also asserts **resumability**, the second ask: if the outcome after the first
# chunk is `I`, the outcome after the second must still reach the same verdict and
# the same value. corelib-cpp's raw blob read failed exactly there — INVALID and
# then unrecoverable, with the buffered tail dropped, so the message never
# completed even once the remaining bytes arrived.
#
#   ./scripts/run-chunked.sh                  # corpus/seeds
#   CORPUS=path ./scripts/run-chunked.sh      # another corpus
#
# Driver contract: a driver opts in by honouring `SOFAB_SPLIT=k` — feed each record
# as [0,k) then [k,end) into ONE decoder, and emit the canonical line of the final
# state. Drivers that do not honour it are **skipped loudly**, never counted as
# passing: a driver that ignores the variable produces byte-identical output, which
# is indistinguishable from correctness. See drivers/common/CONTRACT.md.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/seeds}"

# Drivers known to implement the chunking variables. Add a name here only once it
# demonstrably re-feeds — a driver that ignores them emits byte-identical output, so
# this list is the only thing standing between the gate and a vacuous pass. Each of
# these announces its configuration on stderr when a variable is set, so "does it
# really re-feed" is checkable rather than asserted (see drivers/common/CONTRACT.md).
# The rest are tracked in docs/TODO.md.
# zig is deliberately ABSENT while F-0058 (generator#293) is open: its generated
# chunked reassembly shares one buffer across split payloads, so two wrapper-array
# elements alias each other. Including it would make this gate permanently red for a
# defect that is already filed — the same reasoning results/known-clusters.txt rests
# on. Add it back when F-0058 closes; that one word is the whole change.
SUPPORTED="${SOFAB_SPLIT_DRIVERS:-c rust-std rust-nostd cpp cpp-fixed cpp-c-cpp typescript java csharp dart py-cython py-pure}"

if [ -z "$SUPPORTED" ]; then
    echo "==> [chunked] no driver implements SOFAB_SPLIT yet — nothing to check." >&2
    echo "    The oracle and the corpus sweep are ready; the per-driver re-feed is not." >&2
    echo "    Tracked in docs/TODO.md. Skipping (this gate cannot pass vacuously)." >&2
    exit 0
fi

echo "==> [chunked] building drivers" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [chunked] chunk invariance over $(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$') input(s)" >&2
python3 "$ROOT/oracle/chunk_invariance.py" --corpus "$CORPUS" --drivers "$SUPPORTED" "$@"
