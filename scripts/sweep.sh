#!/usr/bin/env sh
# Structural sweep gate (PLAN §6 — the sweep family).
#
# A sweep enumerates one normative rule across EVERY field position in the schema
# and checks two oracles (engine/structured/sweep_run.py):
#   * agreement   — all 12 drivers emit the same canonical line;
#   * conformance — accept-vs-reject matches what the spec requires (a family-wide
#                   wrong answer is agreement-green but conformance-red).
#
# Blocking axes (must stay green): sweep_repeated_id (§7.4), sweep_overbound (§7.1).
# Report-only: wiretype_sweep (§7.3) — known-open F-0022/F-0023 (generator#188/#189);
# sweep_malform_truncate (§5.2) — known-open F-0024 (generator#190). Move each into the
# blocking set once its finding lands upstream.
#
# Rebuilds the 12 drivers against schema/probe.sofab.yaml first (a seed run.sh), so
# this is safe to run even after scripts/run-limits.sh, which leaves probe-dyn
# binaries in drivers/*/build — the recurring footgun the finding NOTES warn about.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SWEEP="$ROOT/engine/structured/sweep_run.py"

echo "==> [sweep] building the 12 drivers against probe (seed differential)" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [sweep] blocking axes: repeated-id (§7.4) + over-bound (§7.1) + reserved-subtype (§4.6) + truncation (§7)" >&2
python3 "$SWEEP" sweep_repeated_id sweep_overbound sweep_reserved_subtype sweep_truncation

echo "==> [sweep] report-only: wiretype (§7.3) — known-open F-0022/F-0023" >&2
if python3 "$SWEEP" wiretype_sweep; then
    echo "==> [sweep] wiretype is GREEN — promote it into the blocking set above" >&2
else
    echo "==> [sweep] wiretype has its expected open divergences (F-0022/F-0023); not blocking" >&2
fi

echo "==> [sweep] report-only: malform×truncate (§5.2) — known-open F-0024" >&2
if python3 "$SWEEP" sweep_malform_truncate; then
    echo "==> [sweep] malform×truncate is GREEN — promote it into the blocking set above" >&2
else
    echo "==> [sweep] malform×truncate has its expected open divergences (F-0024); not blocking" >&2
fi
