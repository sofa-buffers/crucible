// Crucible Java driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-java code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Like Python (and unlike Rust/C++), the generated Java `Probe.decode` is
// fallible: it wraps a decode failure in a RuntimeException, so the verdict is a
// plain try/catch — no two-pass workaround.
//
// The Java coverage engine is Jazzer — see FuzzProbe.java.
package crucible;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;

import message.Probe;

public final class Driver {

    private static String rejectClass(RuntimeException e) {
        // corelib-java surfaces a decode failure as the RuntimeException's cause.
        // Coarse mapping in Phase 2 (reject-class comparison is soft per policy);
        // refine to the canonical taxonomy once the Java exception types are pinned.
        Throwable c = (e.getCause() != null) ? e.getCause() : e;
        String n = c.getClass().getSimpleName().toLowerCase();
        if (n.contains("range") || n.contains("argument")) return "argument";
        if (n.contains("state") || n.contains("usage")) return "usage";
        if (n.contains("buffer")) return "buffer_full";
        return "invalid_msg";
    }

    private static String canonical(byte[] data) {
        // decode -> re-encode -> hex (oracle/canonical.md).
        byte[] enc;
        try {
            Probe m = Probe.decode(data);
            enc = m.encode();
        } catch (RuntimeException e) {
            return "R " + rejectClass(e);
        }
        StringBuilder sb = new StringBuilder("A ");
        for (byte b : enc) {
            sb.append(String.format("%02x", b & 0xff));
        }
        return sb.toString();
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
