// Jazzer.js coverage target for the probe decoder (devcontainer; needs
// @jazzer.js/core, so build.sh does NOT bundle this — it builds only the replay
// driver). Exercises the same decode core for coverage-guided fuzzing:
//
//   npx jazzer fuzz.ts --sync
//
// Must never crash on any input; a decode failure is the expected SofabError and
// is swallowed. Cross-implementation divergence is caught by the differential
// comparator, not here.
import { Probe } from "./message";

export function fuzz(data: Buffer): void {
  try {
    Probe.decode(new Uint8Array(data));
  } catch (expected) {
    // malformed input -> SofabError; not a finding
  }
}
