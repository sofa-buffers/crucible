// Crucible Java driver — materialized value dump (oracle/materialized.md).
//
// Lives in package `message` (not crucible) on purpose: the generated nested probe
// classes (ProbeNested, ProbeArrays, ProbeArraysNested) are package-private, so a
// hand walk of every one of their public fields must sit inside their package. The
// corelib-java generated code exposes no reflection descriptor (contrast the C
// driver's sofab_object_descr walk), so every field is enumerated explicitly here.
//
// Emits the value dump for a COMPLETE decode under SOFAB_MATERIALIZE=1, matching
// engine/structured/materialize.py byte-for-byte. Notes on fidelity:
//   * unsigned scalars/array elements are stored in a signed `long` but printed as
//     UNSIGNED decimal (Long.toUnsignedString) per the field's DECLARED type; signed
//     use Long.toString. An unsigned array stored as long[] still prints "u<...>".
//   * floats are raw IEEE bit patterns (floatToRawIntBits / doubleToRawLongBits),
//     MSB-first, %x treating the int/long as unsigned hex.
//   * strings/blobs are "<tag><utf8-byte-length>:<bytes-hex>".
package message;

import java.nio.charset.StandardCharsets;

public final class ProbeDump {
    private ProbeDump() {}

    private static final char[] HEX = "0123456789abcdef".toCharArray();

    /** Materialized value string for a decoded Probe (no "A " prefix). */
    public static String dump(Probe m) {
        StringBuilder sb = new StringBuilder();
        sb.append('{');
        // top-level scalars, ids 0..7 (u8,i8,u16,i16,u32,i32,u64,i64)
        sb.append("0:");   u(sb, m.u8);   sb.append(';');
        sb.append("1:");   s(sb, m.i8);   sb.append(';');
        sb.append("2:");   u(sb, m.u16);  sb.append(';');
        sb.append("3:");   s(sb, m.i16);  sb.append(';');
        sb.append("4:");   u(sb, m.u32);  sb.append(';');
        sb.append("5:");   s(sb, m.i32);  sb.append(';');
        sb.append("6:");   u(sb, m.u64);  sb.append(';');
        sb.append("7:");   s(sb, m.i64);  sb.append(';');

        // nested struct, id 10: f32(0) f64(1) str(2) blob(3)
        ProbeNested n = m.nested;
        sb.append("10:{");
        sb.append("0:");  f32(sb, n.f32);          sb.append(';');
        sb.append("1:");  f64(sb, n.f64);          sb.append(';');
        sb.append("2:");  text(sb, n.str);         sb.append(';');
        sb.append("3:");  blob(sb, n.bytes_field);
        sb.append('}');
        sb.append(';');

        // arrays struct, id 100: eight numeric arrays (0..7) + nested fp arrays (id 10)
        ProbeArrays a = m.arrays;
        sb.append("100:{");
        sb.append("0:");  uArr(sb, a.u8);   sb.append(';');
        sb.append("1:");  sArr(sb, a.i8);   sb.append(';');
        sb.append("2:");  uArr(sb, a.u16);  sb.append(';');
        sb.append("3:");  sArr(sb, a.i16);  sb.append(';');
        sb.append("4:");  uArr(sb, a.u32);  sb.append(';');
        sb.append("5:");  sArr(sb, a.i32);  sb.append(';');
        sb.append("6:");  uArr(sb, a.u64);  sb.append(';');
        sb.append("7:");  sArr(sb, a.i64);  sb.append(';');
        ProbeArraysNested an = a.nested;
        sb.append("10:{");
        sb.append("0:");  f32Arr(sb, an.fp32);  sb.append(';');
        sb.append("1:");  f64Arr(sb, an.fp64);
        sb.append('}');
        sb.append('}');
        sb.append(';');

        // wrapper arrays: string_array (id 200), blob_array (id 201) — the container's
        // in-memory length is the signal, so emit indices 0..size()-1 (gaps already "").
        sb.append("200:[");
        for (int i = 0; i < m.string_array.size(); i++) {
            if (i > 0) sb.append(',');
            text(sb, m.string_array.get(i));
        }
        sb.append(']');
        sb.append(';');
        sb.append("201:[");
        for (int i = 0; i < m.blob_array.size(); i++) {
            if (i > 0) sb.append(',');
            blob(sb, m.blob_array.get(i));
        }
        sb.append(']');

        sb.append('}');
        return sb.toString();
    }

    // --- leaf encoders -------------------------------------------------------
    private static void u(StringBuilder sb, long v) { sb.append('u').append(Long.toUnsignedString(v)); }
    private static void s(StringBuilder sb, long v) { sb.append('s').append(Long.toString(v)); }

    private static void f32(StringBuilder sb, float f) {
        sb.append('f').append(String.format("%08x", Float.floatToRawIntBits(f)));
    }
    private static void f64(StringBuilder sb, double d) {
        sb.append('F').append(String.format("%016x", Double.doubleToRawLongBits(d)));
    }

    private static void hex(StringBuilder sb, byte[] b) {
        for (byte x : b) { int v = x & 0xff; sb.append(HEX[v >>> 4]).append(HEX[v & 0xf]); }
    }
    private static void text(StringBuilder sb, String str) {
        byte[] b = (str == null ? "" : str).getBytes(StandardCharsets.UTF_8);
        sb.append('t').append(b.length).append(':'); hex(sb, b);
    }
    private static void blob(StringBuilder sb, byte[] b) {
        if (b == null) b = new byte[0];
        sb.append('b').append(b.length).append(':'); hex(sb, b);
    }

    private static void uArr(StringBuilder sb, long[] a) {
        sb.append('['); for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); u(sb, a[i]); } sb.append(']');
    }
    private static void sArr(StringBuilder sb, long[] a) {
        sb.append('['); for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); s(sb, a[i]); } sb.append(']');
    }
    private static void f32Arr(StringBuilder sb, float[] a) {
        sb.append('['); for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); f32(sb, a[i]); } sb.append(']');
    }
    private static void f64Arr(StringBuilder sb, double[] a) {
        sb.append('['); for (int i = 0; i < a.length; i++) { if (i > 0) sb.append(','); f64(sb, a[i]); } sb.append(']');
    }
}
