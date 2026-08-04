// Crucible Java driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-java code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Single-pass decode via the generated status-returning `Probe.tryDecode(byte[],
// Probe)` (sofabgen 0.16.0 — G-0008 fixed, see docs/SOFABGEN.md): it feeds the
// bytes into the passed `Probe`, then returns the terminal `IStream.status()`, so
// one call yields both the three-valued VERDICT (its returned status, or the
// SofabException it throws on malformed input) and the decoded VALUE (the filled
// `Probe`, re-encoded for the A/I hex). This replaces the earlier two-pass
// workaround that re-ran `IStream.feed` against a null visitor because the plain
// `Probe.decode` discarded the status.
//
// The Java coverage engine is Jazzer — see FuzzProbe.java.
package crucible;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.List;

import message.Probe;

import org.sofabuffers.sofab.DecodeStatus;
import org.sofabuffers.sofab.OStream;
import org.sofabuffers.sofab.SofabError;
import org.sofabuffers.sofab.SofabException;

public final class Driver {

    // Materialized value dump mode (oracle/materialized.md): when SOFAB_MATERIALIZE=1,
    // an A (COMPLETE) decode emits a full walk of the decoded value instead of the
    // re-encoded wire hex. I/R/L and the default (env unset) path are unchanged.
    private static final boolean MATERIALIZE = "1".equals(System.getenv("SOFAB_MATERIALIZE"));

    // ---- the streaming axes (drivers/common/CONTRACT.md) ------------------------
    //
    // The replay protocol hands each record over whole and re-encodes it with one
    // call, so neither streaming surface of the generated API is reachable through
    // it. Unset, every variable below is today's behaviour byte for byte.
    //
    // Java's generated Decoder DOES expose status(), so the verdict comes from there
    // rather than from finish() — finish() throws when the stream ended mid-field,
    // and routing the verdict through it would bake that into the canonical line.
    private static int envInt(String name) {
        String v = System.getenv(name);
        if (v == null || v.isEmpty()) return 0;
        try { return Integer.parseInt(v); } catch (NumberFormatException e) { return 0; }
    }
    private static final int SPLIT = envInt("SOFAB_SPLIT");
    private static final int CHUNK = envInt("SOFAB_CHUNK");
    private static final int FLUSH = envInt("SOFAB_FLUSH");
    private static final boolean SCRUB;
    private static final String ENCODE;
    static {
        String s = System.getenv("SOFAB_CHUNK_SCRUB");
        SCRUB = s != null && !s.isEmpty() && !s.equals("0");
        String e = System.getenv("SOFAB_ENCODE");
        ENCODE = (e == null || e.isEmpty()) ? "new" : e;
        if (!ENCODE.equals("new") && !ENCODE.equals("to") && !ENCODE.equals("stream")) {
            System.err.println("crucible-java: unknown SOFAB_ENCODE=" + ENCODE
                + " (this backend has new, to, stream)");
            System.exit(2);
        }
        // Announce on stderr (never parsed). A driver that silently ignored these
        // would be indistinguishable from one that honours them — stdout is identical
        // either way — so this makes "it really re-feeds" checkable, not asserted.
        if (SPLIT != 0 || CHUNK != 0 || SCRUB || FLUSH != 0 || !ENCODE.equals("new")) {
            System.err.println("crucible-java: streaming cfg split=" + SPLIT + " chunk="
                + CHUNK + " scrub=" + (SCRUB ? 1 : 0) + " enc=" + ENCODE
                + " flush=" + FLUSH);
        }
    }
    private static final boolean CHUNKING = SPLIT != 0 || CHUNK != 0 || SCRUB;

    /** How the record is cut on its way in. Never an empty chunk; a 0-byte record
     *  yields none at all. */
    private static List<byte[]> chunksOf(byte[] data) {
        List<byte[]> out = new ArrayList<>();
        int len = data.length;
        if (len == 0) return out;
        if (CHUNK > 0) {
            for (int o = 0; o < len; o += CHUNK) {
                int n = Math.min(CHUNK, len - o);
                byte[] c = new byte[n];
                System.arraycopy(data, o, c, 0, n);
                out.add(c);
            }
            return out;
        }
        if (SPLIT > 0 && SPLIT < len) {
            byte[] a = new byte[SPLIT];
            byte[] b = new byte[len - SPLIT];
            System.arraycopy(data, 0, a, 0, SPLIT);
            System.arraycopy(data, SPLIT, b, 0, len - SPLIT);
            out.add(a);
            out.add(b);
            return out;
        }
        byte[] whole = new byte[len];
        System.arraycopy(data, 0, whole, 0, len);
        out.add(whole);
        return out;
    }

    /** Re-encode through the surface SOFAB_ENCODE selects. All three must emit
     *  identical bytes, and SOFAB_FLUSH must not change them either: it gives the
     *  OStream an n-byte buffer draining to a sink, so the encoder crosses a buffer
     *  boundary at every offset. */
    private static byte[] encodeVia(Probe m) throws IOException {
        if (ENCODE.equals("new")) return m.encode();
        int cap = FLUSH > 0 ? FLUSH : Probe.MAX_SIZE;
        ByteArrayOutputStream acc = new ByteArrayOutputStream();
        OStream os = new OStream(new byte[cap], 0, (buf, off, len) -> acc.write(buf, off, len));
        if (ENCODE.equals("to")) {
            m.encodeTo(os);          // serialize + flush, per the generated doc
        } else {
            m.serialize(os);
            os.flush();
        }
        return acc.toByteArray();
    }

