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
# see drivers/go/gocorpus.py, which is the only format that module understands.
#
# FUZZ_TARGET=FuzzProbeStream switches to the second target (crucible#178): it
# steers on the STREAMING (feed/finish) decode path instead of the block-path
# FuzzProbe above, taking its chunk cut position from two extra fuzz arguments
# (mode, param — drivers/go/fuzz_test.go) rather than from a header in the
# bytes, so seeding and harvesting go through gocorpus.py's multi-argument
# (`--first-bytes`) mode instead of its strict single-argument one.
#
# Env:
#   FUZZ_TIME=<seconds>   wall-clock budget (default 120)
#   CORPUS=<dir>          corpus to seed from and harvest into (default corpus/interesting)
#   FUZZ_TARGET=<name>    fuzz target to run (default FuzzProbe; or FuzzProbeStream)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
GODIR="$ROOT/drivers/go"
FUZZ_TIME="${FUZZ_TIME:-120}"
CORP="${CORPUS:-$ROOT/corpus/interesting}"
CRASH="$ROOT/corpus/crashes"
CONV="$GODIR/gocorpus.py"
TARGET="${FUZZ_TARGET:-FuzzProbe}"
STREAM=0
[ "$TARGET" = "FuzzProbeStream" ] && STREAM=1
SEEDDIR="$GODIR/testdata/fuzz/$TARGET"

command -v go >/dev/null || { echo "error: go not on PATH (use the devcontainer)" >&2; exit 1; }
mkdir -p "$CORP" "$CRASH"

# The generated `message` package must exist and match the current schema.
echo "==> [go-fuzz] regenerating probe types + driver" >&2
sh "$GODIR/build.sh" >/dev/null

# --- seed: raw corpus -> Go's text format ----------------------------------
# Named seed_<sha1> so that anything else left in testdata afterwards is, by
# construction, an artifact Go wrote itself — i.e. a failing input.
echo "==> [go-fuzz] seeding $TARGET from $(basename "$CORP") + seeds + findings" >&2
rm -rf "$SEEDDIR"
mkdir -p "$SEEDDIR"
seeded=0
for f in "$CORP"/* "$ROOT/corpus/seeds"/* "$ROOT"/findings/*/*.bin; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in .gitkeep|*.md) continue ;; esac
    h=$(sha1sum "$f" | cut -c1-16)
    [ -f "$SEEDDIR/seed_$h" ] && continue
    if [ "$STREAM" = "1" ]; then
        # Same three-way sweep as scripts/fuzz.sh's C seeding (SPLIT at the
        # midpoint / CHUNK=1 / CHUNK=7), deterministic per file so a re-run
        # doesn't re-roll it — NOT the same per-file assignment as the C side
        # (that hashes the whole sha1 in Python; this hashes only its first 8
        # hex chars in shell arithmetic), which doesn't matter: each engine
        # only needs to cover the three variants across ITS OWN seed corpus.
        size=$(wc -c <"$f")
        [ "$size" -eq 0 ] && continue   # CONTRACT rule 4: never fed at all
        variant=$(( 0x$(sha1sum "$f" | cut -c1-8) % 3 ))
        case "$variant" in
            0) m=0; p=$(( size / 2 )); [ "$p" -gt 65535 ] && p=65535 ;;
            1) m=1; p=1 ;;
            2) m=1; p=7 ;;
        esac
        python3 "$CONV" encode "$f" "$SEEDDIR/seed_$h" --mode "$m" --param "$p"
    else
        python3 "$CONV" encode "$f" "$SEEDDIR/seed_$h"
    fi
    seeded=$((seeded + 1))
done
echo "==> [go-fuzz] $seeded seed(s)" >&2

