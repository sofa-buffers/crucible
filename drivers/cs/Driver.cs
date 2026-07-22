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
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using sofab;
using Message;

namespace Crucible;

internal static class Driver
{
    // Materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1.
    // On a COMPLETE decode this walks the DECODED value and dumps every field +
    // every array element explicitly, instead of re-encoding to wire hex. The walk
    // is SCHEMA-AGNOSTIC: it is driven entirely by the generated descriptor
    // (engine/structured/schema.py → oracle/materialized-schema.json), reflecting
    // field values out of the generated Message.cs classes by name. Nothing about
    // the message's structure is hardcoded here — only the per-kind LEAF formatting
    // is (u/s/fp32/fp64/string/blob). The engine/structured/materialize.py reference
    // is ground truth; this output must equal it byte-for-byte. fp32 is printed
    // straight from its float bit pattern (the corelib decodes it as a native float,
    // so no widen/repack fidelity caveat applies here — contrast the Python driver).
    private static readonly bool Materialize =
        Environment.GetEnvironmentVariable("SOFAB_MATERIALIZE") == "1";

    // A descriptor node (recursive): the generated schema shape, loaded at startup.
    // Leaf: id/name/kind. struct: +fields. array: +elem(u|s|fp32|fp64)+count.
    // wrapper: +elem(string|blob)+count.
    private sealed class SchemaNode
    {
        public int Id;
        public string Name;
        public string Kind;
        public string Elem;
        public int Count;
        public List<SchemaNode> Fields;
    }

    // The generated message descriptor's top-level fields, loaded only in
    // materialize mode (parsing is skipped entirely on the default hex path).
    private static readonly List<SchemaNode> Schema = Materialize ? LoadSchema() : null;

    private static List<SchemaNode> LoadSchema()
    {
        string path = Environment.GetEnvironmentVariable("SOFAB_MATERIALIZE_SCHEMA")
            ?? "oracle/materialized-schema.json";
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        var fields = new List<SchemaNode>();
        foreach (var f in doc.RootElement.GetProperty("fields").EnumerateArray())
            fields.Add(ParseNode(f));
        return fields;
    }

    private static SchemaNode ParseNode(JsonElement e)
    {
        var n = new SchemaNode
        {
            Id = e.GetProperty("id").GetInt32(),
            Kind = e.GetProperty("kind").GetString(),
        };
        if (e.TryGetProperty("name", out var nm)) n.Name = nm.GetString();
        if (e.TryGetProperty("elem", out var el)) n.Elem = el.GetString();
        if (e.TryGetProperty("count", out var ct)) n.Count = ct.GetInt32();
        if (e.TryGetProperty("fields", out var fs))
        {
            n.Fields = new List<SchemaNode>();
            foreach (var c in fs.EnumerateArray()) n.Fields.Add(ParseNode(c));
        }
        return n;
    }

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

    // Format one leaf value per its descriptor kind (oracle/materialized.md §Grammar).
    // The element declared type (u/s/fp32/fp64/string/blob) comes from the schema, so
    // array/wrapper elements reuse this exactly as scalar leaves do.
    private static string Leaf(string kind, object v) => kind switch
    {
        "u" => U(Convert.ToUInt64(v, CultureInfo.InvariantCulture)),
        "s" => S(Convert.ToInt64(v, CultureInfo.InvariantCulture)),
        "fp32" => F32(Convert.ToSingle(v, CultureInfo.InvariantCulture)),
        "fp64" => F64(Convert.ToDouble(v, CultureInfo.InvariantCulture)),
        "string" => T((string)v),
        "blob" => B((byte[])v),
        _ => throw new InvalidOperationException("unhandled leaf kind " + kind),
    };

    // Read a message field/property by its schema name via reflection. corelib-cs's
    // generated Message.cs names members with the schema's exact casing (snake_case,
    // e.g. bytes_field / string_array) and exposes them as public fields; a property
    // is accepted too, so this survives a codegen convention change.
    private static object GetMember(object obj, string name, out Type declared)
    {
        Type t = obj.GetType();
        var f = t.GetField(name);
        if (f != null) { declared = f.FieldType; return f.GetValue(obj); }
        var p = t.GetProperty(name);
        if (p != null) { declared = p.PropertyType; return p.GetValue(obj); }
        throw new MissingMemberException(t.Name, name);
    }

    // Generic, schema-driven walk of the decoded value. Structure comes entirely from
    // the descriptor node; only Leaf() is schema-specific (per-kind formatting).
    private static string Walk(SchemaNode node, object value)
    {
        switch (node.Kind)
        {
            case "struct":
                return WalkStruct(node.Fields, value);
            case "array":
            {
                // Fixed-count numeric/fp array, materialized to its full N in memory:
                // every element emitted, no trailing trim (that only elides on the wire).
                var arr = (Array)value;
                var sb = new StringBuilder("[");
                for (int i = 0; i < arr.Length; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(Leaf(node.Elem, arr.GetValue(i)));
                }
                return sb.Append(']').ToString();
            }
            case "wrapper":
            {
                // string_array / blob_array: the decoded container is already grown to
                // highest-populated index + 1 with interior gaps as empty elements —
                // emit all Count elements in index order.
                var list = (System.Collections.IList)value;
                var sb = new StringBuilder("[");
                for (int i = 0; i < list.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(Leaf(node.Elem, list[i]));
                }
                return sb.Append(']').ToString();
            }
            default:
                return Leaf(node.Kind, value);
        }
    }

    private static string WalkStruct(List<SchemaNode> fields, object value)
    {
        var sb = new StringBuilder("{");
        for (int i = 0; i < fields.Count; i++)
        {
            SchemaNode c = fields[i];
            if (i > 0) sb.Append(';');
            object cv = GetMember(value, c.Name, out Type ct);
            // A nested struct member is initialized non-null by the generated code, but
            // guard defensively (mirrors the old `?? new` walk) so a null never NREs.
            if (c.Kind == "struct" && cv == null) cv = Activator.CreateInstance(ct);
            sb.Append(c.Id.ToString(CultureInfo.InvariantCulture)).Append(':').Append(Walk(c, cv));
        }
        return sb.Append('}').ToString();
    }

    // Dump the decoded value per oracle/materialized.md: a single-line object, fields
    // in ascending id order (the descriptor's order), no field ever omitted.
    private static string MaterializeValue(Probe m) => WalkStruct(Schema, m);

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
