// Crucible C# driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-cs code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Verdict is three-valued (oracle/canonical.md, MESSAGE_SPEC §7): A COMPLETE /
// I INCOMPLETE / R INVALID. Single-pass decode via the generated status-returning
// `Probe.TryDecode(byte[], out Probe)` (sofabgen 0.16.0 — G-0008 fixed, see
// docs/SOFABGEN.md): it feeds the bytes AND returns the terminal `DecodeStatus`,
// so one call yields both the verdict (its returned status, or the SofabException
// it throws on malformed input) and the decoded value (`msg`, re-encoded for the
// hex on a COMPLETE decode). This replaces the earlier two-pass workaround that
// re-ran `IStream.Feed` against a null visitor because `Probe.Decode` discarded
// the status.
//
// The C# coverage engine is SharpFuzz — see Fuzz.cs.
using System;
using System.Globalization;
using System.IO;
using System.Text;
using sofab;
using Message;

namespace Crucible;

internal static class Driver
{
    // Materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1.
    // On a COMPLETE decode this walks the DECODED value and dumps every field +
    // every array element explicitly, instead of re-encoding to wire hex. corelib-cs
    // has no reflective descriptor, so every field is hand-walked from the generated
    // Message.cs classes. The engine/structured/materialize.py reference is ground
    // truth; this output must equal it byte-for-byte. fp32 is printed straight from
    // its float bit pattern (the corelib decodes it as a native float, so no widen/
    // repack fidelity caveat applies here — contrast the Python driver).
    private static readonly bool Materialize =
        Environment.GetEnvironmentVariable("SOFAB_MATERIALIZE") == "1";

    private static string Hex(byte[] b)
    {
        var sb = new StringBuilder(b.Length * 2);
        foreach (byte x in b) sb.Append(x.ToString("x2", CultureInfo.InvariantCulture));
        return sb.ToString();
    }

    private static string U(ulong v) => "u" + v.ToString(CultureInfo.InvariantCulture);
    private static string S(long v) => "s" + v.ToString(CultureInfo.InvariantCulture);
    private static string F32(float x) =>
        "f" + ((uint)BitConverter.SingleToInt32Bits(x)).ToString("x8", CultureInfo.InvariantCulture);
    private static string F64(double x) =>
        "F" + ((ulong)BitConverter.DoubleToInt64Bits(x)).ToString("x16", CultureInfo.InvariantCulture);

    private static string T(string s)
    {
        byte[] b = Encoding.UTF8.GetBytes(s ?? "");
        return "t" + b.Length.ToString(CultureInfo.InvariantCulture) + ":" + Hex(b);
    }

    private static string B(byte[] bb)
    {
        bb ??= Array.Empty<byte>();
        return "b" + bb.Length.ToString(CultureInfo.InvariantCulture) + ":" + Hex(bb);
    }

    // Fixed-count numeric arrays (materialized to their full N in memory): every
    // element emitted, no trailing trim (that only elides on the wire).
    private static string ArrU<T>(T[] arr) where T : struct
    {
        var sb = new StringBuilder("[");
        for (int i = 0; i < arr.Length; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append(U(Convert.ToUInt64(arr[i], CultureInfo.InvariantCulture)));
        }
        return sb.Append(']').ToString();
    }

    private static string ArrS<T>(T[] arr) where T : struct
    {
        var sb = new StringBuilder("[");
        for (int i = 0; i < arr.Length; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append(S(Convert.ToInt64(arr[i], CultureInfo.InvariantCulture)));
        }
        return sb.Append(']').ToString();
    }

    private static string ArrF32(float[] arr)
    {
        var sb = new StringBuilder("[");
        for (int i = 0; i < arr.Length; i++) { if (i > 0) sb.Append(','); sb.Append(F32(arr[i])); }
        return sb.Append(']').ToString();
    }

    private static string ArrF64(double[] arr)
    {
        var sb = new StringBuilder("[");
        for (int i = 0; i < arr.Length; i++) { if (i > 0) sb.Append(','); sb.Append(F64(arr[i])); }
        return sb.Append(']').ToString();
    }

