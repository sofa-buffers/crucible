// Jazzer coverage target for the probe decoder on the JVM leg (devcontainer; needs
// the Jazzer jar on the classpath, so build.sh does NOT compile this — it builds
// only the replay driver). Exercises the same decode core for coverage-guided
// fuzzing:
//
//   kotlinc -cp build/jvm/classes:<corelib jar> FuzzProbe.kt -d fuzz-classes
//   jazzer --cp=fuzz-classes:build/jvm/classes:<corelib jar>:jazzer_standalone.jar \
//          --target_class=crucible.FuzzProbe
//
// JVM ONLY. The `native` leg has no coverage front-end: Kotlin/Native exposes no
// libFuzzer entry point, which is the position drivers/zig and drivers/dart are in
// (PLAN §14). The two legs share a decoder, so JVM coverage still steers the corpus
// that both are replayed against.
//
// Must never crash the JVM on any input; a decode failure is the expected
// SofabException/IllegalStateException and is swallowed. Cross-implementation
// divergence is caught by the differential comparator, not here.
package crucible

import message.Probe

public object FuzzProbe {
    @JvmStatic
    public fun fuzzerTestOneInput(data: ByteArray) {
        try {
            Probe.decode(data)
        } catch (expected: RuntimeException) {
            // malformed input -> SofabException, truncated -> IllegalStateException;
            // both are RuntimeException and neither is a finding.
        }
    }
}
