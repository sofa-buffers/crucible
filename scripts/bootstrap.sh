#!/usr/bin/env sh
# One-time project bootstrap: populate vendor/ with the corelibs and tools/ with
# sofabgen. Idempotent — safe to re-run.
#
# In a dev workspace where the corelib repos already sit next to this one
# (../corelib-*), they are symlinked (fast, live). Otherwise they are cloned
# from GitHub. We track the corelib/generator `main` branches (no version pin) —
# this mirrors the repo's "latest main" re-verification convention (STATUS.md).
#
# REFRESH=1 pulls updates into an already-bootstrapped tree: cloned corelibs are
# fast-forwarded to origin's tip and sofabgen is rebuilt from generator main.
# Symlinked siblings are live checkouts — refresh those in their own repos. The
# plain (unset) run stays skip-if-present so it is cheap to re-invoke.
set -eu

REFRESH="${REFRESH:-0}"

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SIBLINGS=$(cd "$ROOT/.." && pwd)
mkdir -p "$ROOT/vendor" "$ROOT/tools"

# Corelibs needed by the current drivers. Extend as languages are added.
CORELIBS="corelib-c-cpp corelib-cpp corelib-cs corelib-go corelib-java corelib-py corelib-rs corelib-rs-no-std corelib-ts corelib-zig"

for lib in $CORELIBS; do
    dst="$ROOT/vendor/$lib"
    if [ -e "$dst" ]; then
        # Symlinks are live siblings — refresh them in their own repos. Only pull
        # cloned (real git dir) checkouts, and only under REFRESH.
        if [ "$REFRESH" = "1" ] && [ ! -L "$dst" ] && [ -d "$dst/.git" ]; then
            echo "==> vendor/$lib -> refresh (fetch + reset to origin main)" >&2
            git -C "$dst" fetch --depth 1 origin >&2
            git -C "$dst" reset --hard origin/HEAD >&2
        else
            echo "==> vendor/$lib present" >&2
        fi
        continue
    fi
    if [ -d "$SIBLINGS/$lib" ]; then
        echo "==> vendor/$lib -> symlink to $SIBLINGS/$lib" >&2
        ln -s "$SIBLINGS/$lib" "$dst"
    else
        echo "==> vendor/$lib -> clone from GitHub" >&2
        git clone --depth 1 "https://github.com/sofa-buffers/$lib.git" "$dst"
    fi
done

# sofabgen: prefer a sibling arena's prebuilt binary, else build from a sibling
# generator checkout, else clone+build. Under REFRESH we skip the opaque arena
# binary (it may lag generator main / v0.16.2) and build from source.
SG="$ROOT/tools/sofabgen"
if [ -x "$SG" ] && [ "$REFRESH" != "1" ]; then
    echo "==> tools/sofabgen present" >&2
elif [ "$REFRESH" != "1" ] && [ -x "$SIBLINGS/arena/tools/sofabgen" ]; then
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
