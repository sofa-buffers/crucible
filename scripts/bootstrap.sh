#!/usr/bin/env sh
# Project bootstrap: populate vendor/ with the corelibs and tools/ with sofabgen.
# Idempotent — safe to re-run.
#
# **Always current by default.** Crucible's whole job is to test the *latest* family
# against itself, so every run of this script:
#   - installs the **latest green sofabgen CI build** — the binary the generator's
#     ci.yml attaches to every successful run on the tracked branch, which is fresher
#     than the tagged-release cadence and carries unreleased-but-merged backends. When
#     no such artifact is reachable (e.g. before the generator starts attaching it, or
#     without a cross-repo token) it falls back **loudly** to the latest published
#     release, and
#   - fetches every cloned corelib to the tracked branch.
# There is no skip-if-present shortcut: a silently stale toolchain has bitten this repo
# before (a vendored sofabgen sat at 0.15.2 while the findings were being re-verified
# "on 0.16.1" — see docs/STATUS-LOG.md), and a differential fuzzer that lies about which
# versions it compared is worse than one that is slow. For the same reason the fallback
# is announced, never silent: the run always says which build it actually installed.
#
# **Which branch is tracked: this checkout's own.** A family-wide change lands on a
# same-named branch in every repo before it lands on main (e.g.
# poc/omit-all-default-sequences). Crucible on that branch is only meaningful against
# *that* branch of the corelibs and the generator, so the family ref defaults to
# Crucible's current branch; repos that do not carry it fall back to main, announced
# per repo. On main this is exactly the old behaviour. Override with FAMILY_BRANCH.
#
# For a non-main family branch the generator is **built from source at that branch**
# whenever its CI attaches no binary (the generator only publishes the sofabgen-<os>-<arch>
# artifacts on main). It never silently falls back to a main/release generator there:
# generated code from main against corelibs from a branch is a comparison of two
# different designs, and every divergence it produced would be an artifact of the mix.
#
# In a dev workspace where the corelib repos already sit next to this one (../corelib-*)
# they are symlinked (fast, live) — those are your working checkouts, so this script
# never touches them; refresh them in their own repos.
#
# Env:
#   FAMILY_BRANCH=<name>      family branch to track (default: this checkout's branch)
#   FAMILY_BRANCH=main        track the released family regardless of the local branch
#   SOFABGEN_VERSION=latest   (default) the latest green CI build from the tracked branch,
#                             or a source build of it when that branch publishes no binary
#   SOFABGEN_VERSION=vX.Y.Z   pin a published release instead (reproduce an old finding)
#   SOFABGEN_VERSION=source   build the generator from source at the tracked branch (needs Go)
#                             (`=main` is kept as the older spelling of the same thing)
#   SOFABGEN_BRANCH=<name>    generator branch only, when it differs from FAMILY_BRANCH
#   SOFABGEN_RUN=<run-id>     pin a specific generator ci.yml run instead of the latest green
#   SOFABGEN_ARTIFACT=<name>  artifact holding the binary (default: sofabgen-<os>-<arch>)
#   SOFABGEN_TOKEN=<token>    token for the generator Actions API (else GH_TOKEN/GITHUB_TOKEN/gh)
#   SOFABGEN_CI_REQUIRED=1    hard-fail instead of falling back to a release when CI is unreachable
#   NO_FETCH=1                skip all network access; use what is already vendored
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SIBLINGS=$(cd "$ROOT/.." && pwd)
mkdir -p "$ROOT/vendor" "$ROOT/tools"

SOFABGEN_VERSION="${SOFABGEN_VERSION:-latest}"
NO_FETCH="${NO_FETCH:-0}"
GEN_REPO="https://github.com/sofa-buffers/generator"

# Corelibs needed by the current drivers. Extend as languages are added.
CORELIBS="corelib-c-cpp corelib-cpp corelib-cs corelib-dart corelib-go corelib-java corelib-py corelib-rs corelib-rs-no-std corelib-ts corelib-zig"

# ------------------------------------------------------------ family branch ----
# Default: whatever branch this checkout is on. In Actions, HEAD is detached, so read
# the branch from the environment there (GITHUB_HEAD_REF on a PR, GITHUB_REF_NAME on a
# push) before falling back to git.
FAMILY_BRANCH="${FAMILY_BRANCH:-}"
if [ -z "$FAMILY_BRANCH" ]; then
    FAMILY_BRANCH="${GITHUB_HEAD_REF:-}"
    [ -n "$FAMILY_BRANCH" ] || FAMILY_BRANCH="${GITHUB_REF_NAME:-}"
    [ -n "$FAMILY_BRANCH" ] || FAMILY_BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)
