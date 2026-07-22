#!/usr/bin/env sh
# Structural sweep gate (PLAN §6 — the sweep family).
#
# A sweep enumerates one normative rule across EVERY field position in the schema
# and checks two oracles (engine/structured/sweep_run.py):
#   * agreement   — all 13 drivers emit the same canonical line;
#   * conformance — accept-vs-reject matches what the spec requires (a family-wide
#                   wrong answer is agreement-green but conformance-red).
#
# Blocking axes (must stay green): sweep_repeated_id (§7.4), sweep_overbound (§7.1),
# sweep_reserved_subtype (§4.6), sweep_truncation (§7), sweep_malform_truncate (§5.2 —
# F-0024 resolved in sofabgen 0.19.4, promoted from report-only), wiretype_sweep (§7.3 —
# F-0022/F-0023 resolved in 0.19.4 and F-0025 (fp scalar←array, generator#193) resolved in
# the post-0.19.4 CI build; promoted from report-only 2026-07-22, verified all-12-agree).
# All six axes are now blocking; no report-only residual and no carve-out remains
# (F-0026, the blob_array §7.4 wrapper re-open, was resolved in corelib-c-cpp#106 / `2416a2b`
# on 2026-07-22 — the elem=="blob" skip in sweep_repeated_id.py was dropped and its isolates
# promoted into corpus/regression/).
#
# Rebuilds the 13 drivers against schema/probe.sofab.yaml first (a seed run.sh), so
# this is safe to run even after scripts/run-limits.sh, which leaves probe-dyn
# binaries in drivers/*/build — the recurring footgun the finding NOTES warn about.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SWEEP="$ROOT/engine/structured/sweep_run.py"

echo "==> [sweep] building the 13 drivers against probe (seed differential)" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null

echo "==> [sweep] blocking axes: repeated-id (§7.4) + over-bound (§7.1) + reserved-subtype (§4.6) + truncation (§7) + malform×truncate (§5.2) + wiretype (§7.3)" >&2
python3 "$SWEEP" sweep_repeated_id sweep_overbound sweep_reserved_subtype sweep_truncation sweep_malform_truncate wiretype_sweep
