#!/usr/bin/env sh
# Run the Crucible C pacemaker — the coverage-guided fuzzing engine (PLAN §3).
#
# Builds the C driver's libFuzzer front-end (clang -fsanitize=fuzzer,address,
# undefined; the `CRUCIBLE_LIBFUZZER` path in drivers/c/driver.c) and runs it,
# seeded from corpus/seeds + accumulated corpus/interesting + the findings
# reproducers. New coverage-increasing inputs grow corpus/interesting/; crashes
# land in corpus/crashes/. Feed the grown corpus through all drivers with
#   CORPUS=corpus/interesting ./scripts/run.sh
# to turn coverage discoveries into differential findings.
#
# FUZZ_STREAM=1 switches to the second target in the same driver.c: the
# STREAMING (feed/finish) path instead of the block-path decode
# (crucible#178). It steers on decode_chunked's own chunk-invariance check
# (drivers/c/driver.c, CRUCIBLE_FUZZ_STREAM) rather than block-path coverage, so
# it is a different corpus (corpus/stream/) with a 3-byte mode/param header in
# front of each message; see "streaming — how a seed becomes a header-prefixed
# input" and "streaming — harvest" below. corpus/interesting/ only ever
# receives the stripped, header-free message, exactly like the block path.
#
# Env:
#   FUZZ_TIME=<seconds>   wall-clock budget (default 120)
#   FUZZ_JOBS=<n>         parallel libFuzzer jobs (default 1)
#   FUZZ_STREAM=1         build+run the streaming target instead of the block one
#   CC=clang              needs a libFuzzer-capable clang (devcontainer)
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-c-cpp"
CC="${CC:-clang}"
FUZZ_TIME="${FUZZ_TIME:-120}"
FUZZ_JOBS="${FUZZ_JOBS:-1}"
STREAM="${FUZZ_STREAM:-0}"

GEN="$ROOT/drivers/c/fuzz-gen"
INTERESTING="$ROOT/corpus/interesting"
CRASH="$ROOT/corpus/crashes"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
if ! command -v "$CC" >/dev/null || ! "$CC" --version 2>/dev/null | grep -qi clang; then
    echo "error: the pacemaker needs a libFuzzer-capable clang (set CC=clang; use the devcontainer)." >&2
    exit 1
fi

if [ "$STREAM" = "1" ]; then
    BIN="$ROOT/drivers/c/build/pacemaker-stream"
    CORP="$ROOT/corpus/stream"
    ARTIFACT_PREFIX="$CRASH/stream-"
    STREAM_DEFINE="-DCRUCIBLE_FUZZ_STREAM"
    TAG="pacemaker-stream"
else
    BIN="$ROOT/drivers/c/build/pacemaker"
    CORP="$INTERESTING"
    ARTIFACT_PREFIX="$CRASH/"
    STREAM_DEFINE=""
    TAG="pacemaker"
fi

echo "==> [$TAG] generating C types from schema" >&2
rm -rf "$GEN"; mkdir -p "$GEN" "$INTERESTING" "$CORP" "$CRASH" "$ROOT/drivers/c/build"
"$SOFABGEN" --lang c --in "$ROOT/schema/probe.sofab.yaml" --out "$GEN" >&2

echo "==> [$TAG] building libFuzzer target (clang: fuzzer+ASan+UBSan)" >&2
# shellcheck disable=SC2086
"$CC" -DCRUCIBLE_LIBFUZZER $STREAM_DEFINE -std=c11 -O1 -g \
    -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer \
    -I"$GEN" -I"$CORELIB/src/include" -I"$ROOT/engine/mutator" \
    "$ROOT/drivers/c/driver.c" "$ROOT/engine/mutator/sofab_mutator.c" "$GEN/probe.c" \
    "$CORELIB/src/object.c" "$CORELIB/src/istream.c" "$CORELIB/src/ostream.c" \
    -o "$BIN" >&2

