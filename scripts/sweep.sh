#!/usr/bin/env sh
# Structural sweep gate (PLAN §6 — the sweep family).
#
# A sweep enumerates one normative rule across EVERY field position in the schema
# and checks two oracles (engine/structured/sweep_run.py):
#   * agreement   — all 12 drivers emit the same canonical line;
#   * conformance — accept-vs-reject matches what the spec requires (a family-wide
#                   wrong answer is agreement-green but conformance-red).
#
# Blocking axes (must stay green): sweep_repeated_id (§7.4), sweep_overbound (§7.1),
# sweep_reserved_subtype (§4.6), sweep_truncation (§7), sweep_malform_truncate (§5.2 —
# F-0024 resolved in sofabgen 0.19.4, promoted here from report-only).
# Report-only: wiretype_sweep (§7.3) — F-0022/F-0023 resolved in sofabgen 0.19.4; one residual
# remains, F-0025 (fp §7.3: a scalar fp field receiving an fp array — the fp analogue of F-0021
# that generator#183 covered for integers only; filed generator#193). Move it into the blocking
# set once it lands upstream.
#
# Rebuilds the 12 drivers against schema/probe.sofab.yaml first (a seed run.sh), so
# this is safe to run even after scripts/run-limits.sh, which leaves probe-dyn
# binaries in drivers/*/build — the recurring footgun the finding NOTES warn about.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SWEEP="$ROOT/engine/structured/sweep_run.py"

echo "==> [sweep] building the 12 drivers against probe (seed differential)" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [sweep] blocking axes: repeated-id (§7.4) + over-bound (§7.1) + reserved-subtype (§4.6) + truncation (§7) + malform×truncate (§5.2)" >&2
python3 "$SWEEP" sweep_repeated_id sweep_overbound sweep_reserved_subtype sweep_truncation sweep_malform_truncate

echo "==> [sweep] report-only: wiretype (§7.3) — residual F-0025 (fp scalar←array, generator#193); F-0022/F-0023 resolved 0.19.4" >&2
if python3 "$SWEEP" wiretype_sweep; then
    echo "==> [sweep] wiretype is GREEN — promote it into the blocking set above" >&2
else
    echo "==> [sweep] wiretype has its expected open divergence (F-0025, fp §7.3); not blocking" >&2
fi
