# G-0008 — generated one-shot decode discards the INCOMPLETE status (C#, Java)

**Status:** ✅ **fixed** in sofabgen 0.15.3 — PR
[generator#106](https://github.com/sofa-buffers/generator/pull/106) added the
status-surfacing `TryDecode`/`tryDecode`; part of the §7 epic
[generator#86](https://github.com/sofa-buffers/generator/issues/86).

**Where:** the generated `Probe.Decode`/`Probe.decode` for the *status-returning*
corelibs — C# (`Message.cs`) and Java (`Probe.java`).

**What:** under MESSAGE_SPEC §7 (finish-less three-valued decode), those corelibs
surface `INCOMPLETE` as a **returned status**, not a thrown error:
`IStream.Feed(...)` returns `DecodeStatus.Incomplete` (C#) and `IStream.status()`
returns `DecodeStatus.INCOMPLETE` (Java) — `feed` does *not* throw on a truncated
message. But the generated one-shot decode calls `feed` and **throws the status
away**:

```csharp
public static Probe Decode(byte[] data) {
    var m = new Probe(); var v = new ProbeVisitor(m);
    new IStream().Feed(data, 0, data.Length, v);   // DecodeStatus DISCARDED
    return m;
}
```

So a truncated message decodes without error and is indistinguishable from a
COMPLETE one — the generated decode **collapses INCOMPLETE into ACCEPT**, the
exact F-0001 bug the verdict axis exists to catch. Confirmed empirically: a lone
`0x80` re-encoded byte-identical to the empty message (`A 5607...`) before the
driver workaround.

**Why it matters:** this is the INCOMPLETE-dimension analogue of G-0001/G-0005
(which fixed the *reject* dimension — a fallible decode — but not the
*accept-vs-incomplete* dimension). The generated glue hides a real outcome the
corelib computes correctly.

**Former driver workaround (now removed):** `drivers/cs/Driver.cs` and
`drivers/java/Driver.java` used to take the **verdict** from a direct
`IStream.Feed`/`feed` + status read (a no-op visitor), and the **value** from the
generated decode — the same two-pass pattern the Rust driver uses for G-0001.

**Fixed** in sofabgen 0.15.3 (PR
[generator#106](https://github.com/sofa-buffers/generator/pull/106), closes
generator#105, under the §7 epic
[#86](https://github.com/sofa-buffers/generator/issues/86)): the generated
one-shot decode for the status-returning corelibs now surfaces the terminal
`DecodeStatus` via a status-returning entry point — C#
`DecodeStatus TryDecode(byte[] data, out T msg)` and Java
`DecodeStatus tryDecode(byte[] data, T out)` — so a caller can tell COMPLETE from
INCOMPLETE without re-running `feed`. The exception-throwing corelibs (Go, Rust
via feed, C++, C, Python, TS, Zig) already propagate INCOMPLETE through the
generated decode — only the status-returning pair needed the codegen change.

**Driver follow-up done** (crucible#10, sofabgen 0.16.0 bump): the two-pass
workaround is **removed** — `drivers/cs/Driver.cs` and `drivers/java/Driver.java`
now take both verdict and value from a single `TryDecode`/`tryDecode` call
(`Complete`→`A <hex>`, `Incomplete`→`I`, malformed throw→`R <class>`). Verified:
lone `0x80` still reports `I` (not the pre-fix `A`), and both drivers agree with
the family on the F-0001 seeds.
