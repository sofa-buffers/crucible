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
from sofab import (Decoder, Encoder, SofaError, SofaIncompleteError,
                   SofaLimitError)

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
    if kind == "struct_wrapper":
        # a wrapper whose elements are struct sequences (WP-05): each element is a
        # generated object — an obj walk per element, container length as-is
        return "[" + ",".join(
            "{" + ";".join(
                f"{c['id']}:{_walk(c, getattr(e, c['name']))}" for c in node["fields"]
            ) + "}" for e in value
        ) + "]"
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


# ---- the streaming axes (drivers/common/CONTRACT.md) --------------------------
#
# The replay protocol hands each record over whole and re-encodes it with one call,
# so neither streaming surface of the generated API is reachable through it. Unset,
# every variable below is today's behaviour byte for byte.
#
# Python is the one PULL-shaped backend: there is no push `feed`. `Probe.decode(data)`
# is `deserialize(Decoder(io.BytesIO(data)))`, so the driver expresses chunking by
# handing the Decoder a reader that returns SHORT READS — at most `n` bytes per call.
# That is faithful rather than a workaround: the Decoder's `_need` loop treats a short
# read as "more to come" and only an empty return as end-of-input, which is exactly the
# distinction the axis is about. `chunk_size` is set to match so each refill asks for
# the same small amount.
#
# There is no push decoder to expose a `status`, so the verdict comes from the same
# exceptions the one-shot path raises — which is the contract's rule (derive it the way
# the one-shot path does), not an exception to it.
def _env_int(name: str) -> int:
    v = os.environ.get(name, "")
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


_SPLIT = _env_int("SOFAB_SPLIT")
_CHUNK = _env_int("SOFAB_CHUNK")
_FLUSH = _env_int("SOFAB_FLUSH")
_SCRUB = os.environ.get("SOFAB_CHUNK_SCRUB", "") not in ("", "0")
_ENCODE = os.environ.get("SOFAB_ENCODE", "") or "new"
_CHUNKING = bool(_SPLIT or _CHUNK)


def _check_cfg() -> None:
    if _SCRUB:
        # Not applicable, and for the opposite reason to corelib-zig's: this runtime
        # cannot alias a fed chunk at all. `read()` returns immutable `bytes` and the
        # Decoder copies them into its own buffer on arrival, so there is no borrow to
        # expose by overwriting. Exit 3 says "cannot be tested here" — never "passed".
        sys.stderr.write(
            "crucible-py: SOFAB_CHUNK_SCRUB is not applicable — the pull Decoder reads "
            "immutable bytes and copies them on arrival, so no borrow is observable\n")
        sys.exit(3)
    if _ENCODE == "to":
        sys.stderr.write("crucible-py: SOFAB_ENCODE=to — this backend has no encodeTo "
                         "(it has new, stream)\n")
        sys.exit(2)
    if _ENCODE not in ("new", "stream"):
        sys.stderr.write(f"crucible-py: unknown SOFAB_ENCODE={_ENCODE} "
                         "(this backend has new, stream)\n")
        sys.exit(2)
    # Announce on stderr (never parsed). A driver that silently ignored these would be
    # indistinguishable from one that honours them — stdout is identical either way.
    if _SPLIT or _CHUNK or _FLUSH or _ENCODE != "new":
        sys.stderr.write(f"crucible-py: streaming cfg split={_SPLIT} chunk={_CHUNK} "
                         f"enc={_ENCODE} flush={_FLUSH}\n")


class _ChunkedReader:
    """A reader that hands the Decoder the record in pieces.

    `SOFAB_CHUNK=n` caps every read at n bytes; `SOFAB_SPLIT=k` gives k bytes first and
    the rest afterwards. An empty return means end-of-input and nothing else, so a
    short read is never mistaken for truncation.
    """

    def __init__(self, data: bytes) -> None:
        self._d = data
        self._pos = 0
        self._first = True

    def read(self, n: int) -> bytes:
        if self._pos >= len(self._d):
            return b""
        if _CHUNK > 0:
            take = min(n, _CHUNK)
        elif _SPLIT > 0 and self._first:
            take = min(n, _SPLIT)
        else:
            take = n
        self._first = False
        out = self._d[self._pos:self._pos + take]
        self._pos += len(out)
        return out


def _decode_streamed(data: bytes) -> Probe:
    o = Probe()
    size = _CHUNK if _CHUNK > 0 else (_SPLIT if _SPLIT > 0 else 65536)
    o.deserialize(Decoder(_ChunkedReader(data), chunk_size=max(size, 1)))
    return o


def _encode_via(m: Probe) -> bytes:
    """Re-encode through the surface SOFAB_ENCODE selects.

    Both must emit identical bytes, and SOFAB_FLUSH must not change them either: it
    puts the encoder over a fixed n-byte caller buffer whose flush sink drains it and
    hands back a fresh one, so the encoder crosses a buffer boundary at every offset.
    """
    if _ENCODE == "new":
        return m.encode()
    if _FLUSH <= 0:
        e = Encoder()
        m.serialize(e)
        return e.getvalue()
    acc = bytearray()
    enc: Encoder

    def sink(chunk: bytes) -> None:
        acc.extend(chunk)
        enc.buffer_set(bytearray(_FLUSH))

    enc = Encoder.over_buffer(bytearray(_FLUSH), 0, sink)
    m.serialize(enc)
    enc.flush()
    return bytes(acc)


def canonical(data: bytes) -> str:
    # decode -> re-encode -> hex (oracle/canonical.md).
    try:
        # The chunked path is taken ONLY when a chunking variable is set, so the
        # default stays the one-shot Probe.decode byte for byte.
        m = _decode_streamed(data) if _CHUNKING else Probe.decode(data)
        b = _encode_via(m)
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
    _check_cfg()
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
