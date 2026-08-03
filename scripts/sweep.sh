#!/usr/bin/env sh
# Structural sweep gate (PLAN §6 — the sweep family).
#
# A sweep enumerates one normative rule across EVERY field position in the schema
# and checks two oracles (engine/structured/sweep_run.py):
#   * agreement   — all 13 drivers emit the same canonical line;
#   * conformance — accept-vs-reject matches what the spec requires (a family-wide
#                   wrong answer is agreement-green but conformance-red).
#
# sweep_tolerance (§7.2 class 5b) additionally uses `expect="same:<twin>"`: the input
# must be accepted AND re-encode to the same bytes as its canonical twin. That is the
# only assertion in the suite that catches a family which is *uniformly* too strict or
# which accepts a non-canonical form and echoes it straight back — both are unanimous,
# and unanimity is what every other check calls green.
#
# Blocking axes (must stay green): sweep_repeated_id (§7.4), sweep_overbound (§7.1),
# sweep_reserved_subtype (§4.6), sweep_truncation (§7), sweep_malform_truncate (§5.2 —
# F-0024 resolved in sofabgen 0.19.4, promoted from report-only), wiretype_sweep (§7.3 —
# F-0022/F-0023 resolved in 0.19.4 and F-0025 (fp scalar←array, generator#193) resolved in
# the post-0.19.4 CI build; promoted from report-only 2026-07-22, verified all-12-agree).
# Since 2026-08-02 **every probe axis is blocking** and no carve-out remains: sweep_framing
# (§5.2/§6.2), sweep_unknown_seq (§5.2/§4.9) and sweep_repeated_elem (§7.4×§5.1) were
# promoted the same day their findings were fixed (corelib-c-cpp#126, generator#268,
# generator#273). Only the union pass is still report-only
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

echo "==> [sweep] blocking axes: repeated-id (§7.4) + over-bound (§7.1) + reserved-subtype (§4.6) + truncation (§7) + malform×truncate (§5.2) + wiretype (§7.3) + varint (§2 canonicality) + empty-frame (§2 omission) + framing/ceilings (§5.2/§6.2) + unknown-sequence (§5.2/§4.9) + repeated-element-id (§7.4×§5.1) + tolerance (§7.2 class 5b)" >&2
python3 "$SWEEP" sweep_repeated_id sweep_overbound sweep_reserved_subtype sweep_truncation sweep_malform_truncate wiretype_sweep sweep_varint sweep_empty_frame sweep_framing sweep_unknown_seq sweep_repeated_elem sweep_tolerance

# --- all three former report-only probe axes are BLOCKING since 2026-08-02 ----
# sweep_framing (WP-04), sweep_unknown_seq and sweep_repeated_elem were report-only
# under ground rule 4 — a new axis blocks only once green, or once every divergence it
# surfaces is catalogued. All three went green the same day their findings were fixed:
#   sweep_framing      — MAX_DEPTH boundary vectors; corelib-c-cpp#126 (F-0050)
#   sweep_unknown_seq  — unknown id carrying a sequence; generator#268 (F-0044)
#   sweep_repeated_elem— repeated element id in a wrapper; generator#273 (F-0048)
# They are folded into the blocking call above. Note sweep_framing deliberately carries
# no FIXLEN_MAX/ARRAY_MAX boundary vectors: §6.2 makes those ceilings profile-dependent,
# so no single boundary value exists that the whole family must agree on — the reasoning
# is in sweep_framing.py so it is not re-attempted.

# --- union pass (WP-01, REPORT-ONLY) ----------------------------------------
# The union feature lives in a separate schema (the full-scale probe has no union),
# so it is invisible to the axes above. This pass rebuilds the 13 drivers against
# schema/probe-union.sofab.yaml, runs the union axes (wiretype §7.3, repeated-id §7.4,
# over-bound §7.1, reserved-subtype §4.6, truncation §7, empty-frame §2, tolerance
# §7.2/5b), then rebuilds back to probe
# so the binaries are never left in the probe-union state (ground rule 3 — the same
# footgun run-limits.sh has). REPORT-ONLY per project precedent (a new axis is not
# blocking until it is green or every divergence it surfaces is a catalogued finding);
# promotion to blocking + replay.yml is a follow-up. A non-zero union result therefore
# does NOT fail this gate — the divergences it prints are candidate findings.
echo "==> [sweep] union pass (report-only): rebuilding 13 drivers against probe-union" >&2
SCHEMA="$ROOT/schema/probe-union.sofab.yaml" CORPUS="$ROOT/corpus/union" "$ROOT/scripts/run.sh" >/dev/null
echo "==> [sweep] union axes (report-only): wiretype §7.3 + repeated-id §7.4 + over-bound §7.1 + reserved-subtype §4.6 + truncation §7" >&2
python3 "$SWEEP" --union \
  || echo "==> [sweep] union pass is REPORT-ONLY — divergences/nonconformance above are candidate findings, not a gate failure" >&2
echo "==> [sweep] rebuilding 13 drivers back to probe (restore the default binary state)" >&2
CORPUS="$ROOT/corpus/seeds" "$ROOT/scripts/run.sh" >/dev/null
echo "==> [sweep] done (probe axes blocking; union pass report-only)" >&2
