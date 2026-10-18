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
#   SKIP_BUILD=1 ./scripts/roster.sh build   # reuse the last build if nothing it depends on changed
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
        # SKIP_BUILD=1 reuses the previous build of this roster subset when nothing a build
        # depends on has changed since: the stamp covers every variable a drivers/*/build.sh
        # or materialize_gen.py reads, the CONTENT of the schema (and the *.defs.yaml it may
        # import) and of the materialized table (a mktemp path differs per run, its content
        # does not), and the checkout (HEAD + `git status`). Any difference, a missing
        # binary or no stamp at all: build as usual. CI sets it so that consecutive steps on
        # one schema stop rebuilding twenty drivers each; a stale binary (a SCHEMA switch,
        # limit mode) can never be reused, because the switch changes the stamp.
        _stampfile="$ROOT/drivers/.roster-build-${want:-all}"
        _stamp=$(
            echo "tag=$want"
            for _v in LIMITS LIMCFG SANITIZE SAN CC CXX ZIG RUSTFLAGS KONAN_DATA_DIR KLIB JAR CS_TFM SOFAB_RS_CORELIB; do
                eval "echo $_v=\${$_v-}"
            done
            _schema="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
            cat "$_schema" "$(dirname "$_schema")"/*.defs.yaml 2>/dev/null | cksum
            [ -n "${SOFAB_MATERIALIZE_SCHEMA:-}" ] && cksum < "$SOFAB_MATERIALIZE_SCHEMA"
            # `|| true`: under `set -e` a failing git (no repository; a container whose user
            # does not own the checkout — "dubious ownership", exit 128) would end the build
            git -C "$ROOT" rev-parse HEAD 2>/dev/null || true
            git -C "$ROOT" status --porcelain 2>/dev/null || true
            # what bootstrap.sh installs (gitignored, so `git status` cannot see it): the
            # generator binary and each corelib's commit — not their `status`, since a
            # build leaves artifacts inside vendor/
            [ -f "$ROOT/tools/sofabgen" ] && cksum < "$ROOT/tools/sofabgen"
            for _d in "$ROOT"/vendor/*/; do git -C "$_d" rev-parse HEAD 2>/dev/null || true; done
        )
        _stamp=$(printf '%s\n' "$_stamp" | cksum)
        if [ "${SKIP_BUILD:-0}" = "1" ] && [ -f "$_stampfile" ] && [ "$(head -n 1 "$_stampfile")" = "$_stamp" ]; then
            _ok=1
            for _bin in $(sed -n '2,$p' "$_stampfile" | sed -n 's/^[^:]*://p'); do
                [ -e "$_bin" ] || _ok=0
            done
            if [ "$_ok" = "1" ]; then
                echo "==> SKIP_BUILD: roster ${want:-all} unchanged since its last build — reusing it" >&2
                sed -n '2,$p' "$_stampfile" | while IFS= read -r _line; do
                    printf -- '--driver\n%s\n' "$_line"
                done
                exit 0
            fi
        fi
        rm -f "$_stampfile"
        _built=""
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
            _built="$_built$_name:$_bin
"
            IFS='
'
        done
        IFS=$_oldifs
        # every build succeeded (set -e): record what was built, for SKIP_BUILD
        printf '%s\n%s' "$_stamp" "$_built" > "$_stampfile"
        ;;
    caps)
        # `caps <encode|chunked|encode_fail|reuse> [tag]` — the roster names whose backend declares the
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
            encode|chunked|encode_fail|reuse) ;;
            *) echo "usage: roster.sh caps {encode|chunked|encode_fail|reuse} [tag]" >&2; exit 2 ;;
        esac
        rows | while read -r name builder arg _tags _binary; do
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
                encode_fail)
                    # SOFAB_ENCODE_FAIL: whether the driver can hand the encoder a
                    # destination that is too small. `no` is the declared absence.
                    v=$(sed -n 's/^encode_fail=//p' "$meta")
                    [ -n "$v" ] && [ "$v" != "no" ] && printf '%s\n' "$name"
                    ;;
                reuse)
                    # SOFAB_REUSE: whether the generated decode takes a destination
                    # the caller may reuse. `all`, `none`, or the build.sh variant
                    # arguments that have it — per variant, because rust's rs has it
                    # and its rs-no-std rows do not (corelib-rs-no-std#133).
                    v=$(sed -n 's/^reuse_decode=//p' "$meta")
                    case "$v" in
                        all) printf '%s\n' "$name" ;;
                        ""|none) ;;
                        *) case ",$v," in *",$arg,"*) printf '%s\n' "$name" ;; esac ;;
                    esac
                    ;;
            esac
        done
        ;;
    *)
        echo "usage: roster.sh {list|build|caps} [tag]" >&2
        exit 2
        ;;
esac
