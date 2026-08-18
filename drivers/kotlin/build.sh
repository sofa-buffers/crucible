#!/usr/bin/env sh
# Build a Crucible Kotlin Multiplatform replay driver: regenerate the probe classes
# from the schema via sofabgen (--lang kotlin), build the vendored corelib for the
# requested KMP target, compile them + driver.kt + that target's IO shim, and emit
# the runnable driver.
#
#   build.sh jvm       corelib-kotlin-mp's `jvm` target      -> a java wrapper script
#   build.sh native    corelib-kotlin-mp's `linuxX64` target -> a native ELF
#
# Emits the driver path on stdout (last line); logs go to stderr.
#
# ONE SOURCE, TWO TARGETS — the drivers/rust/ pattern. corelib-kotlin-mp is one
# commonMain codec compiled for several platforms, differing in the `expect`/`actual`
# for little-endian word access (VarHandles on the JVM, indexed shifts natively). The
# wire behaviour is meant to be identical on both, so any divergence between them is a
# bug by construction — which is why both are registered in drivers/roster rather than
# one standing in for the other.
#
# THE CORELIB IS BUILT BY ITS OWN GRADLE BUILD, never by hand-compiling its sources:
# build.gradle.kts pins the JVM target (17), `-jvm-default=no-compatibility` and the
# native target list, and a driver built against a differently-compiled corelib is not
# testing the artifact the project ships. The DRIVER, by contrast, is compiled directly
# with kotlinc — the reason drivers/java/build.sh calls javac rather than adding a
# Maven module: a driver is a handful of files against a built library and should not
# drag a build system of its own along.
#
# Honors SCHEMA (union/dyn schemas) and LIMITS (limit mode caps) from the environment,
# exactly like the peer build.sh scripts.
set -eu

VARIANT="${1:-jvm}"
case "$VARIANT" in
    jvm|native) ;;
    *) echo "usage: build.sh {jvm|native}" >&2; exit 2 ;;
esac

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-kotlin-mp"
OUT="$HERE/build/$VARIANT"
GEN="$OUT/gen"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -d "$CORELIB" ] || { echo "missing $CORELIB — run scripts/bootstrap.sh" >&2; exit 1; }
command -v kotlinc >/dev/null 2>&1 || { echo "missing kotlinc (see .devcontainer)" >&2; exit 1; }

# ---------------------------------------------------------------- the corelib ----
# Built via the project's own Gradle wrapper, and rebuilt whenever the vendored
# sources moved: skip-if-present once masked an F-0016 fix in the Java driver (a
# `git reset --hard` to the fixed corelib left the old jar in place, so the driver
# linked the PRE-fix corelib and the finding read as still-broken). A corelib bump
# sets src mtimes to checkout time, so `-newer` catches it.
gradle_build() {  # $1 = gradle task, $2 = the artifact it produces
    if [ ! -e "$2" ] || [ -n "$(find "$CORELIB/src" "$CORELIB/build.gradle.kts" -type f -newer "$2" 2>/dev/null | head -1)" ]; then
        echo "==> [kotlin/$VARIANT] building corelib-kotlin-mp ($1)" >&2
        ( cd "$CORELIB" && ./gradlew --console=plain -q "$1" >&2 )
    fi
}

case "$VARIANT" in
    jvm)
        JAR="$CORELIB/build/libs/corelib-kotlin-mp-jvm-0.1.0.jar"
        gradle_build jvmJar "$JAR"
        [ -f "$JAR" ] || { echo "corelib jvm jar not at $JAR" >&2; exit 1; }
        ;;
    native)
        KLIB="$CORELIB/build/classes/kotlin/linuxX64/main/klib/corelib-kotlin-mp"
        gradle_build linuxX64MainKlibrary "$KLIB"
        [ -e "$KLIB" ] || { echo "corelib linuxX64 klib not at $KLIB" >&2; exit 1; }
        # kotlinc-native ships inside the Kotlin/Native distribution that Gradle
        # provisions into KONAN_DATA_DIR (the standalone kotlinc has no native
        # front-end), so it is located after the corelib build has pulled it.
        KONAN="${KONAN_DATA_DIR:-$HOME/.konan}"
        KNC=$(find "$KONAN" -maxdepth 3 -type f -name kotlinc-native 2>/dev/null | head -1)
        [ -n "$KNC" ] || { echo "no kotlinc-native under $KONAN (see .devcontainer)" >&2; exit 1; }
        ;;
