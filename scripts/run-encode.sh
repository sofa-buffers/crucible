#!/usr/bin/env sh
# Encode-invariance gate (crucible#132) — the encode-side twin of run-chunked.sh.
#
# The family is byte-canonical: a value has exactly one encoding. The generated API
# offers up to three ways to produce it — the allocating `encode()`, the caller-buffer
# `encodeTo()`, and the streaming `serialize(os)` — and the round-trip oracle exercises
# whichever one the driver happens to call. The other two are untested everywhere, and
# so is what happens when the OStream's buffer boundary lands mid-message.
#
# For one implementation and one decoded value, all three surfaces must emit **identical
# bytes**, and `SOFAB_FLUSH=n` must not change them either. Like the chunk gate this is
# **not differential** — it compares an implementation against itself, so it needs no
# second implementation, drivers opt in one at a time, and it is the only kind of gate
# that can catch a defect the whole family shares.
#
#   ./scripts/run-encode.sh                  # corpus/structured (value-rich, all accept)
#   CORPUS=path ./scripts/run-encode.sh      # another corpus
#
# Defaults to corpus/structured rather than corpus/seeds because only an ACCEPTED input
# re-encodes: on `I` and `R` there is no value and every surface trivially agrees. The
# structured corpus is the value space this gate is about.
#
# Driver contract: a driver opts in by honouring `SOFAB_ENCODE=new|to|stream` and
# `SOFAB_FLUSH=n`, and by exiting non-zero when asked for a surface its backend does not
# have (drivers/common/CONTRACT.md). Drivers that do not honour it are **skipped
# loudly**, never counted as passing: a driver that ignores the variables produces
# byte-identical output, which is indistinguishable from correctness.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/structured}"

# WHO PARTICIPATES IS DERIVED, NOT TYPED. `roster.sh caps encode` lists the roster
# names whose `drivers/<builder>/meta` declares any `encode_surfaces`, so a new driver
# is in this gate by construction. The hand-written list this replaces is what let `go`
# sit outside the gate for eleven days: its backend had all three surfaces and its meta
# said so, but a name was missing from a script — and a missing name is indistinguishable
# from a declared exception. Staying out now requires a `meta` that declares no surface.
# SOFAB_ENCODE_DRIVERS still overrides, for isolating one driver by hand.
SUPPORTED="${SOFAB_ENCODE_DRIVERS:-$("$ROOT/scripts/roster.sh" caps encode | tr '\n' ' ')}"

if [ -z "$SUPPORTED" ]; then
    echo "==> [encode] no driver implements SOFAB_ENCODE yet — nothing to check." >&2
    echo "    The oracle and the corpus are ready; the per-driver re-encode is not." >&2
    echo "    Tracked in docs/TODO.md. Skipping (this gate cannot pass vacuously)." >&2
    exit 0
fi

echo "==> [encode] building drivers" >&2
# PIN THE CORPUS. run.sh is used here only to build the roster, but it also runs the
# differential comparison and reads CORPUS from the environment — so without this pin it
# inherits *this* gate's CORPUS and compares that instead. On any corpus with known
# divergences (corpus/interesting, which docs/CI.md and the check-nightly procedure both
# point this gate at) the comparator exits non-zero, `set -e` aborts here, and the encode
# check never runs. It fails silently: run.sh's stdout is the summary and goes to
# /dev/null, so the log ends at "differential comparison over N input(s)" with no
# divergence count and no traceback, which reads like a killed process rather than a
# guard. run-chunked.sh pins it for the same reason.
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [encode] encode invariance over $(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$') input(s)" >&2
python3 "$ROOT/oracle/encode_invariance.py" --corpus "$CORPUS" --drivers "$SUPPORTED" "$@"
