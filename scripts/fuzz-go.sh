#!/usr/bin/env sh
# Run the **Go** coverage engine — Crucible's second steering engine (PLAN §3,
# docs/TODO.md "Multi-impl coverage").
#
# The C pacemaker steers the fuzzer by *C* coverage, so it only ever explores paths
# that are complex in C. Every catalogued finding in another language was reached
# either by the differential over a C-grown corpus or by hand — never by a fuzzer
# steering on that language's own decoder. This runs Go's native coverage-guided
# fuzzer (`go test -fuzz`, no external framework) over the same schema and feeds
# what it finds back into the shared corpus, so the next differential run sees
# inputs chosen for *Go*-side complexity.
#
# Go stores its corpus in a text format rather than raw bytes, in both directions —
# see drivers/go/gocorpus.py, which is the only place that format is understood.
#
# Env:
#   FUZZ_TIME=<seconds>   wall-clock budget (default 120)
#   CORPUS=<dir>          corpus to seed from and harvest into (default corpus/interesting)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
GODIR="$ROOT/drivers/go"
FUZZ_TIME="${FUZZ_TIME:-120}"
CORP="${CORPUS:-$ROOT/corpus/interesting}"
CRASH="$ROOT/corpus/crashes"
CONV="$GODIR/gocorpus.py"
SEEDDIR="$GODIR/testdata/fuzz/FuzzProbe"

command -v go >/dev/null || { echo "error: go not on PATH (use the devcontainer)" >&2; exit 1; }
mkdir -p "$CORP" "$CRASH"

# The generated `message` package must exist and match the current schema.
echo "==> [go-fuzz] regenerating probe types + driver" >&2
sh "$GODIR/build.sh" >/dev/null

# --- seed: raw corpus -> Go's text format ----------------------------------
# Named seed_<sha1> so that anything else left in testdata afterwards is, by
# construction, an artifact Go wrote itself — i.e. a failing input.
echo "==> [go-fuzz] seeding from $(basename "$CORP") + seeds + findings" >&2
rm -rf "$SEEDDIR"
mkdir -p "$SEEDDIR"
seeded=0
for f in "$CORP"/* "$ROOT/corpus/seeds"/* "$ROOT"/findings/*/*.bin; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in .gitkeep|*.md) continue ;; esac
    h=$(sha1sum "$f" | cut -c1-16)
    [ -f "$SEEDDIR/seed_$h" ] && continue
    python3 "$CONV" encode "$f" "$SEEDDIR/seed_$h"
    seeded=$((seeded + 1))
done
echo "==> [go-fuzz] $seeded seed(s)" >&2

# --- fuzz -------------------------------------------------------------------
# `-run '^$'` so only fuzzing happens, no ordinary tests. A non-zero exit means a
# seed or a discovered input made the decoder panic — a crash finding, not a
# harness error, so it is reported rather than swallowed.
echo "==> [go-fuzz] fuzzing ${FUZZ_TIME}s (native go test -fuzz, coverage-guided)" >&2
rc=0
( cd "$GODIR" && GOFLAGS=-mod=mod GOTOOLCHAIN=local \
    go test -run '^$' -fuzz=FuzzProbe -fuzztime="${FUZZ_TIME}s" . ) || rc=$?

# --- harvest: Go's coverage corpus -> raw bytes -----------------------------
PKG=$(cd "$GODIR" && GOFLAGS=-mod=mod GOTOOLCHAIN=local go list -f '{{.ImportPath}}' . 2>/dev/null)
CACHE="$(go env GOCACHE)/fuzz/$PKG/FuzzProbe"
new=0
if [ -d "$CACHE" ]; then
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    for f in "$CACHE"/*; do
        [ -f "$f" ] || continue
        python3 "$CONV" decode "$f" "$tmp/x" 2>/dev/null || continue
        h=$(sha1sum "$tmp/x" | cut -d' ' -f1)
        [ -f "$CORP/$h" ] && continue          # already known, by content
        cp "$tmp/x" "$CORP/$h"
        new=$((new + 1))
    done
fi
echo "==> [go-fuzz] $new new input(s) harvested into $(basename "$CORP")" >&2

# --- crash artifacts --------------------------------------------------------
crashes=0
for f in "$SEEDDIR"/*; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in seed_*) continue ;; esac
    python3 "$CONV" decode "$f" "$CRASH/go-$(basename "$f")" 2>/dev/null && crashes=$((crashes + 1))
done
[ "$crashes" -gt 0 ] && echo "==> [go-fuzz] $crashes CRASH artifact(s) -> corpus/crashes/ (a Go panic is a finding)" >&2

echo "==> [go-fuzz] corpus now $(ls "$CORP" | grep -vc gitkeep) input(s); go test exit $rc" >&2
echo "==> next: CORPUS=$CORP CLUSTER=1 ./scripts/run.sh   # differential over the grown corpus" >&2
exit "$rc"
