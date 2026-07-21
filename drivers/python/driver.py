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
import os
import struct
import sys

from message import Probe
from sofab import SofaError, SofaIncompleteError, SofaLimitError

# --- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 -------
# The dataclass carries no schema type (fp32 vs fp64, unsigned vs signed), so this
# walker holds a small schema-type table. Prototype: the C driver's descriptor walk
# is schema-agnostic; a generated table would make the dynamically-typed drivers so
# too. fp32 is repacked through <f to recover its 32-bit pattern from the double it
# was decoded into (the NaN-payload caveat in canonical.md applies).
_MATERIALIZE = os.environ.get("SOFAB_MATERIALIZE") == "1"
_SCALARS = [(0, "u8", 0), (1, "i8", 1), (2, "u16", 0), (3, "i16", 1),
            (4, "u32", 0), (5, "i32", 1), (6, "u64", 0), (7, "i64", 1)]


def _u(v):  return f"u{v}"
def _s(v):  return f"s{v}"
def _f32(x): return "f%08x" % struct.unpack("<I", struct.pack("<f", x))[0]
def _f64(x): return "F%016x" % struct.unpack("<Q", struct.pack("<d", x))[0]
def _t(s):  b = s.encode("utf-8"); return f"t{len(b)}:{b.hex()}"
def _b(bb): bb = bytes(bb); return f"b{len(bb)}:{bb.hex()}"
def _arr(v): return "[" + ",".join(v) + "]"


def _materialize(m) -> str:
    f = [f"{fid}:{(_s if sg else _u)(getattr(m, a))}" for fid, a, sg in _SCALARS]
    n = m.nested
    f.append("10:{" + ";".join([f"0:{_f32(n.f32)}", f"1:{_f64(n.f64)}",
                                 f"2:{_t(n.str)}", f"3:{_b(n.bytes_field)}"]) + "}")
    a = m.arrays
    af = [f"{fid}:" + _arr([(_s if sg else _u)(x) for x in getattr(a, at)])
          for fid, at, sg in _SCALARS]
    af.append("10:{" + ";".join(["0:" + _arr([_f32(x) for x in a.nested.fp32]),
                                  "1:" + _arr([_f64(x) for x in a.nested.fp64])]) + "}")
    f.append("100:{" + ";".join(af) + "}")
    f.append("200:" + _arr([_t(s) for s in m.string_array]))
    f.append("201:" + _arr([_b(bb) for bb in m.blob_array]))
    return "{" + ";".join(f) + "}"

_CLASS = {
    "SofaDecodeError": "invalid_msg",
    "SofaRangeError": "argument",
    "SofaStateError": "usage",
    "SofaBufferError": "buffer_full",
}


def _reject(e: Exception) -> str:
    if isinstance(e, SofaError):
        return "R " + _CLASS.get(type(e).__name__, "invalid_msg")
    # Any non-SofaError failure is surfaced (not hidden) so a divergence in
    # failure mode still shows up rather than masquerading.
    return "R other"


def canonical(data: bytes) -> str:
    # decode -> re-encode -> hex (oracle/canonical.md).
    try:
        m = Probe.decode(data)
        b = m.encode()
    except SofaIncompleteError:
        # §7 INCOMPLETE: decode ended mid-message (truncation) — not an error and
        # not malformed, so it is neither "A" nor "R". SofaIncompleteError is a
        # sibling of SofaDecodeError under SofaError, so this clause MUST precede
        # the generic handler below or _reject would mislabel it "R invalid_msg".
        return "I"
    except SofaLimitError:
        # LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
        # cap on a schema-unbounded field. A policy rejection distinct from INVALID —
        # its own verdict `L`, not `R`. Sibling of SofaDecodeError under SofaError, so
        # this clause MUST precede the generic handler below.
        return "L"
    except Exception as e:
        return _reject(e)
    if _MATERIALIZE:
        return "A " + _materialize(m)
    return "A " + b.hex()


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