    private static String rejectClass(SofabException e) {
        // corelib-java carries the canonical category on the exception itself
        // (SofabError), so branch on it rather than string-matching class names.
        switch (e.error()) {
            case ARGUMENT:    return "argument";
            // USAGE was removed in corelib-java#49; the canonical "usage" class
            // stays in oracle/canonical.md for the corelibs that still have it.
            // Anything unmapped falls through to the invalid_msg default below.
            case BUFFER_FULL: return "buffer_full";
            case INVALID_MSG:
            default:          return "invalid_msg";
        }
    }

    // LIMIT_EXCEEDED (generator#102, limit mode only) is a policy rejection distinct
    // from INVALID and gets its own verdict `L`; everything else is an `R <class>`.
    private static String errLine(SofabException e) {
        return e.error() == SofabError.LIMIT_EXCEEDED ? "L" : "R " + rejectClass(e);
    }

    private static String hexValue(char verdict, Probe m) {
        // Value for an A (COMPLETE) or I (INCOMPLETE) line: re-encode the decoded
        // message -> hex (oracle/canonical.md). For I this is the partial value
        // filled before truncation (the `incomplete_value` axis is soft in Phase 2;
        // the verdict itself is hard).
        byte[] enc;
        try {
            enc = encodeVia(m);
        } catch (IOException e) {
            return "R other";
        } catch (RuntimeException e) {
            // encode failed after tryDecode reported A/I — should not happen given a
            // worst-case buffer; report it as a reject class.
            Throwable c = (e.getCause() != null) ? e.getCause() : e;
            if (c instanceof SofabException) {
                return errLine((SofabException) c);
            }
            return "R other";
        }
        StringBuilder sb = new StringBuilder();
        sb.append(verdict).append(' ');
        for (byte b : enc) {
            sb.append(String.format("%02x", b & 0xff));
        }
        return sb.toString();
    }

    private static String canonical(byte[] data) {
        // One pass: tryDecode fills `m` and returns the corelib's real three-valued
        // outcome (or throws SofabException on malformed input, MESSAGE_SPEC §7).
        Probe m = new Probe();
        DecodeStatus status;
        try {
            if (CHUNKING) {
                // Chunked decode via the generated Decoder, taken ONLY when a chunking
                // variable is set — the default stays the one-shot tryDecode byte for
                // byte, which is also what makes the gate meaningful: it then compares
                // two genuinely different code paths. The verdict comes from status(),
                // never from finish(), which throws mid-field (CONTRACT.md).
                Probe.Decoder d = Probe.decoder();
                for (byte[] c : chunksOf(data)) {
                    d.feed(c);
                    // Scrub: the chunk is a copy the driver owns, so overwriting it
                    // after feed exposes a decoder that borrowed instead of copying.
                    if (SCRUB) java.util.Arrays.fill(c, (byte) 0xA5);
                }
                status = d.status();
                m = d.message();
            } else {
                status = Probe.tryDecode(data, m);
            }
        } catch (SofabException e) {
            return errLine(e);
        } catch (RuntimeException e) {
            // Generated decode raises rejections from inside the visitor as an
            // unchecked wrapper (e.g. UncheckedIOException around a SofabException),
            // so the real category — including LIMIT_EXCEEDED — arrives here rather
            // than the checked branch above. Unwrap to preserve the L/R distinction;
            // a genuinely foreign RuntimeException still falls through to "R other".
            Throwable c = (e.getCause() != null) ? e.getCause() : e;
            if (c instanceof SofabException) {
                return errLine((SofabException) c);
            }
            return "R other";
        }
        // INCOMPLETE (MESSAGE_SPEC §7): bytes end mid-message — the third canonical
        // verdict, neither accept (A) nor reject (R). Not an error. COMPLETE emits A.
        char verdict = (status == DecodeStatus.INCOMPLETE) ? 'I' : 'A';
        // Materialized mode replaces only the A payload with the decoded-value dump
        // (oracle/materialized.md); I keeps the round-trip hex of its partial value.
        if (verdict == 'A' && MATERIALIZE) {
            return "A " + message.ProbeDump.dump(m);
        }
        return hexValue(verdict, m);
    }

    private static boolean readFully(InputStream in, byte[] buf, int n) throws IOException {
        int off = 0;
        while (off < n) {
            int r = in.read(buf, off, n - off);
            if (r < 0) return false;
            off += r;
        }
        return true;
    }

    public static void main(String[] args) throws IOException {
        InputStream in = new BufferedInputStream(System.in);
        PrintStream out = System.out;
        byte[] lenbuf = new byte[4];
        while (true) {
            int first = in.read();
            if (first < 0) break; // clean EOF at record boundary
            lenbuf[0] = (byte) first;
            for (int k = 1; k < 4; k++) {
                int b = in.read();
                if (b < 0) { System.err.println("crucible-java: short length prefix"); System.exit(1); }
                lenbuf[k] = (byte) b;
            }
            long n = (lenbuf[0] & 0xffL) | ((lenbuf[1] & 0xffL) << 8)
                   | ((lenbuf[2] & 0xffL) << 16) | ((lenbuf[3] & 0xffL) << 24);
            byte[] data = new byte[(int) n];
            if (n > 0 && !readFully(in, data, (int) n)) {
                System.err.println("crucible-java: short payload");
                System.exit(1);
            }
            out.println(canonical(data));
            out.flush();
        }
    }
}
