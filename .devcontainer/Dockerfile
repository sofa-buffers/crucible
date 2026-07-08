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
#   default-jdk + maven        Java target; Jazzer is fetched per build
#   python3 + venv + atheris   Python target + Atheris (libFuzzer for CPython)
#   (dotnet 9) + SharpFuzz     C# target (corelib-cs)
#   (nodejs) + @jazzer.js      TypeScript target (corelib-ts)
#   (zig tarball)              Zig target (corelib-zig) — built-in fuzzing is young,
#                                the driver may fall back to libFuzzer via C interop
#   binutils / llvm-symbolizer readable sanitizer + coverage reports
#   gh, jq, git                repo + findings plumbing
#
# NOT installed (vs Arena): protobuf / nanopb / EmbeddedProto (no baselines here),
# and the bare-metal cross toolchains (fuzzing runs hosted, not on Cortex-M/RISC-V).
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip git jq time pkg-config \
    build-essential cmake make gcc g++ \
    clang lld llvm llvm-dev libclang-rt-dev \
    python3 python3-venv python3-pip python3-dev \
    default-jdk maven \
    libicu-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Rust (rustup, stable) + cargo-fuzz --------------------------------------
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:/usr/local/dotnet:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain stable \
    && rustup component add rust-src \
    && cargo install cargo-fuzz \
    && rustc --version && cargo fuzz --version

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