# --- fuzz -------------------------------------------------------------------
# `-run '^$'` so only fuzzing happens, no ordinary tests. A non-zero exit means a
# seed or a discovered input made the decoder panic — a crash finding, not a
# harness error, so it is reported rather than swallowed.
#
# The anchor matters even for the default target: `-fuzz` is a REGEX, so an
# unanchored `-fuzz=FuzzProbe` also matches `FuzzProbeStream` once that target
# exists, and `go test` refuses to run ("matches more than one fuzz test").
echo "==> [go-fuzz] fuzzing $TARGET ${FUZZ_TIME}s (native go test -fuzz, coverage-guided)" >&2
rc=0
( cd "$GODIR" && GOFLAGS=-mod=mod GOTOOLCHAIN=local \
    go test -run '^$' -fuzz="^${TARGET}\$" -fuzztime="${FUZZ_TIME}s" . ) || rc=$?

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
    # -buildvcs=false: `go list` stamps VCS metadata, which shells out to git. In
    # the CI container the checkout is not owned by the build user, so git exits
    # 128 ("dubious ownership") and takes `go list` down with it — the actual
    # cause of the five silent nightlies. `go build`/`go test` do not trip it.
    if ( cd "$GODIR" && GOFLAGS=-mod=mod GOTOOLCHAIN=local \
             go list -buildvcs=false -f '{{.ImportPath}}' . ) >"$tmp/pkg" 2>"$tmp/err"; then
        PKG=$(cat "$tmp/pkg")
    else
        echo "==> [go-fuzz] WARNING: 'go list' failed — falling back to go.mod:" >&2
        sed 's/^/    /' "$tmp/err" >&2
        PKG=$(awk '$1 == "module" { print $2; exit }' "$GODIR/go.mod")
    fi
fi

CACHE=""
if [ -n "$GOCACHE_DIR" ] && [ -n "$PKG" ] && [ -d "$GOCACHE_DIR/fuzz/$PKG/$TARGET" ]; then
    CACHE="$GOCACHE_DIR/fuzz/$PKG/$TARGET"
elif [ -n "$GOCACHE_DIR" ] && [ -d "$GOCACHE_DIR/fuzz" ]; then
    # Last resort: $TARGET is the only fuzz target of that name in this repo, so
    # the one directory of that name under the cache is ours whatever the
    # import path.
    CACHE=$(find "$GOCACHE_DIR/fuzz" -type d -name "$TARGET" 2>/dev/null | head -n 1)
    [ -n "$CACHE" ] && echo "==> [go-fuzz] fuzz cache located by search: $CACHE" >&2
fi

new=0
if [ -n "$CACHE" ] && [ -d "$CACHE" ]; then
    for f in "$CACHE"/*; do
        [ -f "$f" ] || continue
        if [ "$STREAM" = "1" ]; then
            python3 "$CONV" decode --first-bytes "$f" "$tmp/x" 2>/dev/null || continue
        else
            python3 "$CONV" decode "$f" "$tmp/x" 2>/dev/null || continue
        fi
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
    if [ "$STREAM" = "1" ]; then
        out="$CRASH/go-stream-$(basename "$f")"
        if python3 "$CONV" decode --first-bytes "$f" "$out" "$tmp/args" 2>/dev/null; then
            crashes=$((crashes + 1))
            # args-file holds one int per line: mode then param
            # (drivers/go/fuzz_test.go's FuzzProbeStream signature).
            m=$(sed -n '1p' "$tmp/args"); p=$(sed -n '2p' "$tmp/args")
            if [ -n "$m" ] && [ -n "$p" ]; then
                var="SOFAB_SPLIT"; [ "$((m & 1))" = "1" ] && var="SOFAB_CHUNK"
                echo "==> [go-fuzz]   $out: replay with $var=$p" >&2
            fi
        fi
    else
        python3 "$CONV" decode "$f" "$CRASH/go-$(basename "$f")" 2>/dev/null && crashes=$((crashes + 1))
    fi
done
[ "$crashes" -gt 0 ] && echo "==> [go-fuzz] $crashes CRASH artifact(s) -> corpus/crashes/ (a Go panic — or, for $TARGET, a t.Fatalf chunk-invariance violation — is a finding)" >&2

echo "==> [go-fuzz] corpus now $(ls "$CORP" | grep -vc gitkeep) input(s); go test exit $rc" >&2
echo "==> next: CORPUS=$CORP CLUSTER=1 ./scripts/run.sh   # differential over the grown corpus" >&2
exit "$rc"
