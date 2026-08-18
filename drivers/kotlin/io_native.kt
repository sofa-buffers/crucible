// Crucible Kotlin driver — the Kotlin/Native target's IO shim
// (drivers/kotlin/driver.kt).
//
// One of the io_<target>.kt files, exactly one of which build.sh compiles next to
// the shared driver. It supplies the three things common Kotlin has no API for —
// the environment, binary stdin, stdout — plus `main`, so the shared core stays
// target-agnostic.
//
// The native leg runs corelib-kotlin-mp's `linuxX64` target: the same commonMain
// codec compiled through LLVM to a native ELF, with indexed shifts as the
// little-endian word access (`Mem.native.kt`) rather than the JVM's VarHandles.
// That is the other half of what makes this a multiplatform target rather than a
// second JVM one.
//
// stdin/stdout go through the POSIX read/write syscalls: `readLine`/`print` are
// text APIs and this protocol is binary on the way in. Both loop, because a pipe
// is free to return short in either direction.
@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package crucible

import kotlinx.cinterop.addressOf
import kotlinx.cinterop.toKString
import kotlinx.cinterop.usePinned
import platform.posix.getenv
import platform.posix.read
import platform.posix.write

internal object Io {
    fun env(name: String): String? = getenv(name)?.toKString()

    fun readStdin(): ByteArray {
        var buf = ByteArray(1 shl 16)
        var n = 0
        while (true) {
            if (n == buf.size) buf = buf.copyOf(buf.size * 2)
            val got = buf.usePinned { p ->
                read(0, p.addressOf(n), (buf.size - n).toULong())
            }
            if (got <= 0L) break
            n += got.toInt()
        }
        return buf.copyOf(n)
    }

    fun out(s: String) {
        val bytes = s.encodeToByteArray()
        var off = 0
        while (off < bytes.size) {
            val put = bytes.usePinned { p ->
                write(1, p.addressOf(off), (bytes.size - off).toULong())
            }
            if (put <= 0L) break
            off += put.toInt()
        }
    }

    fun err(s: String) {
        val bytes = (s + "\n").encodeToByteArray()
        bytes.usePinned { p -> write(2, p.addressOf(0), bytes.size.toULong()) }
    }

    fun exit(code: Int): Nothing = kotlin.system.exitProcess(code)
}

fun main() = runDriver()
