#!/usr/bin/env sh
# Encode-invariance gate (crucible#132) — the encode-side twin of run-chunked.sh.
#
# The family is byte-canonical: a value has exactly one encoding. The generated API
# offers up to three ways to produce it — the allocating `encode()`, the caller-buffer
# `encodeTo()`, and the streaming `serialize(os)` — and the round-trip oracle exercises
# whichever one the driver happens to call. The other two are untested everywhere, and
# so is what happens when the OStream's buffer boundary lands mid-message.
#
# For one implementation and one decoded value, all three surfaces must emit **identical
# bytes**, and `SOFAB_FLUSH=n` must not change them either. Like the chunk gate this is
# **not differential** — it compares an implementation against itself, so it needs no
# second implementation, drivers opt in one at a time, and it is the only kind of gate
# that can catch a defect the whole family shares.
#
#   ./scripts/run-encode.sh                  # corpus/structured (value-rich, all accept)
#   CORPUS=path ./scripts/run-encode.sh      # another corpus
#
# Defaults to corpus/structured rather than corpus/seeds because only an ACCEPTED input
# re-encodes: on `I` and `R` there is no value and every surface trivially agrees. The
# structured corpus is the value space this gate is about.
#
# Driver contract: a driver opts in by honouring `SOFAB_ENCODE=new|to|stream` and
# `SOFAB_FLUSH=n`, and by exiting non-zero when asked for a surface its backend does not
# have (drivers/common/CONTRACT.md). Drivers that do not honour it are **skipped
# loudly**, never counted as passing: a driver that ignores the variables produces
# byte-identical output, which is indistinguishable from correctness.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORPUS="${CORPUS:-$ROOT/corpus/structured}"

# Drivers known to implement SOFAB_ENCODE. Add a name here only once it demonstrably
# re-encodes through each surface its meta declares — a driver that ignores the
# variables emits byte-identical output, so this list is the only thing standing
# between the gate and a vacuous pass. The rest are tracked in docs/TODO.md.
SUPPORTED="${SOFAB_ENCODE_DRIVERS:-c rust-std rust-nostd cpp cpp-fixed cpp-c-cpp typescript java csharp dart zig}"

if [ -z "$SUPPORTED" ]; then
    echo "==> [encode] no driver implements SOFAB_ENCODE yet — nothing to check." >&2
    echo "    The oracle and the corpus are ready; the per-driver re-encode is not." >&2
    echo "    Tracked in docs/TODO.md. Skipping (this gate cannot pass vacuously)." >&2
    exit 0
fi

echo "==> [encode] building drivers" >&2
"$ROOT/scripts/run.sh" >/dev/null

echo "==> [encode] encode invariance over $(ls "$CORPUS" | grep -vc -e gitkeep -e '\.md$') input(s)" >&2
python3 "$ROOT/oracle/encode_invariance.py" --corpus "$CORPUS" --drivers "$SUPPORTED" "$@"
