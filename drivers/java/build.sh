#!/usr/bin/env sh
# Build the Crucible Java replay driver: regenerate the probe classes from the
# schema via sofabgen, compile them + Driver.java against corelib-java's jar, and
# emit an executable wrapper that runs the driver on the JVM.
#
# Emits the wrapper path on stdout; logs go to stderr.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-java"
GEN="$HERE/build/gen"
CLASSES="$HERE/build/classes"
JAR="$CORELIB/target/sofab.jar"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }

# Build the corelib jar if it is missing OR stale — any source (or the pom) newer than
# the jar means the vendored corelib-java moved and the jar must be rebuilt. Skip-if-present
# once masked an F-0016 fix: a `git reset --hard` to the fixed corelib left the Jul-15 jar
# in place, so the driver linked the *pre-fix* corelib and the finding read as still-broken.
# (A corelib bump sets src mtimes to checkout time, so `-newer` catches it.)
if [ ! -f "$JAR" ] || [ -n "$(find "$CORELIB/src" "$CORELIB/pom.xml" -type f -newer "$JAR" 2>/dev/null | head -1)" ]; then
    echo "==> [java] building corelib-java jar (mvn package)" >&2
    ( cd "$CORELIB" && mvn -q -DskipTests clean package >&2 )
fi

echo "==> [java] generating probe classes from schema" >&2
rm -rf "$GEN" "$CLASSES"; mkdir -p "$GEN" "$CLASSES"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$GEN/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang java --in "$SCHEMA" --out "$GEN" >&2

echo "==> [java] javac (driver + generated, against sofab.jar)" >&2
# shellcheck disable=SC2046
javac -cp "$JAR" -d "$CLASSES" \
    $(find "$GEN" -name '*.java') "$HERE/Driver.java" "$HERE/ProbeDump.java" >&2

WRAP="$HERE/build/driver"
cat > "$WRAP" <<EOF
#!/bin/sh
exec java -cp "$CLASSES:$JAR" crucible.Driver
EOF
chmod +x "$WRAP"

echo "$WRAP"
