// Crucible C# driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-cs code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Like Python/Java/TS (and unlike Rust/C++), the generated C# Probe.Decode
// throws (SofabException) on malformed input, so the verdict is a try/catch.
//
// The C# coverage engine is SharpFuzz — see Fuzz.cs.
using System;
using System.IO;
using System.Text;
using sofab;
using Message;

namespace Crucible;

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
        // decode -> re-encode -> hex (oracle/canonical.md).
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
