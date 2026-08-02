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
# Those axes are blocking and no carve-out remains among them; two NEWER probe axes
# (sweep_unknown_seq, sweep_repeated_elem — added 2026-08-02, see below) are report-only
# until their findings close
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

echo "==> [sweep] blocking axes: repeated-id (§7.4) + over-bound (§7.1) + reserved-subtype (§4.6) + truncation (§7) + malform×truncate (§5.2) + wiretype (§7.3) + varint (§2 canonicality, agreement-only) + empty-frame (§2 omission, POC)" >&2
python3 "$SWEEP" sweep_repeated_id sweep_overbound sweep_reserved_subtype sweep_truncation sweep_malform_truncate wiretype_sweep sweep_varint sweep_empty_frame

# --- framing & format-ceiling axis (WP-04, REPORT-ONLY) ---------------------
# Stray/unbalanced sequence-end (§5.2) + format ceilings ID_MAX/FIXLEN_MAX/ARRAY_MAX/
# MAX_DEPTH (§6.2). Report-only + non-blocking until green or every divergence is a
# catalogued finding (ground rule 4). The over-ceiling length/count vectors declare a
# huge size with no payload — a driver that allocates per the declared length is a DoS
# finding (F-0013 precedent), caught by the per-driver timeout. A non-zero result here
# is NOT a gate failure.
#
# 2026-08-02: gained MAX_DEPTH **boundary** vectors (255 vs 256, closed and truncated,
# built both through a declared sequence and through a §7.3-skipped one). It had only
# 300-vs-8, which is why it owned the MAX_DEPTH rule and still missed the off-by-one now
# filed as corelib-c-cpp#126 (F-0050) — the two vectors it now fails on. Promote to
# blocking when #126 closes. FIXLEN_MAX/ARRAY_MAX deliberately get no boundary vectors:
# §6.2 makes those ceilings profile-dependent, so no single boundary value exists that
# the whole family must agree on — see the note in sweep_framing.py.
echo "==> [sweep] framing & ceilings axis (report-only): stray end (§5.2) + ID_MAX/FIXLEN_MAX/ARRAY_MAX/MAX_DEPTH (§6.2)" >&2
python3 "$SWEEP" sweep_framing \
  || echo "==> [sweep] framing axis is REPORT-ONLY — divergences above are candidate findings, not a gate failure" >&2

# --- the two axes added 2026-08-02, both REPORT-ONLY ------------------------
# Each closes a cell that six axes walked past and the fuzzer had to find, and each is
# red today on exactly one open finding — so both are report-only per ground rule 4 (a
# new axis blocks only once green, or once every divergence it surfaces is catalogued).
#
#   sweep_unknown_seq   (§5.2/§4.9) — an UNKNOWN id carrying a SEQUENCE with children.
#       sweep_framing places unknown ids only at scalar/fixlen/array wire types, so the
#       "skip the whole subtree" half of the rule was unswept. 14/25 red: **F-0044**
#       (generator#268), camp {rust-std, rust-nostd, java, csharp, zig} exactly.
#       Promote when #268 closes.
#   sweep_repeated_elem (§7.4 x §5.1) — a repeated ELEMENT id inside one wrapper opening.
#       sweep_repeated_id repeats field ids and re-opens wrappers, but never an element
#       id *within* a wrapper. 8/17 red: **F-0048** (generator#273), rust-nostd alone.
#       Promote when #273 closes.
echo "==> [sweep] axes added 2026-08-02 (report-only): unknown-sequence §5.2/§4.9 (F-0044) + repeated-element-id §7.4/§5.1 (F-0048)" >&2
python3 "$SWEEP" sweep_unknown_seq sweep_repeated_elem \
  || echo "==> [sweep] both axes are REPORT-ONLY — the divergences above are F-0044 (generator#268) and F-0048 (generator#273), not a gate failure" >&2

# --- union pass (WP-01, REPORT-ONLY) ----------------------------------------
# The union feature lives in a separate schema (the full-scale probe has no union),
# so it is invisible to the axes above. This pass rebuilds the 13 drivers against
# schema/probe-union.sofab.yaml, runs the union axes (wiretype §7.3, repeated-id §7.4,
# over-bound §7.1, reserved-subtype §4.6, truncation §7), then rebuilds back to probe
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
