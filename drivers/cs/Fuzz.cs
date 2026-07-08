// SharpFuzz coverage target for the probe decoder (devcontainer; needs the
// SharpFuzz package + `sharpfuzz` instrumentation, so build.sh does NOT compile
// this — it builds only the replay Driver). Exercises the same decode core for
// coverage-guided fuzzing:
//
//   sharpfuzz <instrumented SofaBuffers.dll>
//   dotnet run   # with Fuzzer.LibFuzzer.Run wired as the entry point
//
// Must never crash on any input; a decode failure is the expected SofabException
// and is swallowed. Cross-implementation divergence is caught by the differential
// comparator, not here.
using System;
using SharpFuzz;
using sofab;
using Message;

namespace Crucible;

internal static class Fuzz
{
    // Not named Main / not compiled by build.sh, so it never collides with the
    // replay Driver's entry point.
    public static void Run()
    {
        Fuzzer.LibFuzzer.Run(span =>
        {
            try { Probe.Decode(span.ToArray()); }
            catch (SofabException) { /* malformed input -> expected; not a finding */ }
        });
    }
}
