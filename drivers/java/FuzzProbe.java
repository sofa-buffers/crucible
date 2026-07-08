// Jazzer coverage target for the probe decoder (devcontainer; needs the Jazzer
// jar on the classpath, so build.sh does NOT compile this — it builds only the
// replay Driver). Exercises the same decode core for coverage-guided fuzzing:
//
//   jazzer --cp=build/classes:sofab.jar:jazzer_standalone.jar \
//          --target_class=crucible.FuzzProbe
//
// Must never crash the JVM on any input; a decode failure is the expected
// RuntimeException and is swallowed. Cross-implementation divergence is caught by
// the differential comparator, not here.
package crucible;

import message.Probe;

public final class FuzzProbe {
    public static void fuzzerTestOneInput(byte[] data) {
        try {
            Probe.decode(data);
        } catch (RuntimeException expected) {
            // malformed input -> RuntimeException; not a finding
        }
    }
}
