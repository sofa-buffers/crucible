#!/usr/bin/env sh
# Project bootstrap: populate vendor/ with the corelibs and tools/ with sofabgen.
# Idempotent — safe to re-run.
#
# **Always current by default.** Crucible's whole job is to test the *latest* family
# against itself, so every run of this script:
#   - installs the **latest published sofabgen release** binary (checksum-verified), and
#   - fetches every cloned corelib to **origin/main**.
# There is no skip-if-present shortcut: a silently stale toolchain has bitten this repo
# before (a vendored sofabgen sat at 0.15.2 while the findings were being re-verified
# "on 0.16.1" — see docs/STATUS.md), and a differential fuzzer that lies about which
# versions it compared is worse than one that is slow.
#
# In a dev workspace where the corelib repos already sit next to this one (../corelib-*)
# they are symlinked (fast, live) — those are your working checkouts, so this script
# never touches them; refresh them in their own repos.
#
# Env:
#   SOFABGEN_VERSION=vX.Y.Z   pin a release instead of latest (reproduce an old finding)
#   SOFABGEN_VERSION=main     build from generator@main (needs Go) — for unreleased fixes
#   NO_FETCH=1                skip all network access; use what is already vendored
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SIBLINGS=$(cd "$ROOT/.." && pwd)
mkdir -p "$ROOT/vendor" "$ROOT/tools"

SOFABGEN_VERSION="${SOFABGEN_VERSION:-latest}"
NO_FETCH="${NO_FETCH:-0}"
GEN_REPO="https://github.com/sofa-buffers/generator"

# Corelibs needed by the current drivers. Extend as languages are added.
CORELIBS="corelib-c-cpp corelib-cpp corelib-cs corelib-go corelib-java corelib-py corelib-rs corelib-rs-no-std corelib-ts corelib-zig"

# ---------------------------------------------------------------- corelibs ----
for lib in $CORELIBS; do
    dst="$ROOT/vendor/$lib"

    if [ ! -e "$dst" ]; then
        if [ -d "$SIBLINGS/$lib" ]; then
            echo "==> vendor/$lib -> symlink to $SIBLINGS/$lib" >&2
            ln -s "$SIBLINGS/$lib" "$dst"
        else
            [ "$NO_FETCH" = "1" ] && { echo "error: vendor/$lib missing and NO_FETCH=1" >&2; exit 1; }
            echo "==> vendor/$lib -> clone from GitHub" >&2
            git clone --depth 1 "https://github.com/sofa-buffers/$lib.git" "$dst"
        fi
        continue
    fi

    # A symlinked sibling is someone's live checkout — never reset it.
    if [ -L "$dst" ]; then
        echo "==> vendor/$lib symlinked (live sibling; refresh it in its own repo)" >&2
        continue
    fi
    [ -d "$dst/.git" ] || { echo "==> vendor/$lib present (not a git checkout)" >&2; continue; }
    [ "$NO_FETCH" = "1" ] && { echo "==> vendor/$lib @ $(git -C "$dst" rev-parse --short HEAD) (NO_FETCH)" >&2; continue; }

    # Never silently discard someone's work: vendor/ is a dependency, but if it *is*
    # dirty that is a deliberate local edit (a corelib patch under test). Warn, skip.
    if [ -n "$(git -C "$dst" status --porcelain 2>/dev/null)" ]; then
        echo "==> vendor/$lib has LOCAL CHANGES — not resetting. Commit/stash, or delete it to re-clone." >&2
        continue
    fi

    before=$(git -C "$dst" rev-parse --short HEAD)
    git -C "$dst" fetch --depth 1 -q origin main
    git -C "$dst" reset --hard -q FETCH_HEAD
    after=$(git -C "$dst" rev-parse --short HEAD)
    if [ "$before" = "$after" ]; then
        echo "==> vendor/$lib @ $after (origin/main, unchanged)" >&2
    else
        echo "==> vendor/$lib $before -> $after (origin/main)" >&2
    fi
done

# ---------------------------------------------------------------- sofabgen ----
SG="$ROOT/tools/sofabgen"

sofabgen_build_from_main() {
    command -v go >/dev/null || { echo "error: SOFABGEN_VERSION=main needs Go" >&2; exit 1; }
    echo "==> tools/sofabgen <- building generator@main" >&2
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    git clone --depth 1 -q "$GEN_REPO.git" "$tmp"
    ( cd "$tmp" && go build -o "$SG" ./cmd/sofabgen )
}

sofabgen_asset() {
    _os=$(uname -s | tr '[:upper:]' '[:lower:]')
    case "$(uname -m)" in
        x86_64|amd64)  _arch=amd64 ;;
        aarch64|arm64) _arch=arm64 ;;
        i386|i686)     _arch=386 ;;
        armv*|arm)     _arch=arm ;;
        *) echo "error: unsupported arch $(uname -m)" >&2; exit 1 ;;
    esac
    case "$_os" in
        linux|darwin) echo "sofabgen-${_os}-${_arch}" ;;
        *) echo "error: unsupported OS $_os (release assets: linux, darwin, windows)" >&2; exit 1 ;;
    esac
}

sha256_of() {
    if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if [ "$SOFABGEN_VERSION" = "main" ]; then
    sofabgen_build_from_main
elif [ "$NO_FETCH" = "1" ]; then
    [ -x "$SG" ] || { echo "error: tools/sofabgen missing and NO_FETCH=1" >&2; exit 1; }
    echo "==> tools/sofabgen $("$SG" --version 2>/dev/null | head -1) (NO_FETCH)" >&2
else
    # Resolve the tag. The /releases/latest redirect gives it without gh or jq.
    if [ "$SOFABGEN_VERSION" = "latest" ]; then
        url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$GEN_REPO/releases/latest")
        tag=${url##*/tag/}
        [ -n "$tag" ] && [ "$tag" != "$url" ] || { echo "error: could not resolve the latest release tag" >&2; exit 1; }
    else
        tag="$SOFABGEN_VERSION"
    fi

    have=$("$SG" --version 2>/dev/null | head -1 || true)
    if [ "v$have" = "$tag" ]; then
        echo "==> tools/sofabgen $tag (already latest)" >&2
    else
        asset=$(sofabgen_asset)
        base="$GEN_REPO/releases/download/$tag"
        echo "==> tools/sofabgen ${have:-none} -> $tag  ($asset)" >&2
        tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
        curl -fsSL -o "$tmp/sofabgen" "$base/$asset" \
            || { echo "error: download failed: $base/$asset" >&2; exit 1; }
        # The release ships a .sha256 per asset — an unverified toolchain binary is
        # exactly the kind of thing this repo should not take on trust.
        if curl -fsSL -o "$tmp/sofabgen.sha256" "$base/$asset.sha256" 2>/dev/null; then
            want=$(cut -d' ' -f1 < "$tmp/sofabgen.sha256")
            got=$(sha256_of "$tmp/sofabgen")
            [ "$want" = "$got" ] || { echo "error: sha256 mismatch for $asset (want $want, got $got)" >&2; exit 1; }
            echo "==> tools/sofabgen sha256 verified" >&2
        else
            echo "==> tools/sofabgen WARNING: no .sha256 published for $asset — not verified" >&2
        fi
        chmod +x "$tmp/sofabgen"
        mv "$tmp/sofabgen" "$SG"
    fi
fi

echo "==> bootstrap complete — sofabgen $("$SG" --version 2>/dev/null | head -1)" >&2
"$SG" --print-defaults >/dev/null 2>&1 || true
echo "vendored: $CORELIBS" >&2
