#!/usr/bin/env sh
# One-time project bootstrap: populate vendor/ with the corelibs and tools/ with
# sofabgen. Idempotent — safe to re-run.
#
# In a dev workspace where the corelib repos already sit next to this one
# (../corelib-*), they are symlinked (fast, live). Otherwise they are cloned
# from GitHub. Override versions/pins as this matures.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SIBLINGS=$(cd "$ROOT/.." && pwd)
mkdir -p "$ROOT/vendor" "$ROOT/tools"

# Corelibs needed by the current drivers. Extend as languages are added.
CORELIBS="corelib-c-cpp corelib-go"

for lib in $CORELIBS; do
    dst="$ROOT/vendor/$lib"
    [ -e "$dst" ] && { echo "==> vendor/$lib present" >&2; continue; }
    if [ -d "$SIBLINGS/$lib" ]; then
        echo "==> vendor/$lib -> symlink to $SIBLINGS/$lib" >&2
        ln -s "$SIBLINGS/$lib" "$dst"
    else
        echo "==> vendor/$lib -> clone from GitHub" >&2
        git clone --depth 1 "https://github.com/sofa-buffers/$lib.git" "$dst"
    fi
done

# sofabgen: prefer a sibling arena's prebuilt binary, else build from a sibling
# generator checkout, else clone+build.
SG="$ROOT/tools/sofabgen"
if [ -x "$SG" ]; then
    echo "==> tools/sofabgen present" >&2
elif [ -x "$SIBLINGS/arena/tools/sofabgen" ]; then
    echo "==> tools/sofabgen <- arena/tools/sofabgen" >&2
    cp "$SIBLINGS/arena/tools/sofabgen" "$SG"
elif [ -d "$SIBLINGS/generator" ]; then
    echo "==> tools/sofabgen <- building sibling generator" >&2
    ( cd "$SIBLINGS/generator" && go build -o "$SG" ./cmd/sofabgen )
else
    echo "==> tools/sofabgen <- clone+build generator" >&2
    tmp=$(mktemp -d)
    git clone --depth 1 https://github.com/sofa-buffers/generator.git "$tmp"
    ( cd "$tmp" && go build -o "$SG" ./cmd/sofabgen )
    rm -rf "$tmp"
fi

echo "==> bootstrap complete" >&2
"$SG" --print-defaults >/dev/null 2>&1 || true
echo "vendored: $CORELIBS" >&2
