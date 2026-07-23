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
try/except — no two-pass workaround (contrast results/FINDINGS.md G-0001/G-0005).
"""
import json
import os
import struct
import sys

from message import Probe
from sofab import SofaError, SofaIncompleteError, SofaLimitError

# --- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 -------
# The dataclass carries no schema type (fp32 vs fp64, unsigned vs signed), so the
# walker is driven by the GENERATED schema descriptor (engine/structured/schema.py,
# committed to oracle/materialized-schema.json) rather than a hardcoded table — the
# same descriptor walk the C driver and engine/structured/materialize.py use, so a
# schema shape/type change needs no edit here. Only leaf FORMATTING is schema-aware:
# fp32 is repacked through <f to recover its 32-bit pattern from the double it was
# decoded into (the NaN-payload caveat in canonical.md applies).
_MATERIALIZE = os.environ.get("SOFAB_MATERIALIZE") == "1"


def _u(v):  return f"u{v}"
def _s(v):  return f"s{v}"
def _f32(x): return "f%08x" % struct.unpack("<I", struct.pack("<f", x))[0]
def _f64(x): return "F%016x" % struct.unpack("<Q", struct.pack("<d", x))[0]
def _t(s):  b = s.encode("utf-8"); return f"t{len(b)}:{b.hex()}"
def _b(bb): bb = bytes(bb); return f"b{len(bb)}:{bb.hex()}"

# One formatter per materialized-form leaf kind (also the array/wrapper element kind).
_LEAF = {"u": _u, "s": _s, "fp32": _f32, "fp64": _f64, "string": _t, "blob": _b}


def _load_schema():
    path = os.environ.get("SOFAB_MATERIALIZE_SCHEMA") or "oracle/materialized-schema.json"
    with open(path) as fh:
        return json.load(fh)


_SCHEMA = _load_schema() if _MATERIALIZE else None


def _walk(node, value) -> str:
    """One descriptor node + the decoded value at that node -> its materialized string.
    struct recurses over child fields; array/wrapper join their in-memory elements
    (already length N for arrays, index-ordered for wrappers); a leaf formats value."""
    kind = node["kind"]
    if kind == "struct":
        return "{" + ";".join(
            f"{c['id']}:{_walk(c, getattr(value, c['name']))}" for c in node["fields"]
        ) + "}"
    if kind == "array" or kind == "wrapper":
        enc = _LEAF[node["elem"]]
        return "[" + ",".join(enc(x) for x in value) + "]"
    return _LEAF[kind](value)


def _materialize(m) -> str:
    # The top message is a struct-like list of fields; value = the decoded Probe.
    return "{" + ";".join(
        f"{f['id']}:{_walk(f, getattr(m, f['name']))}" for f in _SCHEMA["fields"]
    ) + "}"

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
