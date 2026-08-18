FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

# =============================================================================
# Crucible — differential fuzzing dev environment for the SofaBuffers wire format.
#
# Unlike the Arena (which builds every corelib OPTIMIZED and pairs it with a
# protobuf baseline), Crucible builds every corelib INSTRUMENTED — sanitizers
# plus coverage — and needs one fuzzing engine per language. So this image ships,
# per language, the toolchain AND its fuzzing framework:
#
#   clang/llvm + lld           libFuzzer (`-fsanitize=fuzzer`) + ASan/UBSan/MSan
#                                — the C/C++ PACEMAKER driver and the coverage motor
#   build-essential cmake gcc  gcc path for the persistent replay drivers (no clang
#                                needed just to run the differential loop)
#   go (official 1.25.x)       Go target + native `go test -fuzz`
#   (rustup) + cargo-fuzz      Rust target (corelib-rs / rs-no-std) — libFuzzer-based
#                              (+ rust-analyzer component for editor/LSP)
#   default-jdk + maven        Java target; Jazzer is fetched per build
#   temurin 21 + gradle        Kotlin Multiplatform target (corelib-kotlin-mp) — Gradle
#     + kotlinc                  builds the corelib, kotlinc the driver, Jazzer fuzzes
#     + kotlin-native            the JVM target. JDK 21 is the image's JAVA_HOME: Gradle
#                                8.x does not run on Ubuntu 26.04's default JDK 25. The
#                                driver has two legs (jvm, linuxX64), so the native
#                                compiler is here too — kotlinc has no native front-end.
#   python3 + venv + atheris   Python target + Atheris (libFuzzer for CPython)
#   (dotnet 9) + SharpFuzz     C# target (corelib-cs)
#   (nodejs) + @jazzer.js      TypeScript target (corelib-ts)
#   (zig tarball)              Zig target (corelib-zig) — built-in fuzzing is young,
#                                the driver may fall back to libFuzzer via C interop
#   (dart sdk tarball)         Dart target (corelib-dart) — no first-party libFuzzer;
#                                the driver AOT-compiles via dart:ffi and is driven by
#                                a C libFuzzer harness (like Zig). `dart pub` fetches
#                                the driver's package deps per build (like Jazzer).
#   binutils / llvm-symbolizer readable sanitizer + coverage reports
#   gh, jq, git                repo + findings plumbing
#
# NOT installed (vs Arena): protobuf / nanopb / EmbeddedProto (no baselines here),
# and the bare-metal cross toolchains (fuzzing runs hosted, not on Cortex-M/RISC-V).
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip zip gnupg git jq time pkg-config ripgrep \
    build-essential cmake make gcc g++ \
    clang lld llvm llvm-dev libclang-rt-dev \
    python3 python3-venv python3-pip python3-dev \
    default-jdk maven \
    libicu-dev zlib1g-dev libncurses6 \
    && rm -rf /var/lib/apt/lists/*

# --- Kotlin: JDK 21 (Temurin) + Gradle + kotlinc ------------------------------
# corelib-kotlin-mp is a Kotlin Multiplatform library driven by Gradle, which needs
# three things the Java target did not:
#
#   * a JDK Gradle can RUN on. Ubuntu 26.04's `default-jdk` is JDK 25, and Gradle
#     8.14 — the version that repo's wrapper pins — refuses to start on it. Temurin
#     21 is the LTS its own devcontainer and CI leg use, and it becomes the whole
#     image's JAVA_HOME rather than a second JDK on the side: corelib-java compiles
#     to release 17, so the Java driver does not notice 25 -> 21, and Jazzer — the
#     fuzzing framework for BOTH JVM drivers — tracks the LTS line. Temurin does not
#     win update-alternatives against the distro JDK, so the JAVA_HOME/PATH below,
#     not /usr/bin/java, is what decides which JDK a build actually gets.
#   * Gradle, pinned to the wrapper's version, so a fresh (or offline) checkout has a
#     build tool before any wrapper is there; project builds still go via ./gradlew.
#   * kotlinc, the standalone compiler, for the reason drivers/java calls javac
#     directly: Gradle builds the corelib, the driver is a handful of files compiled
#     against that jar and must not drag a Gradle project of its own along. Keep the
#     version in step with the `kotlin("multiplatform")` version in that repo's
#     build.gradle.kts — a driver built by a newer kotlinc than the corelib fails on
#     metadata version, which reads like a corelib bug and is not one.
#
# Kotlin/Native (linuxX64/linuxArm64) fetches its own LLVM + platform libraries on
# first build (~2 GB); KONAN_DATA_DIR parks that cache in the image instead of the
# mounted workspace, and zlib/ncurses above are what that toolchain links against.
# Kotlin/JS reuses the Node.js installed further down.
ENV JAVA_HOME=/opt/java-current \
    KONAN_DATA_DIR=/opt/konan \
    PATH=/opt/java-current/bin:/opt/kotlinc/bin:$PATH
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public \
        | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg \
    && chmod go+r /etc/apt/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
        > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update && apt-get install -y --no-install-recommends temurin-21-jdk \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sfn "/usr/lib/jvm/temurin-21-jdk-$(dpkg --print-architecture)" /opt/java-current \
    && GRADLE_VERSION=8.14.5 \
    && curl -fsSL -o /tmp/gradle.zip "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
    && unzip -q /tmp/gradle.zip -d /opt && rm /tmp/gradle.zip \
    && ln -sfn "/opt/gradle-${GRADLE_VERSION}/bin/gradle" /usr/local/bin/gradle \
    && KOTLIN_VERSION=2.4.10 \
    && curl -fsSL -o /tmp/kotlinc.zip "https://github.com/JetBrains/kotlin/releases/download/v${KOTLIN_VERSION}/kotlin-compiler-${KOTLIN_VERSION}.zip" \
    && unzip -q /tmp/kotlinc.zip -d /opt && rm /tmp/kotlinc.zip \
    && java -version && gradle --version && kotlinc -version

# --- Kotlin/Native: the compiler behind the `native` driver leg ----------------
# The standalone kotlinc above has NO native front-end — its bin/ carries
# kotlinc-jvm, kotlinc-js and kotlinc-wasm and nothing else — so the linuxX64 leg of
# drivers/kotlin needs the separate Kotlin/Native distribution. Gradle provisions it
# on demand, which is how it appears in a dev container; on a CI runner that would be
# a ~2 GB download in the middle of a gate, so the image carries it instead.
#
# TWO downloads, because they arrive by different routes: the prebuilt compiler
# (unpacked here), and its LLVM + sysroot dependencies, which Kotlin/Native fetches
# LAZILY on first compile rather than shipping in the distribution. Compiling a
# hello-world is what pulls those, and doing it here is the difference between a
# warm image and a first gate that downloads a toolchain.
#
# It lands under KONAN_DATA_DIR in the layout Gradle uses, so both find the same
# installation: drivers/kotlin/build.sh looks for kotlinc-native there, and the
# corelib's own Gradle build reuses this copy instead of fetching its own.
RUN KOTLIN_VERSION=2.4.10 \
    && case "$(uname -m)" in \
         x86_64)  KN_HOST=linux-x86_64 ;; \
         aarch64) KN_HOST=linux-aarch64 ;; \
         *) echo "no Kotlin/Native prebuilt for $(uname -m)" >&2; exit 1 ;; \
       esac \
    && KN_HOME="$KONAN_DATA_DIR/kotlin-native-prebuilt-${KN_HOST}-${KOTLIN_VERSION}" \
    && mkdir -p "$KONAN_DATA_DIR" \
    && curl -fsSL "https://github.com/JetBrains/kotlin/releases/download/v${KOTLIN_VERSION}/kotlin-native-prebuilt-${KN_HOST}-${KOTLIN_VERSION}.tar.gz" \
        | tar -xz -C "$KONAN_DATA_DIR" \
    && printf 'fun main() { println("warm") }\n' > /tmp/warm.kt \
    && "$KN_HOME/bin/kotlinc-native" -p program -o /tmp/warm /tmp/warm.kt \
    && /tmp/warm.kexe \
    && rm -f /tmp/warm.kt /tmp/warm.kexe

# --- Rust (rustup, stable) + cargo-fuzz --------------------------------------
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:/usr/local/dotnet:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain stable \
    && rustup component add rust-src rust-analyzer \
    && cargo install cargo-fuzz \
    && rustc --version && cargo fuzz --version && rust-analyzer --version

# --- Go (official toolchain) --------------------------------------------------
# Matches the version corelib-go's generated go.mod pins; native fuzzing is the
# Go coverage engine (`go test -fuzz`).
ENV PATH=/usr/local/go/bin:$PATH
RUN GO_VERSION=1.25.11 && ARCH="$(dpkg --print-architecture)" \
    && curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${ARCH}.tar.gz" -o /tmp/go.tgz \
    && tar -C /usr/local -xzf /tmp/go.tgz \
    && rm /tmp/go.tgz \
    && go version

# --- .NET SDK 9 + SharpFuzz ---------------------------------------------------
ENV DOTNET_ROOT=/usr/local/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 \
    PATH=/usr/local/dotnet:/root/.dotnet/tools:$PATH
RUN curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && chmod +x /tmp/dotnet-install.sh \
    && /tmp/dotnet-install.sh --channel 9.0 --install-dir /usr/local/dotnet \
    && rm /tmp/dotnet-install.sh \
    && dotnet tool install --global SharpFuzz.CommandLine \
    && dotnet --version

# --- Zig (official toolchain) -------------------------------------------------
ENV PATH=/usr/local/zig:$PATH
RUN ZIG_VERSION=0.16.0 && case "$(dpkg --print-architecture)" in \
        amd64) ZA=x86_64;; arm64) ZA=aarch64;; *) ZA=x86_64;; esac \
    && curl -fsSL "https://ziglang.org/download/${ZIG_VERSION}/zig-${ZA}-linux-${ZIG_VERSION}.tar.xz" -o /tmp/zig.txz \
    && mkdir -p /usr/local/zig \
    && tar -C /usr/local/zig --strip-components=1 -xJf /tmp/zig.txz \
    && rm /tmp/zig.txz \
    && zig version

# --- Dart SDK -----------------------------------------------------------------
# The Debian/APT dart channel is amd64-only, so (like Go/Zig/.NET) install the
# official SDK archive with an arch case for x64/arm64 parity. The SDK bundles the
# `dart` CLI, `dart pub` (package manager — the driver's pub deps are fetched per
# build), `dart compile` (AOT/exe + shared lib via dart:ffi), and `dart test`.
# Tracks the latest *stable* SDK — there is no corelib-dart yet to pin against; pin
# DART_VERSION to that corelib's SDK constraint once the Dart driver lands.
ENV DART_SDK=/usr/local/dart-sdk \
    PUB_CACHE=/usr/local/pub-cache \
    PATH=/usr/local/dart-sdk/bin:/usr/local/pub-cache/bin:$PATH
RUN DART_VERSION=latest && case "$(dpkg --print-architecture)" in \
        amd64) DA=x64;; arm64) DA=arm64;; *) DA=x64;; esac \
    && curl -fsSL "https://storage.googleapis.com/dart-archive/channels/stable/release/${DART_VERSION}/sdk/dartsdk-linux-${DA}-release.zip" -o /tmp/dartsdk.zip \
    && unzip -q /tmp/dartsdk.zip -d /usr/local \
    && rm /tmp/dartsdk.zip \
    && dart --version

# --- Node.js LTS + Jazzer.js + Claude Code ------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @jazzer.js/core @anthropic-ai/claude-code \
    && node --version

# --- Python fuzzing + Cython accelerator --------------------------------------
# Atheris is libFuzzer for CPython (builds a native extension, hence clang +
# python3-dev above). Cython builds corelib-py's `_speedups` accelerator for the
# py-cython driver — pre-seeded here so the driver's venv build is fast/offline.
# The drivers install these into a project venv at bootstrap; the image warms the
# wheels and their build deps.
RUN python3 -m pip install --break-system-packages --no-cache-dir cython atheris || true

# --- GitHub CLI ---------------------------------------------------------------
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# One-time project bootstrap (vendor corelibs + sofabgen) is done at run time by
# scripts/bootstrap.sh, then ./scripts/run.sh drives the differential loop.
CMD ["/bin/bash"]
