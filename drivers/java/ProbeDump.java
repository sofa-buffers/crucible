// Crucible Java driver — materialized value dump (oracle/materialized.md).
//
// Lives in package `message` (not crucible) on purpose: the generated nested probe
// classes (ProbeNested, ProbeArrays, ProbeArraysNested) are package-private, so a
// reflective walk of their fields must sit inside their package.
//
// SCHEMA-AGNOSTIC: the value walk is driven entirely by the GENERATED descriptor
// (oracle/materialized-schema.json, produced by engine/structured/schema.py) loaded
// at runtime, NOT by a hardcoded field-by-field walk. Only the per-kind leaf
// formatting is schema-specific; the structure (which fields, their ids, nesting,
// array counts, unsigned-vs-signed element types) comes from the descriptor. A
// schema change regenerates the descriptor and needs no edit here.
//
// Emits the value dump for a COMPLETE decode under SOFAB_MATERIALIZE=1, matching
// engine/structured/materialize.py byte-for-byte. Notes on fidelity:
//   * unsigned scalars/array elements are stored in a signed `long` but printed as
//     UNSIGNED decimal (Long.toUnsignedString) per the DESCRIPTOR's declared type;
//     signed use Long.toString. The u-vs-s tag comes from the descriptor `kind`/
//     `elem`, never from the storage (all integer arrays are long[]).
//   * floats are raw IEEE bit patterns (floatToRawIntBits / doubleToRawLongBits),
//     MSB-first, %x treating the int/long as unsigned hex.
//   * strings/blobs are "<tag><utf8-byte-length>:<bytes-hex>".
package message;

