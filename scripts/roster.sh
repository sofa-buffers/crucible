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
    *)
        echo "usage: roster.sh {list|build} [tag]" >&2
        exit 2
        ;;
esac
