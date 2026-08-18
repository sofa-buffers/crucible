// Crucible Kotlin Multiplatform driver — persistent replay front-end for the
// differential loop, shared by every KMP target.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-kotlin-mp code,
// and writes one canonical line (oracle/canonical.md) per record to stdout.
//
// ONE SOURCE, N TARGETS. corelib-kotlin-mp is a Kotlin Multiplatform library: one
// `commonMain` codec compiled for the JVM, for Kotlin/Native and for Node, with a
// per-target `expect`/`actual` for little-endian word access alone (byte-array
// VarHandles on the JVM, indexed shifts elsewhere). Those are different machine
// code paths through the same decoder, so they are different implementations to
// compare — the drivers/rust/ pattern, where one driver.rs serves corelib-rs and
// corelib-rs-no-std and both are registered in drivers/roster.
//
// Everything below is target-agnostic Kotlin. The three things a replay driver
// needs that common Kotlin has no API for — the environment, binary stdin, and
// stdout — come from `Io`, which each `io_<target>.kt` supplies for its target;
// build.sh compiles exactly one of them next to this file. That file also carries
// `main`, so this one has no entry point of its own.
//
// Single-pass decode via the generated status-returning `Probe.tryDecode(ByteArray,
// Probe)`: it feeds the bytes into the passed `Probe`, then returns the terminal
// `IStream.status`, so one call yields both the three-valued VERDICT (its returned
// status, or the SofabException it throws on malformed input) and the decoded VALUE
// (the filled `Probe`, re-encoded for the A/I hex).
//
// The JVM coverage engine is Jazzer — see FuzzProbe.kt.
package crucible

import message.Probe
import org.sofabuffers.sofab.DecodeStatus
import org.sofabuffers.sofab.FlushSink
import org.sofabuffers.sofab.OStream
import org.sofabuffers.sofab.SofabError
import org.sofabuffers.sofab.SofabException

// Materialized value dump mode (oracle/materialized.md): when SOFAB_MATERIALIZE=1,
// an A (COMPLETE) decode emits a full walk of the decoded value instead of the
// re-encoded wire hex. I/R/L and the default (env unset) path are unchanged.
private val MATERIALIZE = Io.env("SOFAB_MATERIALIZE") == "1"

// ---- the streaming axes (drivers/common/CONTRACT.md) ------------------------
//
// The replay protocol hands each record over whole and re-encodes it with one call,
// so neither streaming surface of the generated API is reachable through it. Unset,
// every variable below is today's behaviour byte for byte.
//
// The generated Kotlin Decoder DOES expose `status`, so the verdict comes from there
// rather than from finish() — finish() throws IllegalStateException when the stream
// ended mid-field, and routing the verdict through it would bake that into the
// canonical line.
private fun envInt(name: String): Int = Io.env(name)?.toIntOrNull() ?: 0

private val SPLIT = envInt("SOFAB_SPLIT")
private val CHUNK = envInt("SOFAB_CHUNK")
private val FLUSH = envInt("SOFAB_FLUSH")
private val SCRUB = Io.env("SOFAB_CHUNK_SCRUB").let { it != null && it.isNotEmpty() && it != "0" }
private val ENCODE = Io.env("SOFAB_ENCODE").let { if (it.isNullOrEmpty()) "new" else it }
private val CHUNKING = SPLIT != 0 || CHUNK != 0 || SCRUB

/** How the record is cut on its way in. Never an empty chunk; a 0-byte record
 *  yields none at all. Each chunk is a fresh copy this driver owns, which is what
 *  makes SOFAB_CHUNK_SCRUB able to say anything. */
private fun chunksOf(data: ByteArray): List<ByteArray> {
    val out = ArrayList<ByteArray>()
    val len = data.size
    if (len == 0) return out
    if (CHUNK > 0) {
        var o = 0
        while (o < len) {
            val n = if (CHUNK < len - o) CHUNK else len - o
            out.add(data.copyOfRange(o, o + n))
            o += n
        }
        return out
    }
    if (SPLIT > 0 && SPLIT < len) {
        out.add(data.copyOfRange(0, SPLIT))
        out.add(data.copyOfRange(SPLIT, len))
        return out
    }
    out.add(data.copyOf())
    return out
}

/** Growable byte sink for the two buffered encode surfaces: the OStream hands its
 *  buffer over here every time it fills, and §5.1 says a sink that returns without
 *  installing a replacement has COPIED — which is exactly what this does. */
private class ByteAcc {
    private var buf = ByteArray(256)
    private var n = 0

    fun append(data: ByteArray, off: Int, len: Int) {
        if (n + len > buf.size) {
            var cap = buf.size * 2
            while (cap < n + len) cap *= 2
            buf = buf.copyOf(cap)
        }
        data.copyInto(buf, n, off, off + len)
        n += len
    }

    fun toByteArray(): ByteArray = buf.copyOf(n)
}

/** Re-encode through the surface SOFAB_ENCODE selects. All three must emit
 *  identical bytes, and SOFAB_FLUSH must not change them either: it gives the
 *  OStream an n-byte buffer draining to a sink, so the encoder crosses a buffer
 *  boundary at every offset. corelib-kotlin-mp declares MIN_OUTPUT_BUFFER = 1
 *  (Sofab.MIN_OUTPUT_BUFFER), so every swept size is one it accepts. */
private fun encodeVia(m: Probe): ByteArray {
    if (ENCODE == "new") return m.encode()
    val cap = if (FLUSH > 0) FLUSH else Probe.MAX_SIZE
    val acc = ByteAcc()
    val os = OStream(ByteArray(cap), 0, FlushSink { data, off, len -> acc.append(data, off, len) })
    if (ENCODE == "to") {
        m.encodeTo(os) // serialize + flush, per the generated doc
    } else {
        m.serialize(os)
        os.flush()
    }
    return acc.toByteArray()
}