FINDINGS=""
for d in "$ROOT"/findings/*/; do [ -d "$d" ] && FINDINGS="$FINDINGS $d"; done

if [ "$STREAM" = "1" ]; then
    # --- streaming — how a seed becomes a header-prefixed input -------------
    # libFuzzer's seed dirs are read as raw candidate inputs, so a seed corpus
    # of plain messages would have its first 3 bytes misread as the mode/param
    # header. Build one header-prefixed copy of every message the block path
    # already knows about (corpus/interesting + corpus/seeds + findings),
    # deterministically keyed by content hash so every fuzz.sh run seeds the
    # same header for the same message rather than re-rolling it — the header
    # is chosen to sweep across the two axes, not to be a fixed choice.
    TMPSEEDS=$(mktemp -d)
    trap 'rm -rf "$TMPSEEDS"' EXIT
    echo "==> [pacemaker-stream] seeding (header-prefixed copies in a temp dir)" >&2
    # shellcheck disable=SC2086
    python3 - "$TMPSEEDS" "$INTERESTING" "$ROOT/corpus/seeds" $FINDINGS <<'PY'
import hashlib, os, sys

outdir = sys.argv[1]
srcdirs = sys.argv[2:]
n = 0
for d in srcdirs:
    if not os.path.isdir(d):
        continue
    for name in os.listdir(d):
        if name == ".gitkeep" or name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        if len(data) == 0:
            continue   # CONTRACT rule 4: an empty message is never fed at all
        h = hashlib.sha1(data).hexdigest()
        # Cycle deterministically through the sweep + the byte-at-a-time
        # extreme (CONTRACT.md "Decode side"): SPLIT at the midpoint, then
        # CHUNK=1, then CHUNK=7.
        variant = int(h, 16) % 3
        if variant == 0:
            mode, param = 0, min(len(data) // 2, 65535)
        elif variant == 1:
            mode, param = 1, 1
        else:
            mode, param = 1, 7
        header = bytes([mode & 1, param & 0xFF, (param >> 8) & 0xFF])
        with open(os.path.join(outdir, h), "wb") as out:
            out.write(header + data)
        n += 1
print(f"==> [pacemaker-stream] {n} seed(s) prepared", file=sys.stderr)
PY
    SEED_ARGS="$TMPSEEDS"
else
    SEED_ARGS="$ROOT/corpus/seeds"
fi

echo "==> [$TAG] fuzzing ${FUZZ_TIME}s (corpus: $(basename "$CORP"))" >&2
# First positional dir is the writable corpus; the rest are read-only seed dirs.
# shellcheck disable=SC2086
ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=0}" \
"$BIN" "$CORP" $SEED_ARGS $FINDINGS \
    -max_total_time="$FUZZ_TIME" -jobs="$FUZZ_JOBS" -print_final_stats=1 \
    -artifact_prefix="$ARTIFACT_PREFIX" 2>&1 | grep -iE "^#|cov:|NEW|crash|ERROR|DONE|stat::|SUMMARY|VIOLATION" || true

if [ "$STREAM" = "1" ]; then
    # --- streaming — harvest -------------------------------------------------
    # corpus/stream/ holds header-prefixed inputs; corpus/interesting/ (read by
    # every replay driver via run.sh) must only ever see the stripped message,
    # named by its own content hash so it merges with whatever the block path
    # already harvested there. Never allowed to kill the step (fuzz-go.sh's
    # rule): a partial harvest beats a run that reports nothing because one
    # file tripped an exception.
    echo "==> [pacemaker-stream] harvesting (strip header, keep the message)" >&2
    python3 - "$CORP" "$INTERESTING" <<'PY' || echo "==> [pacemaker-stream] WARNING: harvest step failed, see above" >&2
import hashlib, os, sys

corp, interesting = sys.argv[1], sys.argv[2]
new = 0
for name in os.listdir(corp):
    if name == ".gitkeep":
        continue
    path = os.path.join(corp, name)
    if not os.path.isfile(path):
        continue
    data = open(path, "rb").read()
    if len(data) <= 3:
        continue
    msg = data[3:]
    h = hashlib.sha1(msg).hexdigest()
    dst = os.path.join(interesting, h)
    if os.path.exists(dst):
        continue
    with open(dst, "wb") as out:
        out.write(msg)
    new += 1
print(f"==> [pacemaker-stream] {new} new input(s) harvested into interesting", file=sys.stderr)
PY

    # --- streaming — crash artifacts -----------------------------------------
    # Leave the header-prefixed artifact where libFuzzer wrote it, but also
    # print the replay recipe and write the stripped message beside it, so a
    # chunk-invariance violation found here is checkable against the replay
    # driver without hand-decoding the header (see decode_chunked's doc
    # comment in drivers/c/driver.c for what mode/param mean).
    for f in "$CRASH"/stream-*; do
        [ -f "$f" ] || continue
        case "$f" in *.msg.bin) continue ;; esac
        python3 - "$f" <<'PY' 2>&1 | sed 's/^/==> [pacemaker-stream] /' >&2 || true
import sys

path = sys.argv[1]
data = open(path, "rb").read()
if len(data) <= 3:
    print(f"{path}: too short to carry a header, skipping", file=sys.stderr)
    raise SystemExit(0)
mode, lo, hi = data[0] & 1, data[1], data[2]
param = lo | (hi << 8)
msg = data[3:]
with open(path + ".msg.bin", "wb") as out:
    out.write(msg)
var = "SOFAB_CHUNK" if mode else "SOFAB_SPLIT"
print(f"{path}: replay with {var}={param} over the {len(msg)}-byte "
      f"{path}.msg.bin", file=sys.stderr)
PY
    done
    echo "==> [pacemaker-stream] corpus/stream: $(ls "$CORP" | grep -vc gitkeep) inputs; corpus/interesting: $(ls "$INTERESTING" | grep -vc gitkeep) inputs" >&2
else
    echo "==> [pacemaker] corpus/interesting: $(ls "$INTERESTING" | grep -vc gitkeep) inputs; crashes: $(ls "$CRASH" | grep -vc gitkeep)" >&2
fi
echo "==> next: CORPUS=corpus/interesting ./scripts/run.sh   # differential over the grown corpus" >&2