fi
case "$FAMILY_BRANCH" in ""|HEAD) FAMILY_BRANCH=main ;; esac
[ "$FAMILY_BRANCH" = "main" ] || echo "==> family branch: $FAMILY_BRANCH (repos without it fall back to main)" >&2

# The branch a given remote actually carries: $FAMILY_BRANCH if it has it, else main.
# Prints the ref on stdout; any note about a fallback goes to stderr, by the caller.
remote_ref() {  # $1 = remote URL or a path to a checkout with an `origin`
    if [ "$FAMILY_BRANCH" != "main" ] && [ "$NO_FETCH" != "1" ] \
       && git ls-remote --heads "$1" "$FAMILY_BRANCH" 2>/dev/null | grep -q .; then
        printf '%s' "$FAMILY_BRANCH"
    else
        printf 'main'
    fi
}

# ---------------------------------------------------------------- corelibs ----
for lib in $CORELIBS; do
    dst="$ROOT/vendor/$lib"
    url="https://github.com/sofa-buffers/$lib.git"

    if [ ! -e "$dst" ]; then
        if [ -d "$SIBLINGS/$lib" ]; then
            echo "==> vendor/$lib -> symlink to $SIBLINGS/$lib" >&2
            ln -s "$SIBLINGS/$lib" "$dst"
        else
            [ "$NO_FETCH" = "1" ] && { echo "error: vendor/$lib missing and NO_FETCH=1" >&2; exit 1; }
            ref=$(remote_ref "$url")
            [ "$ref" = "$FAMILY_BRANCH" ] || echo "==> vendor/$lib has no $FAMILY_BRANCH — using main" >&2
            echo "==> vendor/$lib -> clone from GitHub ($ref)" >&2
            git clone --depth 1 --branch "$ref" "$url" "$dst"
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

    # Ask the checkout's own remote, not the constructed URL, so a fork/mirror answers
    # for itself.
    ref=$(remote_ref "$(git -C "$dst" remote get-url origin 2>/dev/null || echo "$url")")
    [ "$ref" = "$FAMILY_BRANCH" ] || echo "==> vendor/$lib has no $FAMILY_BRANCH — using main" >&2

    before=$(git -C "$dst" rev-parse --short HEAD)
    git -C "$dst" fetch --depth 1 -q origin "$ref"
    # -B moves the *named* local branch onto the fetched tip, so `git -C vendor/$lib
    # branch --show-current` names the branch actually under test — a plain `reset
    # --hard` would leave the checkout claiming `main` while holding branch content.
    git -C "$dst" checkout -q -B "$ref" FETCH_HEAD
    after=$(git -C "$dst" rev-parse --short HEAD)
    if [ "$before" = "$after" ]; then
        echo "==> vendor/$lib @ $after (origin/$ref, unchanged)" >&2
    else
        echo "==> vendor/$lib $before -> $after (origin/$ref)" >&2
    fi
done

# ---------------------------------------------------------------- sofabgen ----
SG="$ROOT/tools/sofabgen"

# The generator branch to track. It follows the family branch unless overridden, and
# degrades to main when the generator does not carry that branch.
GEN_BRANCH="${SOFABGEN_BRANCH:-}"
if [ -z "$GEN_BRANCH" ]; then
    GEN_BRANCH=$(remote_ref "$GEN_REPO.git")
    [ "$GEN_BRANCH" = "$FAMILY_BRANCH" ] || echo "==> generator has no $FAMILY_BRANCH — using main" >&2
fi