private fun rejectClass(e: SofabException): String = when (e.error) {
    // corelib-kotlin-mp carries the canonical category on the exception itself
    // (SofabError), so branch on it rather than string-matching messages. Its
    // SofabError has no USAGE member — CORELIB_PLAN §6.3 abolished that class.
    SofabError.ARGUMENT -> "argument"
    SofabError.BUFFER_FULL -> "buffer_full"
    else -> "invalid_msg"
}

// LIMIT_EXCEEDED (generator#102, limit mode only) is a policy rejection distinct
// from INVALID and gets its own verdict `L`; everything else is an `R <class>`.
private fun errLine(e: SofabException): String =
    if (e.error == SofabError.LIMIT_EXCEEDED) "L" else "R " + rejectClass(e)

private const val HEX = "0123456789abcdef"

private fun hexValue(verdict: Char, m: Probe): String {
    // Value for an A (COMPLETE) or I (INCOMPLETE) line: re-encode the decoded
    // message -> hex (oracle/canonical.md). For I this is the partial value filled
    // before truncation (the `incomplete_value` axis is soft; the verdict is hard).
    val enc: ByteArray = try {
        encodeVia(m)
    } catch (e: SofabException) {
        // encode failed after tryDecode reported A/I — should not happen given a
        // worst-case buffer; report it as a reject class rather than crashing.
        return errLine(e)
    } catch (e: RuntimeException) {
        val c = e.cause
        if (c is SofabException) return errLine(c)
        return "R other"
    }
    val sb = StringBuilder(2 + enc.size * 2)
    sb.append(verdict).append(' ')
    for (b in enc) {
        val v = b.toInt() and 0xff
        sb.append(HEX[v ushr 4]).append(HEX[v and 0xf])
    }
    return sb.toString()
}

private fun canonical(data: ByteArray): String {
    // One pass: tryDecode fills `m` and returns the corelib's real three-valued
    // outcome (or throws SofabException on malformed input, MESSAGE_SPEC §7).
    var m = Probe()
    val status: DecodeStatus
    try {
        if (CHUNKING) {
            // Chunked decode via the generated Decoder, taken ONLY when a chunking
            // variable is set — the default stays the one-shot tryDecode byte for
            // byte, which is also what makes the gate meaningful: it then compares
            // two genuinely different code paths. The verdict comes from `status`,
            // never from finish(), which throws mid-field (CONTRACT.md).
            val d = Probe.decoder()
            for (c in chunksOf(data)) {
                d.feed(c)
                // Scrub: the chunk is a copy the driver owns, so overwriting it
                // after feed exposes a decoder that borrowed instead of copying.
                if (SCRUB) c.fill(0xA5.toByte())
            }
            status = d.status
            m = d.message
        } else {
            status = Probe.tryDecode(data, m)
        }
    } catch (e: SofabException) {
        return errLine(e)
    } catch (e: RuntimeException) {
        // A rejection raised from inside the visitor can arrive wrapped; unwrap to
        // preserve the L/R distinction. A genuinely foreign RuntimeException still
        // falls through to "R other".
        val c = e.cause
        if (c is SofabException) return errLine(c)
        return "R other"
    }
    // INCOMPLETE (MESSAGE_SPEC §7): bytes end mid-message — the third canonical
    // verdict, neither accept (A) nor reject (R). Not an error. COMPLETE emits A.
    val verdict = if (status == DecodeStatus.INCOMPLETE) 'I' else 'A'
    // Materialized mode replaces only the A payload with the decoded-value dump
    // (oracle/materialized.md); I keeps the round-trip hex of its partial value.
    if (verdict == 'A' && MATERIALIZE) return "A " + materialize(m)
    return hexValue(verdict, m)
}

/** Announce the resolved streaming configuration on stderr (never parsed).
 *  A driver that silently ignored these would be indistinguishable from one that
 *  honours them — stdout is identical either way — so this is what makes "it really
 *  re-feeds" checkable rather than asserted. */
private fun announce() {
    if (ENCODE != "new" && ENCODE != "to" && ENCODE != "stream") {
        Io.err("crucible-kotlin: unknown SOFAB_ENCODE=$ENCODE (this backend has new, to, stream)")
        Io.exit(2)
    }
    if (SPLIT != 0 || CHUNK != 0 || SCRUB || FLUSH != 0 || ENCODE != "new") {
        Io.err(
            "crucible-kotlin: streaming cfg split=$SPLIT chunk=$CHUNK" +
                " scrub=" + (if (SCRUB) 1 else 0) + " enc=$ENCODE flush=$FLUSH",
        )
    }
}

/** The replay front-end: frame stdin into records, emit one canonical line each.
 *  Reads the whole framed stream before emitting (the comparator writes all inputs
 *  then reads all output — the drivers/ts and drivers/dart pattern), which also
 *  keeps this loop free of any per-target stream API. */
fun runDriver() {
    announce()
    val input = Io.readStdin()
    val out = StringBuilder()
    var p = 0
    while (p < input.size) {
        if (input.size - p < 4) {
            Io.err("crucible-kotlin: short length prefix")
            Io.exit(1)
        }
        val n = (input[p].toInt() and 0xff) or
            ((input[p + 1].toInt() and 0xff) shl 8) or
            ((input[p + 2].toInt() and 0xff) shl 16) or
            ((input[p + 3].toInt() and 0xff) shl 24)
        p += 4
        if (n < 0 || input.size - p < n) {
            Io.err("crucible-kotlin: short payload")
            Io.exit(1)
        }
        val data = input.copyOfRange(p, p + n)
        p += n
        out.append(canonical(data)).append('\n')
    }
    Io.out(out.toString())
}