esac

# ------------------------------------------------------------- generated code ----
echo "==> [kotlin/$VARIANT] generating probe classes from schema" >&2
rm -rf "$OUT"; mkdir -p "$GEN"
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$OUT/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang kotlin --in "$SCHEMA" --out "$GEN" >&2

# The schema-agnostic materialized-value walker, generated from the descriptor
# (oracle/materialized-schema.json) on every build so a schema change reshapes it with
# zero hand-editing. Kotlin has no property reflection outside the JVM, so this is
# generated rather than reflected — and one generated walker then serves every target.
echo "==> [kotlin/$VARIANT] generating materialized-value walker from descriptor" >&2
python3 "$HERE/materialize_gen.py" "$OUT/materialize_gen.kt" "$SCHEMA" >&2

# Exactly one IO shim: the shared driver.kt is target-agnostic and reaches the
# environment, stdin and stdout only through the `Io` this file supplies.
case "$VARIANT" in
    jvm)    IO="$HERE/io_jvm.kt" ;;
    native) IO="$HERE/io_native.kt" ;;
esac

# shellcheck disable=SC2046
set -- $(find "$GEN" -name '*.kt' | sort) "$HERE/driver.kt" "$IO" "$OUT/materialize_gen.kt"

# ------------------------------------------------------------------ the driver ----
case "$VARIANT" in
    jvm)
        echo "==> [kotlin/jvm] kotlinc (driver + generated, against the corelib jar)" >&2
        CLASSES="$OUT/classes"
        mkdir -p "$CLASSES"
        kotlinc -nowarn -classpath "$JAR" -d "$CLASSES" "$@" >&2
        # kotlin-stdlib is on kotlinc's compile classpath implicitly but not on the
        # runtime one; ship the compiler's own copy so the wrapper needs no Gradle.
        STDLIB=$(dirname "$(command -v kotlinc)")/../lib/kotlin-stdlib.jar
        [ -f "$STDLIB" ] || { echo "no kotlin-stdlib.jar next to kotlinc" >&2; exit 1; }
        WRAP="$OUT/driver"
        cat > "$WRAP" <<EOF
#!/bin/sh
exec java -cp "$CLASSES:$JAR:$STDLIB" crucible.Driver
EOF
        chmod +x "$WRAP"
        echo "$WRAP"
        ;;
    native)
        echo "==> [kotlin/native] kotlinc-native (driver + generated, against the corelib klib)" >&2
        # -opt because this binary decodes a whole corpus per run and the default is
        # unoptimized; the safety checks Kotlin/Native keeps either way are what make
        # it a sanitizer-ish net, and -opt does not remove them.
        # -e: Kotlin/Native looks for `main` in the ROOT package unless told otherwise, and
        # the driver's lives in `crucible` like every other symbol here.
        "$KNC" -p program -opt -nowarn -e crucible.main -l "$KLIB" -o "$OUT/driver" "$@" >&2
        # kotlinc-native appends .kexe to the output name on Linux. (An `if`, not a
        # `[ ] && mv`: under `set -e` a false test would make the AND-OR list itself
        # the failing command and abort the build.)
        if [ -f "$OUT/driver.kexe" ]; then mv "$OUT/driver.kexe" "$OUT/driver"; fi
        [ -f "$OUT/driver" ] || { echo "kotlinc-native produced no binary" >&2; exit 1; }
        chmod +x "$OUT/driver"
        echo "$OUT/driver"
        ;;
esac
