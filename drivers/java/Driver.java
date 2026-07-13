// Crucible Java driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-java code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Two-pass decode (see docs/SOFABGEN.md): the generated Java `Probe.decode`
// feeds the bytes to an IStream but DISCARDS the terminal `IStream.status()`, so
// it cannot tell COMPLETE from INCOMPLETE — a truncated message decodes without
// throwing and would wrongly read as accept (A). Mirroring the Rust driver, we
// recover the faithful three-valued VERDICT by re-running `IStream.feed` against
// a null visitor and reading `status()`, and take the VALUE (for A/I hex) from
// the generated `Probe.decode`. Visitor callbacks return unit and cannot affect
// feed's outcome, so the null-pass verdict equals the one inside `decode`.
//
// The Java coverage engine is Jazzer — see FuzzProbe.java.
package crucible;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;

import message.Probe;

import org.sofabuffers.sofab.DecodeStatus;
import org.sofabuffers.sofab.IStream;
import org.sofabuffers.sofab.SofabError;
import org.sofabuffers.sofab.SofabException;
import org.sofabuffers.sofab.Visitor;

public final class Driver {

    // Verdict pass sink: every Visitor method defaults to a no-op, so decoded
    // fields are dropped. We only care whether feed throws (INVALID) and what
    // status() reports afterwards (COMPLETE vs INCOMPLETE).
    private static final class Null implements Visitor {
    }

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

    private static String hexValue(char verdict, byte[] data) {
        // Value for an A (COMPLETE) or I (INCOMPLETE) line: the generated
        // decode->re-encode->hex pipeline (oracle/canonical.md). For I this is the
        // partial value decoded before truncation (the `incomplete_value` axis is
        // soft in Phase 2; the verdict itself is hard).
        byte[] enc;
        try {
            Probe m = Probe.decode(data);
            enc = m.encode();
        } catch (RuntimeException e) {
            // decode/encode failed after the verdict pass agreed on A/I — should
            // not happen given a worst-case buffer; report it as a reject class.
            Throwable c = (e.getCause() != null) ? e.getCause() : e;
            if (c instanceof SofabException) {
                return "R " + rejectClass((SofabException) c);
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
        // Verdict: the corelib's real three-valued outcome (visitor-independent).
        IStream is = new IStream();
        try {
            is.feed(data, new Null());
        } catch (SofabException e) {
            // Malformed regardless of what follows (MESSAGE_SPEC §7).
            return "R " + rejectClass(e);
        } catch (RuntimeException e) {
            return "R other";
        }
        if (is.status() == DecodeStatus.INCOMPLETE) {
            // INCOMPLETE (MESSAGE_SPEC §7): bytes end mid-message — the third
            // canonical verdict, neither accept (A) nor reject (R). Not an error.
            return hexValue('I', data);
        }
        // COMPLETE: a valid message; emit A <hex> of the re-encoded value.
        return hexValue('A', data);
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