sofabgen_build_from_source() {  # $1 = branch
    _br="$1"
    command -v go >/dev/null || { echo "error: building sofabgen from source needs Go" >&2; exit 1; }
    echo "==> tools/sofabgen <- building generator@$_br" >&2
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    git clone --depth 1 -q --branch "$_br" "$GEN_REPO.git" "$tmp"
    ( cd "$tmp" && go build -o "$SG" ./cmd/sofabgen )
    echo "==> tools/sofabgen built from generator@$_br $(git -C "$tmp" rev-parse --short HEAD) ($("$SG" --version 2>/dev/null | head -1))" >&2
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

# A token for the generator's Actions API. Workflow-run artifacts are NOT anonymously
# downloadable even on a public repo, so we need one. Locally `gh auth token` supplies it;
# in CI pass a token with actions:read on sofa-buffers/generator via SOFABGEN_TOKEN.
gh_token() {
    if   [ -n "${SOFABGEN_TOKEN:-}" ]; then printf '%s' "$SOFABGEN_TOKEN"
    elif [ -n "${GH_TOKEN:-}" ];       then printf '%s' "$GH_TOKEN"
    elif [ -n "${GITHUB_TOKEN:-}" ];   then printf '%s' "$GITHUB_TOKEN"
    elif command -v gh >/dev/null 2>&1; then gh auth token 2>/dev/null
    else return 1; fi
}

# The /releases/latest redirect yields the newest tag without gh or jq.
latest_release_tag() {
    _url=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$GEN_REPO/releases/latest" 2>/dev/null) || return 1
    _tag=${_url##*/tag/}
    [ -n "$_tag" ] && [ "$_tag" != "$_url" ] || return 1
    printf '%s' "$_tag"
}

# Install a tagged release asset (checksum-verified). Arg: the tag, e.g. v0.19.7.
sofabgen_from_release() {
    _tag="$1"
    _have=$("$SG" --version 2>/dev/null | head -1 || true)
    if [ "v$_have" = "$_tag" ]; then
        echo "==> tools/sofabgen $_tag (already installed)" >&2
        return 0
    fi
    _asset=$(sofabgen_asset)
    _base="$GEN_REPO/releases/download/$_tag"
    echo "==> tools/sofabgen ${_have:-none} -> $_tag  ($_asset)" >&2
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -o "$tmp/sofabgen" "$_base/$_asset" \
        || { echo "error: download failed: $_base/$_asset" >&2; return 1; }
    # The release ships a .sha256 per asset — an unverified toolchain binary is
    # exactly the kind of thing this repo should not take on trust.
    if curl -fsSL -o "$tmp/sofabgen.sha256" "$_base/$_asset.sha256" 2>/dev/null; then
        _want=$(cut -d' ' -f1 < "$tmp/sofabgen.sha256")
        _got=$(sha256_of "$tmp/sofabgen")
        [ "$_want" = "$_got" ] || { echo "error: sha256 mismatch for $_asset (want $_want, got $_got)" >&2; return 1; }
        echo "==> tools/sofabgen sha256 verified" >&2
    else
        echo "==> tools/sofabgen WARNING: no .sha256 published for $_asset — not verified" >&2
    fi
    chmod +x "$tmp/sofabgen"
    mv "$tmp/sofabgen" "$SG"
}

# Install the binary the generator's ci.yml attached to its latest green run on main.
# Returns non-zero (without exiting) on any recoverable miss so the caller can fall back.
sofabgen_from_ci() {
    command -v python3 >/dev/null 2>&1 || { echo "==> tools/sofabgen: CI fetch needs python3" >&2; return 1; }
    _tok=$(gh_token) || { echo "==> tools/sofabgen: CI fetch needs a token (SOFABGEN_TOKEN/GH_TOKEN or 'gh auth login')" >&2; return 1; }
    [ -n "$_tok" ] || { echo "==> tools/sofabgen: empty token for the generator Actions API" >&2; return 1; }

    _asset="${SOFABGEN_ARTIFACT:-$(sofabgen_asset)}"
    _api="https://api.github.com/repos/sofa-buffers/generator"
    _ah="Authorization: Bearer $_tok"
    _aj="Accept: application/vnd.github+json"

    if [ -n "${SOFABGEN_RUN:-}" ]; then
        _run="$SOFABGEN_RUN"
    else
        _run=$(curl -fsSL -H "$_ah" -H "$_aj" \
            "$_api/actions/workflows/ci.yml/runs?branch=$GEN_BRANCH&status=success&per_page=1" 2>/dev/null \
            | python3 -c 'import sys,json
try: r=json.load(sys.stdin).get("workflow_runs",[])
except Exception: r=[]
print(r[0]["id"] if r else "")' 2>/dev/null)
        [ -n "$_run" ] || { echo "==> tools/sofabgen: no green ci.yml run on generator@$GEN_BRANCH (token needs actions:read on sofa-buffers/generator)" >&2; return 1; }
    fi

    _dl=$(curl -fsSL -H "$_ah" -H "$_aj" "$_api/actions/runs/$_run/artifacts?per_page=100" 2>/dev/null \
        | A="$_asset" python3 -c 'import sys,json,os
try: a=json.load(sys.stdin).get("artifacts",[])
except Exception: a=[]
want=os.environ.get("A","")
m=[x for x in a if x["name"]==want and not x["expired"]]
print(m[0]["archive_download_url"] if m else "")' 2>/dev/null)
    [ -n "$_dl" ] || { echo "==> tools/sofabgen: generator run $_run has no unexpired artifact '$_asset' (set SOFABGEN_ARTIFACT to match ci.yml)" >&2; return 1; }

    echo "==> tools/sofabgen <- CI artifact '$_asset' from generator run $_run" >&2
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -H "$_ah" -o "$tmp/art.zip" "$_dl" 2>/dev/null \
        || { echo "==> tools/sofabgen: artifact download failed for run $_run" >&2; return 1; }
    # Actions artifacts are always zipped; unpack and locate the sofabgen binary inside.
    # The artifact carries the executable plus a sibling <asset>.sha256 — so exclude the
    # checksum file when picking the binary, then use it to verify (same rigor as a release).
    python3 -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$tmp/art.zip" "$tmp/x" 2>/dev/null \
        || { echo "==> tools/sofabgen: could not unzip artifact '$_asset'" >&2; return 1; }
    _bin=$(find "$tmp/x" -type f -name sofabgen 2>/dev/null | head -1)
    [ -n "$_bin" ] || _bin=$(find "$tmp/x" -type f -name "$_asset" 2>/dev/null | head -1)
    [ -n "$_bin" ] || _bin=$(find "$tmp/x" -type f ! -name '*.sha256' ! -name '*.txt' ! -name '*.md' 2>/dev/null | head -1)
    [ -n "$_bin" ] || { echo "==> tools/sofabgen: no binary inside artifact '$_asset'" >&2; return 1; }
    _sum=$(find "$tmp/x" -type f -name '*.sha256' 2>/dev/null | head -1)
    if [ -n "$_sum" ]; then
        _want=$(cut -d' ' -f1 < "$_sum")
        _got=$(sha256_of "$_bin")
        [ "$_want" = "$_got" ] || { echo "==> tools/sofabgen: sha256 mismatch in artifact '$_asset' (want $_want, got $_got)" >&2; return 1; }
        echo "==> tools/sofabgen sha256 verified (CI artifact)" >&2
    else
        echo "==> tools/sofabgen WARNING: no .sha256 in artifact '$_asset' — not verified" >&2
    fi
    chmod +x "$_bin"
    mv "$_bin" "$SG"
    echo "==> tools/sofabgen installed from CI run $_run ($("$SG" --version 2>/dev/null | head -1))" >&2
}

if [ "$SOFABGEN_VERSION" = "source" ] || [ "$SOFABGEN_VERSION" = "main" ]; then
    # `=main` predates branch tracking and used to mean "build from generator@main";
    # it now means "build from the tracked branch", which on main is the same thing.
    sofabgen_build_from_source "$GEN_BRANCH"
elif [ "$NO_FETCH" = "1" ]; then
    [ -x "$SG" ] || { echo "error: tools/sofabgen missing and NO_FETCH=1" >&2; exit 1; }
    echo "==> tools/sofabgen $("$SG" --version 2>/dev/null | head -1) (NO_FETCH)" >&2
elif [ "$SOFABGEN_VERSION" = "latest" ] || [ "$SOFABGEN_VERSION" = "ci" ]; then
    # Preferred path: the freshest CI build of the tracked branch.
    if ! sofabgen_from_ci; then
        [ "${SOFABGEN_CI_REQUIRED:-0}" = "1" ] && { echo "error: CI build unavailable and SOFABGEN_CI_REQUIRED=1" >&2; exit 1; }
        if [ "$GEN_BRANCH" != "main" ]; then
            # A release (or a main CI build) is generator@main — pairing it with corelibs
            # from a branch would compare two different designs and blame the mismatch on
            # the implementations. Build the branch instead; if that is impossible, stop.
            echo "==> tools/sofabgen: no CI binary on generator@$GEN_BRANCH — building it from source (a release would be main's generator)" >&2
            sofabgen_build_from_source "$GEN_BRANCH"
        else
            # On main, fall back — loudly — to the latest release so a repo without a
            # cross-repo token still bootstraps, always saying which build it used.
            _rel=$(latest_release_tag) || { echo "error: CI build unavailable and could not resolve a release to fall back to" >&2; exit 1; }
            echo "==> tools/sofabgen: CI build unavailable — FALLING BACK to latest release $_rel" >&2
            sofabgen_from_release "$_rel" || { echo "error: release fallback failed for $_rel" >&2; exit 1; }
        fi
    fi
else
    # An explicit tag pins a published release (reproduce an old finding).
    sofabgen_from_release "$SOFABGEN_VERSION" || { echo "error: could not install sofabgen $SOFABGEN_VERSION" >&2; exit 1; }
fi

echo "==> bootstrap complete — family branch $FAMILY_BRANCH, sofabgen $("$SG" --version 2>/dev/null | head -1)" >&2
"$SG" --print-defaults >/dev/null 2>&1 || true
echo "vendored: $CORELIBS" >&2
