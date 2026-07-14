#!/usr/bin/env sh
# Build the Crucible C# replay driver: regenerate the probe class from the schema
# via sofabgen, assemble a console project that references corelib-cs, and
# `dotnet build` it. Emits an executable wrapper path on stdout.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SOFABGEN="$ROOT/tools/sofabgen"
CORELIB="$ROOT/vendor/corelib-cs"
COREPROJ="$CORELIB/src/SofaBuffers/SofaBuffers.csproj"
BUILD="$HERE/build"

[ -x "$SOFABGEN" ] || { echo "missing $SOFABGEN — run scripts/bootstrap.sh" >&2; exit 1; }
[ -f "$COREPROJ" ] || { echo "missing $COREPROJ — run scripts/bootstrap.sh" >&2; exit 1; }

# Limit mode (crucible#10 / generator#102): SCHEMA selects the schema (default the
# bounded probe); LIMITS, when set to an integer, bakes identical max_dyn_* caps
# into the generated code so an unbounded field over the cap decodes to
# LIMIT_EXCEEDED. Unset LIMITS = unlimited (byte-identical to before).
SCHEMA="${SCHEMA:-$ROOT/schema/probe.sofab.yaml}"

echo "==> [cs] generating probe class from ${SCHEMA##*/}${LIMITS:+ (limits=$LIMITS)}" >&2
rm -rf "$BUILD"; mkdir -p "$BUILD"
LIMCFG=""
if [ -n "${LIMITS:-}" ]; then
    LIMCFG="$BUILD/limits.cfg.yaml"
    printf 'generic:\n  max_dyn_array_count: %s\n  max_dyn_string_len: %s\n  max_dyn_blob_len: %s\n' \
        "$LIMITS" "$LIMITS" "$LIMITS" > "$LIMCFG"
fi
"$SOFABGEN" ${LIMCFG:+--config "$LIMCFG"} --lang csharp --in "$SCHEMA" --out "$BUILD" >&2
cp "$HERE/Driver.cs" "$BUILD/Driver.cs"   # only the replay driver (not Fuzz.cs)

# Build the corelib DLL standalone first (into $BUILD/corelib) and reference the
# built assembly — a ProjectReference into the symlinked vendor tree hit a ref-
# assembly ordering error (CS0006). This also keeps build output out of the
# vendored source's bin/.
echo "==> [cs] building corelib-cs assembly" >&2
dotnet build "$COREPROJ" -c Release -o "$BUILD/corelib" --nologo -v quiet >&2

# Console project referencing the built corelib DLL. InvariantGlobalization avoids
# an ICU dependency; the compile glob picks up Message.cs + Driver.cs in $BUILD.
cat > "$BUILD/Crucible.csproj" <<EOF
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net9.0</TargetFramework>
    <AssemblyName>Crucible</AssemblyName>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <InvariantGlobalization>true</InvariantGlobalization>
    <AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="SofaBuffers">
      <HintPath>$BUILD/corelib/SofaBuffers.dll</HintPath>
    </Reference>
  </ItemGroup>
</Project>
EOF

echo "==> [cs] dotnet build driver" >&2
dotnet build "$BUILD/Crucible.csproj" -c Release -o "$BUILD/out" --nologo -v quiet >&2

WRAP="$BUILD/driver"
cat > "$WRAP" <<EOF
#!/bin/sh
exec dotnet "$BUILD/out/Crucible.dll"
EOF
chmod +x "$WRAP"

echo "$WRAP"
