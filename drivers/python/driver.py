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
from sofab import (Encoder, SofaDecodeError, SofaError, SofaIncompleteError,
                   SofaLimitError, Status)

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
# `_bool` is int(), not `1 if v else 0`, on purpose: int(True) is 1 and int(False) is 0,
# so a native bool renders as u1/u0 — while a port that kept the RAW wire value (a
# non-normalized `2`) renders `u2`, which is the divergence this form exists to surface.
def _bool(v): return f"u{int(v)}"

_LEAF = {"u": _u, "bool": _bool, "s": _s, "fp32": _f32, "fp64": _f64,
         "string": _t, "blob": _b}


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

# Exception class name -> the canonical reject class (oracle/canonical.md).
#
# `SofaStateError` is deliberately absent. corelib-py#96 (merged 2026-08-17) made it a
# deprecated ALIAS of SofaRangeError, so `type(e).__name__` can never spell it again and
# the entry mapping it to "usage" was dead code. Keeping it would also have been wrong in
# the other direction: `usage` is the class CORELIB_PLAN §6.3 abolished, and an alias for
# SofaRangeError is precisely §6.3's `InvalidArgument`, which is `argument` below.
#
# The four type-mismatched reads that used to raise here now return None and skip the
# field (MESSAGE_SPEC §7.3), so they produce no reject class at all — which is why this
# table no longer needs a row for them. `oracle/comparator.py` still rejects the `usage`
# class outright; nothing in the roster can emit it now, and that check is what keeps it
# so rather than something to be removed alongside this.
_CLASS = {
    "SofaDecodeError": "invalid_msg",
    "SofaRangeError": "argument",
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
# corelib-py is a PUSH decoder like every other corelib, and has been since
# corelib-py#142 (2026-09-02, "feed is the only answer; the status property is gone").
# `Probe.decoder()` hands back the generated streaming reader; `feed(chunk)` returns the
# three-valued outcome (CORELIB_PLAN §5.2.1). Before that it was the one pull-shaped
# backend, and this driver expressed chunking by handing the Decoder a reader that
# returned SHORT READS. That reader is gone, and so is the `Decoder(reader, chunk_size=)`
# constructor it needed — `Decoder` is keyword-only now and takes a `visitor`/`binding`.
#
# The verdict still comes from the same exceptions the one-shot path raises, because
# `_decode_streamed` re-raises what `Probe.decode` would have: both paths then answer in
# one currency and `canonical()`'s try/except covers them alike.
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
_CHUNKING = bool(_SPLIT or _CHUNK or _SCRUB)


def _check_cfg() -> None:
    # SOFAB_CHUNK_SCRUB used to exit 3 here ("cannot be tested"), because the pull
    # Decoder was handed immutable `bytes` by a reader and there was no buffer this
    # driver could overwrite. The push `feed` takes any buffer and states the lifetime
    # itself — the chunk is borrowed for the call only — so the axis became testable the
    # moment the surface changed, and `_chunks` now hands over `bytearray`s to scrub.
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
    if _SPLIT or _CHUNK or _FLUSH or _SCRUB or _ENCODE != "new":
        sys.stderr.write(f"crucible-py: streaming cfg split={_SPLIT} chunk={_CHUNK} "
                         f"scrub={1 if _SCRUB else 0} enc={_ENCODE} flush={_FLUSH}\n")


def _chunks(data: bytes) -> list:
    """The record cut the way drivers/common/CONTRACT.md says, piece by piece.

    `SOFAB_CHUNK=n` gives fixed-size pieces (the last one short); `SOFAB_SPLIT=k` gives
    exactly two, `[0,k)` and `[k,end)`; an empty record gives **no** pieces at all — it
    is the valid empty message (MESSAGE_SPEC §2), not something to feed through.

    Each piece is a `bytearray` this driver owns, so `SOFAB_CHUNK_SCRUB` has a mutable
    buffer to overwrite once `feed` has returned.
    """
    if not data:
        return []
    if _CHUNK > 0:
        return [bytearray(data[o:o + _CHUNK]) for o in range(0, len(data), _CHUNK)]
    if 0 < _SPLIT < len(data):
        return [bytearray(data[:_SPLIT]), bytearray(data[_SPLIT:])]
    return [bytearray(data)]


def _decode_streamed(data: bytes) -> Probe:
    """Feed the record in pieces, then answer exactly as `Probe.decode` would.

    `INVALID` is terminal (§5.2.1) — every later `feed` returns it again without
    consuming anything — so feeding stops at the first one rather than pushing bytes at
    a decoder that is already done. A record with no pieces never calls `feed`, and the
    outcome stays COMPLETE: that is the empty message, and it is what the one-shot path
    reports for the same bytes.
    """
    d = Probe.decoder()
    st = Status.COMPLETE
    for c in _chunks(data):
        st = d.feed(c)
        if _SCRUB:
            # feed borrows the chunk for the duration of the call only: whatever the
            # decoder still needs afterwards it copies out before returning (corelib-py
            # `Decoder.feed`, §6 chunk lifetime). Overwriting the piece here is what
            # holds it to that — a decoder that kept a window into the chunk instead
            # reads 0xA5 and the canonical line diverges from the whole-record one.
            c[:] = b"\xa5" * len(c)
        if st is Status.INVALID:
            break
    if st is Status.INVALID:
        raise SofaDecodeError(d.error or "invalid message")
    if st is Status.INCOMPLETE:
        raise SofaIncompleteError(d.error or "truncated message")
    return d.message


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
