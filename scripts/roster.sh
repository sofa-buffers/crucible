#!/usr/bin/env sh
# Read `drivers/roster` — the single source of truth for who is in the family — and
# either list it or build it. Every shell consumer goes through here so the roster is
# never restated: scripts/run.sh, scripts/materialize.sh, scripts/run-limits.sh.
# The Python side reads the same file via oracle/roster.py.
#
#   ./scripts/roster.sh list          # name builder arg tags binary, one per line
#   ./scripts/roster.sh list limits   # only rows tagged `limits`
#   ./scripts/roster.sh build         # build each, print `--driver name:path` lines
#   ./scripts/roster.sh build limits  # ... for the tagged subset only
#
# `build` prints its progress on stderr and the comparator arguments on stdout, one
# per line, so a caller can splice them into "$@" with IFS=newline. It exits non-zero
# if any build fails — a roster whose drivers did not all build must not silently
# compare a subset.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ROSTER="$ROOT/drivers/roster"

cmd="${1:-list}"
want="${2:-}"

# Strip comments/blank lines, then keep rows carrying $want in their tag list.
rows() {
    sed -e 's/#.*//' "$ROSTER" | while read -r name builder arg tags binary; do
        [ -n "${name:-}" ] || continue
        if [ -n "$want" ]; then
            case ",$tags," in *",$want,"*) ;; *) continue ;; esac
        fi
        printf '%s %s %s %s %s\n' "$name" "$builder" "$arg" "$tags" "$binary"
    done
}

case "$cmd" in
    list)
        rows
        ;;
    build)
        # A failure inside the loop cannot abort the parent through a pipe, so the
        # rows are materialized first and the loop runs in this shell under `set -e`.
        _rows=$(rows)
        _oldifs=$IFS
        IFS='
'
        for _row in $_rows; do
            IFS=$_oldifs
            # shellcheck disable=SC2086
            set -- $_row
            _name=$1 _builder=$2 _arg=$3 _binary=$5
            [ "$_arg" = "-" ] && _arg=""
            # shellcheck disable=SC2086
            _bin=$(sh "$ROOT/drivers/$_builder/build.sh" $_arg)
            printf '==> %-14s %s\n' "$_name:" "$_bin" >&2
            printf -- '--driver\n%s:%s\n' "$_name" "$_bin"
            IFS='
'
        done
        IFS=$_oldifs
        ;;
    caps)
        # `caps <encode|chunked> [tag]` — the roster names whose backend declares the
        # capability in `drivers/<builder>/meta`.
        #
        # This is what the two streaming gates use instead of a hand-written driver
        # list. The lists were the bug: `go` sat outside the encode gate for eleven
        # days because a name was missing from a script, and a missing name looks
        # exactly like a declared exception. Derived this way, participation follows
        # from the roster, and staying out of a gate requires a capability the `meta`
        # denies — a statement someone had to write down, in the file that owns it.
        #
        # Note the mapping is not one-to-one: the four `cpp` roster rows share
        # `drivers/cpp/meta`, and the two `python` rows share `drivers/python/meta`.
        # That is correct — the surfaces are a property of the backend, not of the
        # build variant.
        cap="${2:-}"
        want="${3:-}"
        case "$cap" in
            encode|chunked) ;;
            *) echo "usage: roster.sh caps {encode|chunked} [tag]" >&2; exit 2 ;;
        esac
        rows | while read -r name builder _arg _tags _binary; do
            meta="$ROOT/drivers/$builder/meta"
            [ -f "$meta" ] || continue
            case "$cap" in
                encode)
                    # A backend with no declared surface has nothing to compare.
                    v=$(sed -n 's/^encode_surfaces=//p' "$meta")
                    [ -n "$v" ] && printf '%s\n' "$name"
                    ;;
                chunked)
                    # `none` is the declared absence (corelib-go has no resumable
                    # decoder); push and pull both participate.
                    v=$(sed -n 's/^chunked_decode=//p' "$meta")
                    [ -n "$v" ] && [ "$v" != "none" ] && printf '%s\n' "$name"
                    ;;
            esac
        done
        ;;
    *)
        echo "usage: roster.sh {list|build|caps} [tag]" >&2
        exit 2
        ;;
esac
