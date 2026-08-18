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
# Locating Go's per-target fuzz cache must not be able to kill the step. It used
# to: `go list` ran with its stderr discarded and, under `set -e`, a single
# failure threw away the whole harvest *and* the crash scan without printing one
# word. That is exactly what happened — nightlies 2026-08-14..18 each fuzzed for
# 450s, found new inputs, and dropped every one of them; `continue-on-error` kept
# the run green, so nothing said so. So: no fatal step, and every fallback is
# announced.
#
# The cache layout is $GOCACHE/fuzz/<import path>/<fuzz target>.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

GOCACHE_DIR=""
if GOTOOLCHAIN=local go env GOCACHE >"$tmp/gocache" 2>"$tmp/err"; then
    GOCACHE_DIR=$(cat "$tmp/gocache")
else
    echo "==> [go-fuzz] WARNING: 'go env GOCACHE' failed — cannot harvest:" >&2
    sed 's/^/    /' "$tmp/err" >&2
fi

# The import path, preferably from the toolchain; from go.mod when `go list`
# fails (it resolves the whole module graph, so it has more ways to fail than
# reading the one line we actually want).
PKG=""
if [ -n "$GOCACHE_DIR" ]; then
    if ( cd "$GODIR" && GOFLAGS=-mod=mod GOTOOLCHAIN=local \
             go list -f '{{.ImportPath}}' . ) >"$tmp/pkg" 2>"$tmp/err"; then
        PKG=$(cat "$tmp/pkg")
    else
        echo "==> [go-fuzz] WARNING: 'go list' failed — falling back to go.mod:" >&2
        sed 's/^/    /' "$tmp/err" >&2
        PKG=$(awk '$1 == "module" { print $2; exit }' "$GODIR/go.mod")
    fi
fi

CACHE=""
if [ -n "$GOCACHE_DIR" ] && [ -n "$PKG" ] && [ -d "$GOCACHE_DIR/fuzz/$PKG/FuzzProbe" ]; then
    CACHE="$GOCACHE_DIR/fuzz/$PKG/FuzzProbe"
elif [ -n "$GOCACHE_DIR" ] && [ -d "$GOCACHE_DIR/fuzz" ]; then
    # Last resort: FuzzProbe is the only fuzz target in this repo, so the one
    # directory of that name under the cache is ours whatever the import path.
    CACHE=$(find "$GOCACHE_DIR/fuzz" -type d -name FuzzProbe 2>/dev/null | head -n 1)
    [ -n "$CACHE" ] && echo "==> [go-fuzz] fuzz cache located by search: $CACHE" >&2
fi

new=0
if [ -n "$CACHE" ] && [ -d "$CACHE" ]; then
    for f in "$CACHE"/*; do
        [ -f "$f" ] || continue
        python3 "$CONV" decode "$f" "$tmp/x" 2>/dev/null || continue
        h=$(sha1sum "$tmp/x" | cut -d' ' -f1)
        [ -f "$CORP/$h" ] && continue          # already known, by content
        cp "$tmp/x" "$CORP/$h"
        new=$((new + 1))
    done
else
    echo "==> [go-fuzz] WARNING: no fuzz cache under GOCACHE — harvested nothing" >&2
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