import java.io.IOException;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class ProbeDump {
    private ProbeDump() {}

    private static final char[] HEX = "0123456789abcdef".toCharArray();

    // The generated schema descriptor, loaded once: { "message":..., "fields":[node,...] }.
    private static final Map<String, Object> ROOT = loadSchema();

    private static Map<String, Object> loadSchema() {
        String path = System.getenv("SOFAB_MATERIALIZE_SCHEMA");
        if (path == null || path.isEmpty()) path = "oracle/materialized-schema.json";
        try {
            byte[] bytes = Files.readAllBytes(Paths.get(path));
            Object v = new Json(new String(bytes, StandardCharsets.UTF_8)).parse();
            @SuppressWarnings("unchecked")
            Map<String, Object> root = (Map<String, Object>) v;
            return root;
        } catch (IOException e) {
            throw new RuntimeException("materialized schema load failed: " + path, e);
        }
    }

    /** Materialized value string for a decoded Probe (no "A " prefix). */
    public static String dump(Probe m) {
        // The root is a struct scope (the message) whose value is the Probe itself.
        return walkStruct(fieldsOf(ROOT), m);
    }

    // --- generic descriptor-driven walk -------------------------------------
    private static String walk(Map<String, Object> node, Object value) {
        String kind = (String) node.get("kind");
        switch (kind) {
            case "struct":
                return walkStruct(fieldsOf(node), value);
            case "u":
                return u(value);
            case "s":
                return s(value);
            case "fp32":
                return f32(value);
            case "fp64":
                return f64(value);
            case "string":
                return text(value);
            case "blob":
                return blob(value);
            case "array": {
                // Inline fixed-count numeric/fp array; declared element type is `elem`
                // (u/s distinction is descriptor-only — the storage is long[] either way).
                String elem = (String) node.get("elem");
                int n = Array.getLength(value);
                StringBuilder sb = new StringBuilder();
                sb.append('[');
                for (int i = 0; i < n; i++) {
                    if (i > 0) sb.append(',');
                    sb.append(leaf(elem, Array.get(value, i)));
                }
                sb.append(']');
                return sb.toString();
            }
            case "wrapper": {
                // Dynamic wrapper array (List): its in-memory size is the signal.
                String elem = (String) node.get("elem");
                List<?> list = (List<?>) value;
                StringBuilder sb = new StringBuilder();
                sb.append('[');
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) sb.append(',');
                    sb.append(leaf(elem, list.get(i)));
                }
                sb.append(']');
                return sb.toString();
            }
            default:
                throw new IllegalStateException("unhandled descriptor kind: " + kind);
        }
    }

    private static String walkStruct(List<Object> fields, Object value) {
        StringBuilder sb = new StringBuilder();
        sb.append('{');
        for (int i = 0; i < fields.size(); i++) {
            @SuppressWarnings("unchecked")
            Map<String, Object> child = (Map<String, Object>) fields.get(i);
            if (i > 0) sb.append(';');
            sb.append(asLong(child.get("id")));
            sb.append(':');
            sb.append(walk(child, field(value, (String) child.get("name"))));
        }
        sb.append('}');
        return sb.toString();
    }

    /** Format a single leaf value given its descriptor kind (`u|s|fp32|fp64|string|blob`). */
    private static String leaf(String kind, Object value) {
        switch (kind) {
            case "u":      return u(value);
            case "s":      return s(value);
            case "fp32":   return f32(value);
            case "fp64":   return f64(value);
            case "string": return text(value);
            case "blob":   return blob(value);
            default:       throw new IllegalStateException("unhandled leaf kind: " + kind);
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Object> fieldsOf(Map<String, Object> node) {
        return (List<Object>) node.get("fields");
    }

    /** Reflective field access by schema name: fields are public and named exactly the
     *  schema names; the nested container classes are package-private (this class is in
     *  their package), so setAccessible clears any access check. */
    private static Object field(Object value, String name) {
        try {
            Field f = value.getClass().getField(name);
            f.setAccessible(true);
            return f.get(value);
        } catch (ReflectiveOperationException e) {
            throw new RuntimeException("no schema field '" + name + "' on " + value.getClass(), e);
        }
    }

    private static long asLong(Object v) { return ((Number) v).longValue(); }

    // --- leaf encoders (unchanged formatting) --------------------------------
    private static String u(Object v) { return "u" + Long.toUnsignedString(((Number) v).longValue()); }
    private static String s(Object v) { return "s" + Long.toString(((Number) v).longValue()); }

    private static String f32(Object v) {
        return "f" + String.format("%08x", Float.floatToRawIntBits(((Number) v).floatValue()));
    }
    private static String f64(Object v) {
        return "F" + String.format("%016x", Double.doubleToRawLongBits(((Number) v).doubleValue()));
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) { int v = x & 0xff; sb.append(HEX[v >>> 4]).append(HEX[v & 0xf]); }
        return sb.toString();
    }
    private static String text(Object v) {
        byte[] b = (v == null ? "" : (String) v).getBytes(StandardCharsets.UTF_8);
        return "t" + b.length + ":" + hex(b);
    }
    private static String blob(Object v) {
        byte[] b = (v == null ? new byte[0] : (byte[]) v);
        return "b" + b.length + ":" + hex(b);
    }

    // --- minimal recursive-descent JSON parser (no external lib on classpath) --
    // Handles exactly the descriptor's shape: objects, arrays, strings, numbers,
    // true/false/null. Numbers with a '.'/'e' become Double, otherwise Long.
    private static final class Json {
        private final String s;
        private int i;

        Json(String s) { this.s = s; }

        Object parse() { Object v = value(); ws(); return v; }

        private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

        private Object value() {
            ws();
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': i += 4; return Boolean.TRUE;
                case 'f': i += 5; return Boolean.FALSE;
                case 'n': i += 4; return null;
                default:  return number();
            }
        }

        private Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; ws();                       // consume '{'
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws();
                String k = string();
                ws(); i++;                   // consume ':'
                m.put(k, value());
                ws();
                char c = s.charAt(i++);       // ',' or '}'
                if (c == '}') break;
            }
            return m;
        }

        private List<Object> array() {
            List<Object> l = new ArrayList<>();
            i++; ws();                       // consume '['
            if (s.charAt(i) == ']') { i++; return l; }
            while (true) {
                l.add(value());
                ws();
                char c = s.charAt(i++);       // ',' or ']'
                if (c == ']') break;
            }
            return l;
        }

        private String string() {
            StringBuilder sb = new StringBuilder();
            i++;                              // consume opening quote
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\') {
                    char e = s.charAt(i++);
                    switch (e) {
                        case 'n': sb.append('\n'); break;
                        case 't': sb.append('\t'); break;
                        case 'r': sb.append('\r'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case '/': sb.append('/');  break;
                        case '"': sb.append('"');  break;
                        case '\\': sb.append('\\'); break;
                        case 'u': sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                        default:  sb.append(e);
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Object number() {
            int start = i;
            boolean real = false;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == '-' || c == '+' || (c >= '0' && c <= '9')) { i++; }
                else if (c == '.' || c == 'e' || c == 'E') { real = true; i++; }
                else break;
            }
            String t = s.substring(start, i);
            return real ? (Object) Double.parseDouble(t) : (Object) Long.parseLong(t);
        }
    }
}
