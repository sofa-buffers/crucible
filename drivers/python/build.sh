#!/usr/bin/env sh
# Build a Crucible Python replay driver for one execution mode.
#
#   build.sh cython  -> compiled Cython accelerator (sofab._speedups)
#   build.sh pure    -> pure-Python fallback engine
#
# Both modes are the SAME corelib-py, switched at runtime by SOFAB_PUREPYTHON.
# The venv + generated code are built once and shared; each mode gets a tiny
# executable wrapper. Emits the wrapper path on stdout.
set -eu

MODE="${1:-cython}"
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-py"
VENV="$HERE/build/venv"
GEN="$HERE/build/gen"

case "$MODE" in
    cython) PURE=0 ;;
    pure)   PURE=1 ;;
    *) echo "unknown mode '$MODE' (want: cython | pure)" >&2; exit 2 ;;
esac

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

# Build the venv once: install corelib-py (non-editable, so the vendored source
# stays clean) with Cython present so the _speedups extension is compiled for
# THIS interpreter — otherwise "cython" mode silently falls back to pure. Atheris
# (the coverage front-end) needs clang and is optional for the replay loop.
#
# The *install* is refreshed whenever the vendored sources move (same rule as the
# Java driver's jar): a non-editable install is a copy, so a venv kept across a
# corelib bump tests a corelib nobody vendored any more. That is not hypothetical —
# switching the family branch left the venv on the previous corelib-py, and both
# Python drivers then rejected every seed against a generator that had already moved
# on (`Encoder has no attribute write_sequence_begin_lazy`), which reads as a
# 13-driver divergence rather than as the stale build it was.
STAMP="$VENV/.corelib-py.installed"
install_corelib_py() {
    "$VENV/bin/pip" install -q --force-reinstall --no-deps "$CORELIB" >&2
    : > "$STAMP"
}
if [ ! -x "$VENV/bin/python" ]; then
    echo "==> [python] creating venv + building corelib-py (Cython ext)" >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip >&2
    "$VENV/bin/pip" install -q cython >&2
    install_corelib_py
    "$VENV/bin/pip" install -q atheris >&2 2>/dev/null \
        || echo "==> [python] atheris not installed (needs clang; only the coverage front-end uses it)" >&2
elif [ ! -f "$STAMP" ] || [ -n "$(find "$CORELIB/src" "$CORELIB/pyproject.toml" "$CORELIB/setup.py" -newer "$STAMP" 2>/dev/null | head -1)" ]; then
    echo "==> [python] corelib-py changed since the venv was built — reinstalling (Cython ext)" >&2
    install_corelib_py
fi

echo "==> [python] generating probe types from schema" >&2
rm -rf "$GEN"; mkdir -p "$GEN"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$GEN/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang python --in "$SCHEMA" --out "$GEN" >&2

# Sanity: confirm the requested mode actually resolves as expected.
GOT=$(SOFAB_PUREPYTHON=$PURE "$VENV/bin/python" -c "import sofab; print(sofab.IMPL)")
WANT=$( [ "$PURE" = 1 ] && echo python || echo native )
[ "$GOT" = "$WANT" ] || echo "==> [python:$MODE] WARNING: sofab.IMPL=$GOT (wanted $WANT); native ext may be missing" >&2

WRAP="$HERE/build/py-$MODE"
cat > "$WRAP" <<EOF
#!/bin/sh
exec env SOFAB_PUREPYTHON=$PURE PYTHONPATH="$GEN" "$VENV/bin/python" "$HERE/driver.py"
EOF
chmod +x "$WRAP"

echo "$WRAP"
