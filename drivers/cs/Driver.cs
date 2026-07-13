// Crucible C# driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-cs code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Verdict is three-valued (oracle/canonical.md, MESSAGE_SPEC §7): A COMPLETE /
// I INCOMPLETE / R INVALID. Two-pass decode, mirroring drivers/rust/driver.rs
// (docs/SOFABGEN.md G-0001, and now the C# analogue): the generated
// `Probe.Decode` DISCARDS the `DecodeStatus` that `IStream.Feed` returns, so it
// cannot tell COMPLETE from INCOMPLETE — a truncated message decodes to the
// default value and would wrongly re-encode as `A`. We therefore take the
// VERDICT from a direct `IStream.Feed` against a null visitor (its returned
// DecodeStatus, or the SofabException it throws on malformed input) and use the
// generated `Probe.Decode`+`Encode` only for the VALUE hex on a COMPLETE decode.
// Visitor callbacks cannot affect Feed's status (they return void), so the
// null-pass verdict equals the one inside `Decode`.
//
// The C# coverage engine is SharpFuzz — see Fuzz.cs.
using System;
using System.IO;
using System.Text;
using sofab;
using Message;

namespace Crucible;

// No-op sink: IVisitor's methods are all default (no-op) interface methods, so
// an empty implementor drops every field. Used only to drive Feed for the
// verdict; the value comes from the generated ProbeVisitor via Probe.Decode.
internal sealed class NullVisitor : IVisitor { }

internal static class Driver
{
    private static string RejectClass(SofabException e) => e.Error switch
    {
        SofabError.InvalidMessage => "invalid_msg",
        SofabError.Argument => "argument",
        SofabError.Usage => "usage",
        SofabError.BufferFull => "buffer_full",
        _ => "other",
    };

    private static string Canonical(byte[] data)
    {
        // Verdict: the corelib's real §7 outcome (visitor-independent).
        DecodeStatus status;
        try
        {
            status = new IStream().Feed(data, 0, data.Length, new NullVisitor());
        }
        catch (SofabException e) { return "R " + RejectClass(e); }
        catch (Exception) { return "R other"; }

        // INCOMPLETE: bytes ended mid-message — the third verdict, not an error.
        // (Optional I <hex> partial-value payload is not materialized here.)
        if (status == DecodeStatus.Incomplete) return "I";

        // COMPLETE: value via generated decode -> re-encode -> hex.
        byte[] enc;
        try
        {
            Probe m = Probe.Decode(data);
            enc = m.Encode();
        }
        catch (SofabException e) { return "R " + RejectClass(e); }
        catch (Exception) { return "R other"; }

        var sb = new StringBuilder("A ");
        foreach (byte b in enc) sb.Append(b.ToString("x2"));
        return sb.ToString();
    }

    private static bool ReadFully(Stream s, byte[] buf, int n)
    {
        int off = 0;
        while (off < n)
        {
            int r = s.Read(buf, off, n - off);
            if (r <= 0) return false;
            off += r;
        }
        return true;
    }

    private static void Main()
    {
        Stream stdin = Console.OpenStandardInput();
        var w = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
        w.NewLine = "\n";
        byte[] lenbuf = new byte[4];
        while (true)
        {
            if (!ReadFully(stdin, lenbuf, 4)) break; // clean EOF at record boundary
            uint n = (uint)(lenbuf[0] | (lenbuf[1] << 8) | (lenbuf[2] << 16) | (lenbuf[3] << 24));
            byte[] data = new byte[n];
            if (n > 0 && !ReadFully(stdin, data, (int)n))
            {
                Console.Error.WriteLine("crucible-cs: short payload");
                Environment.Exit(1);
            }
            w.Write(Canonical(data));
            w.Write('\n');
            w.Flush();
        }
    }
}