    // Dump the decoded value per oracle/materialized.md: a single-line object,
    // fields in ascending id order, no field ever omitted.
    private static string MaterializeValue(Probe m)
    {
        var sb = new StringBuilder();
        sb.Append('{');
        // top-level scalars (ids 0..7): unsigned via their unsigned type, signed via signed.
        sb.Append("0:").Append(U(m.u8)).Append(';');
        sb.Append("1:").Append(S(m.i8)).Append(';');
        sb.Append("2:").Append(U(m.u16)).Append(';');
        sb.Append("3:").Append(S(m.i16)).Append(';');
        sb.Append("4:").Append(U(m.u32)).Append(';');
        sb.Append("5:").Append(S(m.i32)).Append(';');
        sb.Append("6:").Append(U(m.u64)).Append(';');
        sb.Append("7:").Append(S(m.i64)).Append(';');

        // nested struct (id 10): f32(0) f64(1) str(2) bytes_field(3).
        ProbeNested n = m.nested ?? new ProbeNested();
        sb.Append("10:{");
        sb.Append("0:").Append(F32(n.f32)).Append(';');
        sb.Append("1:").Append(F64(n.f64)).Append(';');
        sb.Append("2:").Append(T(n.str)).Append(';');
        sb.Append("3:").Append(B(n.bytes_field));
        sb.Append("};");

        // arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10).
        ProbeArrays a = m.arrays ?? new ProbeArrays();
        sb.Append("100:{");
        sb.Append("0:").Append(ArrU(a.u8)).Append(';');
        sb.Append("1:").Append(ArrS(a.i8)).Append(';');
        sb.Append("2:").Append(ArrU(a.u16)).Append(';');
        sb.Append("3:").Append(ArrS(a.i16)).Append(';');
        sb.Append("4:").Append(ArrU(a.u32)).Append(';');
        sb.Append("5:").Append(ArrS(a.i32)).Append(';');
        sb.Append("6:").Append(ArrU(a.u64)).Append(';');
        sb.Append("7:").Append(ArrS(a.i64)).Append(';');
        ProbeArraysNested an = a.nested ?? new ProbeArraysNested();
        sb.Append("10:{");
        sb.Append("0:").Append(ArrF32(an.fp32)).Append(';');
        sb.Append("1:").Append(ArrF64(an.fp64));
        sb.Append("}};");

        // wrapper arrays: string_array (id 200), blob_array (id 201). The decoded
        // container is already grown to highest-populated index + 1 with interior
        // gaps as empty elements — emit all Count elements in index order.
        sb.Append("200:[");
        for (int i = 0; i < m.string_array.Count; i++) { if (i > 0) sb.Append(','); sb.Append(T(m.string_array[i])); }
        sb.Append("];");
        sb.Append("201:[");
        for (int i = 0; i < m.blob_array.Count; i++) { if (i > 0) sb.Append(','); sb.Append(B(m.blob_array[i])); }
        sb.Append(']');

        sb.Append('}');
        return sb.ToString();
    }

    private static string RejectClass(SofabException e) => e.Error switch
    {
        SofabError.InvalidMessage => "invalid_msg",
        SofabError.Argument => "argument",
        SofabError.Usage => "usage",
        SofabError.BufferFull => "buffer_full",
        _ => "other",
    };

    // Map a decode exception to its canonical line prefix. LIMIT_EXCEEDED
    // (generator#102, limit mode only) is a policy rejection distinct from INVALID
    // and gets its own verdict `L`; everything else is an `R <class>` reject.
    private static string ErrLine(SofabException e) =>
        e.Error == SofabError.LimitExceeded ? "L" : "R " + RejectClass(e);

    private static string Canonical(byte[] data)
    {
        // One pass: TryDecode fills `m` and returns the corelib's real §7 outcome
        // (or throws SofabException on malformed input).
        DecodeStatus status;
        Probe m;
        try
        {
            status = Probe.TryDecode(data, out m);
        }
        catch (SofabException e) { return ErrLine(e); }
        catch (Exception) { return "R other"; }

        // INCOMPLETE: bytes ended mid-message — the third verdict, not an error.
        // (Optional I <hex> partial-value payload is not materialized here.)
        if (status == DecodeStatus.Incomplete) return "I";

        // COMPLETE, materialize mode (oracle/materialized.md): dump the decoded
        // value's fields/elements explicitly instead of re-encoding to wire hex.
        if (Materialize) return "A " + MaterializeValue(m);

        // COMPLETE: value via re-encode -> hex.
        byte[] enc;
        try
        {
            enc = m.Encode();
        }
        catch (SofabException e) { return ErrLine(e); }
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
