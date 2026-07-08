#!/usr/bin/env python3
"""Crucible Python driver — persistent replay front-end for the differential loop.

One driver, two modes, chosen by the SOFAB_PUREPYTHON env var the wrapper sets
(build.sh emits one wrapper per mode):
  - py-cython : SOFAB_PUREPYTHON=0 -> the compiled Cython accelerator (sofab._speedups)
  - py-pure   : SOFAB_PUREPYTHON=1 -> the pure-Python fallback engine

Both must be byte-for-byte identical (corelib-py asserts this in its own parity
tests); Crucible checks it against the other language corelibs too.

Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin, emits
one canonical line (oracle/canonical.md) per record. Unlike Rust/C++, the
generated Python `decode` RAISES on malformed input, so the verdict is a plain
try/except — no two-pass workaround (contrast docs/SOFABGEN.md G-0001/G-0005).
"""
import struct
import sys

from message import Probe
from sofab import SofaError

_CLASS = {
    "SofaDecodeError": "invalid_msg",
    "SofaRangeError": "argument",
    "SofaStateError": "usage",
    "SofaBufferError": "buffer_full",
}


def canonical(data: bytes) -> str:
    try:
        m = Probe.decode(data)
    except SofaError as e:
        return "R " + _CLASS.get(type(e).__name__, "invalid_msg")
    except Exception:
        # Any non-SofaError decode failure is surfaced (not hidden) so a
        # divergence in failure mode still shows up rather than masquerading.
        return "R other"

    fbits = struct.unpack("<I", struct.pack("<f", m.f))[0]
    s_hex = m.s.encode("utf-8").hex()
    return f"A u={m.u} i={m.i} f={fbits:08x} s={s_hex}"


def main() -> int:
    stdin = sys.stdin.buffer
    out = sys.stdout
    while True:
        lenbytes = stdin.read(4)
        if len(lenbytes) == 0:
            break  # clean EOF at record boundary
        if len(lenbytes) != 4:
            sys.stderr.write("crucible-python: short length prefix\n")
            return 1
        n = struct.unpack("<I", lenbytes)[0]
        data = stdin.read(n) if n else b""
        if len(data) != n:
            sys.stderr.write("crucible-python: short payload\n")
            return 1
        out.write(canonical(data) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
