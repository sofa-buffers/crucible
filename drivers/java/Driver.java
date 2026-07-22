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
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;

import message.Probe;

import org.sofabuffers.sofab.DecodeStatus;
import org.sofabuffers.sofab.SofabError;
import org.sofabuffers.sofab.SofabException;

public final class Driver {

    // Materialized value dump mode (oracle/materialized.md): when SOFAB_MATERIALIZE=1,
    // an A (COMPLETE) decode emits a full walk of the decoded value instead of the
    // re-encoded wire hex. I/R/L and the default (env unset) path are unchanged.
    private static final boolean MATERIALIZE = "1".equals(System.getenv("SOFAB_MATERIALIZE"));

    private static String rejectClass(SofabException e) {
        // corelib-java carries the canonical category on the exception itself
        // (SofabError), so branch on it rather than string-matching class names.
        switch (e.error()) {
            case ARGUMENT:    return "argument";
            case USAGE:       return "usage";
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
            enc = m.encode();
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
            status = Probe.tryDecode(data, m);
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
