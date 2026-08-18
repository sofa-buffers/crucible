// Crucible Kotlin driver — the JVM target's IO shim (drivers/kotlin/driver.kt).
//
// One of the io_<target>.kt files, exactly one of which build.sh compiles next to
// the shared driver. It supplies the three things common Kotlin has no API for —
// the environment, binary stdin, stdout — plus `main`, so the shared core stays
// target-agnostic.
//
// The JVM leg runs corelib-kotlin-mp's `jvm` target: the same commonMain codec,
// with byte-array VarHandles as the little-endian word access (`Mem.jvm.kt`).
// @file:JvmName pins the class the wrapper launches: without it a top-level `main`
// lands in `Io_jvmKt`, a name that would change with the file's.
@file:JvmName("Driver")

package crucible

import java.io.DataInputStream

internal object Io {
    fun env(name: String): String? = System.getenv(name)

    /** The whole framed input stream. `readAllBytes` on the raw stdin stream can
     *  return short on a pipe, so it is read to EOF explicitly. */
    fun readStdin(): ByteArray {
        val buf = java.io.ByteArrayOutputStream()
        val chunk = ByteArray(1 shl 16)
        val ins = DataInputStream(System.`in`)
        while (true) {
            val r = ins.read(chunk)
            if (r < 0) break
            buf.write(chunk, 0, r)
        }
        return buf.toByteArray()
    }

    fun out(s: String) {
        System.out.write(s.toByteArray(Charsets.UTF_8))
        System.out.flush()
    }

    fun err(s: String) = System.err.println(s)

    fun exit(code: Int): Nothing = kotlin.system.exitProcess(code)
}

fun main() = runDriver()
