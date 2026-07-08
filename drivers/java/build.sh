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

# Build the corelib jar once if the vendored checkout hasn't produced it.
if [ ! -f "$JAR" ]; then
    echo "==> [java] building corelib-java jar (mvn package)" >&2
    ( cd "$CORELIB" && mvn -q -DskipTests package >&2 )
fi

echo "==> [java] generating probe classes from schema" >&2
rm -rf "$GEN" "$CLASSES"; mkdir -p "$GEN" "$CLASSES"
"$SOFABGEN" --lang java --in "$ROOT/schema/probe.sofab.yaml" --out "$GEN" >&2

echo "==> [java] javac (driver + generated, against sofab.jar)" >&2
# shellcheck disable=SC2046
javac -cp "$JAR" -d "$CLASSES" \
    $(find "$GEN" -name '*.java') "$HERE/Driver.java" >&2

WRAP="$HERE/build/driver"
cat > "$WRAP" <<EOF
#!/bin/sh
exec java -cp "$CLASSES:$JAR" crucible.Driver
EOF
chmod +x "$WRAP"

echo "$WRAP"
