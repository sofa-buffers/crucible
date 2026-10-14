// Jazzer coverage target for the probe decoder (devcontainer; needs the Jazzer
// jar on the classpath, so build.sh does NOT compile this — it builds only the
// replay Driver). Exercises the same decode core for coverage-guided fuzzing:
//
//   jazzer --cp=build/classes:sofab.jar:jazzer_standalone.jar \
//          --target_class=crucible.FuzzProbe
//
// A rejection is the SofabException the generated decode() declares, and is
// expected. Anything else thrown — an unchecked exception out of the generated
// visitor or the corelib — is a finding, so it is not caught. Cross-implementation
// divergence is caught by the differential comparator, not here.
package crucible;

import message.Probe;
import org.sofabuffers.sofab.SofabException;

public final class FuzzProbe {
    public static void fuzzerTestOneInput(byte[] data) {
        try {
            Probe.decode(data);
        } catch (SofabException expected) {
            // malformed (or incomplete) input; not a finding
        }
    }
}
