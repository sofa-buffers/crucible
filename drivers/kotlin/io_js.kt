// Crucible Kotlin driver — the Kotlin/JS target's IO shim (drivers/kotlin/driver.kt).
//
// One of the io_<target>.kt files, exactly one of which build.sh compiles next to
// the shared driver. It supplies the three things common Kotlin has no API for —
// the environment, binary stdin, stdout — plus `main`, so the shared core stays
// target-agnostic.
//
// The JS leg runs corelib-kotlin-mp's `js(IR)` target on Node. Kotlin/JS has neither
// a native 64-bit integer nor an fp32 value type (`Long` is emulated, `Float` is a
// JS number), so this is the one leg where the codec's 64-bit and fp32 paths run on
// a different representation than on the JVM and LLVM legs.
//
// Node's `fs` is reached through `require`, which a `commonjs` module (build.sh's
// -module-kind) provides. Writes loop: a pipe may take fewer bytes than offered and
// `writeSync` raises EAGAIN when it is momentarily full.
package crucible

private val fs: dynamic = js("require('fs')")
private val proc: dynamic = js("process")

internal object Io {
    fun env(name: String): String? {
        val v: dynamic = proc.env[name]
        return if (v == undefined) null else v as String
    }

    fun readStdin(): ByteArray {
        val buf: dynamic = fs.readFileSync(0)
        // Copy out of Node's pooled Buffer: its backing ArrayBuffer is shared.
        val copy: dynamic = js("new Int8Array(buf.length)")
        js("copy.set(new Int8Array(buf.buffer, buf.byteOffset, buf.length))")
        return copy.unsafeCast<ByteArray>()
    }

    fun out(s: String) {
        val data: dynamic = js("Buffer.from(s, 'utf8')")
        val total = data.length as Int
        var off = 0
        while (off < total) {
            try {
                off += fs.writeSync(1, data, off, total - off) as Int
            } catch (e: dynamic) {
                if (e.code != "EAGAIN") throw e
            }
        }
    }

    fun err(s: String) {
        fs.writeSync(2, s + "\n")
    }

    fun exit(code: Int): Nothing {
        proc.exit(code)
        throw IllegalStateException("process.exit returned")
    }
}

fun main() = runDriver()
