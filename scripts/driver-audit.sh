#!/usr/bin/env sh
# Per-driver participation ledger — what each roster entry declares, and which gates
# that declaration puts it in.
#
# The problem this exists for: a driver joins the family, lands in the gates that read
# the roster, and is silently absent from the ones that do not. `go` sat outside the
# encode gate for eleven days that way — its backend had all three surfaces, its `meta`
# said so, and a name was simply missing from a script. Nothing was red, because nothing
# was looking. `scripts/roster.sh caps` fixed the mechanism; this fixes the *visibility*,
# and it runs over every entry rather than only new ones, because "the roster entry that
# quietly does less" is not a new-driver problem.
#
# It asserts only what a declaration can be checked against statically — no builds, no
# corpora, so it is cheap enough to block on. What it CANNOT tell you is whether a
# declaration is true; that is what the gates' own hard-fails and the announcement
# assertions are for (drivers/common/CONTRACT.md).
#
#   ./scripts/driver-audit.sh          # ledger + assertions, non-zero on a gap
#
# Exit 0 = every entry declares what the gates need to place it.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ROSTER="$ROOT/drivers/roster"

fail=0
note() { printf '  !! %s\n' "$1" >&2; fail=$((fail + 1)); }

# The two derived gate rosters, read once (scripts/roster.sh owns the derivation).
enc_names=$("$ROOT/scripts/roster.sh" caps encode | tr '\n' ' ')
chk_names=$("$ROOT/scripts/roster.sh" caps chunked | tr '\n' ' ')

in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
metaval() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -1; }

printf '%-15s %-9s %-7s %-14s %-6s %s\n' \
    DRIVER BUILDER CHUNKED ENCODE MINBUF GATES
printf '%s\n' "-------------------------------------------------------------------------------"

rows=$(mktemp)
trap 'rm -f "$rows"' EXIT
"$ROOT/scripts/roster.sh" list > "$rows"

while read -r name builder arg tags binary; do
    meta="$ROOT/drivers/$builder/meta"

    if [ ! -f "$meta" ]; then
        note "$name: drivers/$builder/meta is missing — nothing declares what this backend offers"
        continue
    fi

    chunked=$(metaval "$meta" chunked_decode)
    surfaces=$(metaval "$meta" encode_surfaces)
    minbuf=$(metaval "$meta" min_output_buffer)

    # Which gates this entry lands in, derived the same way the gates derive it.
    gates="differential,sweeps,materialize"
    in_list "$name" "$chk_names" && gates="$gates,chunked"
    in_list "$name" "$enc_names" && gates="$gates,encode"
    case ",$tags," in *,limits,*) gates="$gates,limits" ;; esac
    case ",$tags," in *,blocking,*) ;; *) gates="$gates (QUARANTINED)" ;; esac

    printf '%-15s %-9s %-7s %-14s %-6s %s\n' \
        "$name" "$builder" "${chunked:-—}" "${surfaces:-—}" "${minbuf:-—}" "$gates"

    # --- assertions: a declaration missing is the state that hides work ------------
    #
    # An ABSENT key is the dangerous one, not a `none`. `none` is somebody writing
    # down that the backend cannot do it (corelib-go has no resumable decoder);
    # absent is nobody having looked.
    case "$chunked" in
        push|pull|none) ;;
        "") note "$name: meta declares no chunked_decode — it must say push, pull or none, so an absence is a statement rather than an oversight" ;;
        *)  note "$name: chunked_decode=$chunked is not push, pull or none" ;;
    esac

    if [ -z "$surfaces" ]; then
        note "$name: meta declares no encode_surfaces — the encode gate cannot place it, and it will be absent without saying so"
    fi

    # §5.1: a port that streams MUST declare the smallest buffer it accepts, and the
    # declaration is capped at 20 so a port cannot demand more than a message occupies.
    case ",$surfaces," in
        *,stream,*)
            if [ -z "$minbuf" ]; then
                note "$name: declares the stream surface but no min_output_buffer — CORELIB_PLAN §5.1 requires the port to state its floor"
            elif [ "$minbuf" -lt 1 ] 2>/dev/null || [ "$minbuf" -gt 20 ] 2>/dev/null; then
                note "$name: min_output_buffer=$minbuf is outside §5.1's range (1..20)"
            fi
            ;;
    esac

    # A quarantine must name the finding that justifies it, so it can be lifted the day
    # that finding closes — the roster's own rule. Checked against the file's comments,
    # which is where the reason lives.
    case ",$tags," in
        *,blocking,*) ;;
        *)
            if ! grep -q "$name" "$ROSTER" || ! grep -E "^#.*$name" "$ROSTER" | grep -qE 'F-[0-9]{4}|G-[0-9]{4}'; then
                note "$name: quarantined (no blocking tag) with no finding named in drivers/roster — a quarantine without a reason is a silent exclusion"
            fi
            ;;
    esac
done < "$rows"

printf '%s\n' "-------------------------------------------------------------------------------"
if [ "$fail" -eq 0 ]; then
    echo "==> [driver-audit] every roster entry declares what the gates need to place it." >&2
    exit 0
fi
echo "==> [driver-audit] $fail declaration gap(s) — see the !! lines above." >&2
exit 1
