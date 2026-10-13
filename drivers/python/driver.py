#!/usr/bin/env python3
"""Crucible Python driver — persistent replay front-end for the differential loop.

One driver, two modes, chosen by the SOFAB_PUREPYTHON env var the wrapper sets
(build.sh emits one wrapper per mode):
  - py-cython : SOFAB_PUREPYTHON=0 -> the compiled Cython accelerator (sofab._speedups)
  - py-pure   : SOFAB_PUREPYTHON=1 -> the pure-Python fallback engine

Both must be byte-for-byte identical (corelib-py asserts this in its own parity
tests); Crucible checks it against the other language corelibs too.

Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin, emits
one canonical line (oracle/canonical.md) per record. The one-shot verdict is
whatever the generated `Probe.decode` raises; the chunked one is the status the
generated `Probe.decoder()`'s `feed` returns.
"""
import json
import os
import struct
import sys

from message import Probe
from sofab import (Encoder, SofaArgumentError, SofaBufferError, SofaDecodeError,
                   SofaIncompleteError, SofaLimitError, Status)

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
# enum / bitfield arrive as IntEnum / IntFlag: int() hands over the plain integer
# (also for values outside the named members), printed like `s` / `u`.
def _enum(v): return f"s{int(v)}"
def _bits(v): return f"u{int(v)}"

_LEAF = {"u": _u, "bool": _bool, "s": _s, "fp32": _f32, "fp64": _f64,
         "string": _t, "blob": _b, "enum": _enum, "bitfield": _bits}


def _load_schema():
    path = os.environ.get("SOFAB_MATERIALIZE_SCHEMA") or "oracle/materialized-schema.json"
    with open(path) as fh:
        return json.load(fh)


def _attr(obj, name):
    # the generated dataclass suffixes a field name that shadows a builtin (`list` -> `list_`)
    return getattr(obj, name if hasattr(obj, name) else name + "_")


_SCHEMA = _load_schema() if _MATERIALIZE else None


def _walk(node, value) -> str:
    """One descriptor node + the decoded value at that node -> its materialized string.
    struct recurses over child fields; array/wrapper join their in-memory elements
    (already length N for arrays, index-ordered for wrappers); a leaf formats value."""
    kind = node["kind"]
    if kind == "struct":
        return "{" + ";".join(
            f"{c['id']}:{_walk(c, _attr(value, c['name']))}" for c in node["fields"]
        ) + "}"
    if kind == "union":
        # A union holds exactly ONE option: walk the one the tag names (the public
        # `which`), never by testing each option for a non-default value — a held option
        # at its own default is still held ({4:u0}, not {0:u0}).
        o = next(o for o in node["options"] if o["id"] == value.which)
        return "{" + f"{o['id']}:{_walk(o, _attr(value, o['name']))}" + "}"
    if kind == "struct_wrapper":
        # a wrapper whose elements are struct sequences (WP-05): each element is a
        # generated object — an obj walk per element, container length as-is
        return "[" + ",".join(
            "{" + ";".join(
                f"{c['id']}:{_walk(c, _attr(e, c['name']))}" for c in node["fields"]
            ) + "}" for e in value
        ) + "]"
    if kind == "node_wrapper":
        # dynamic array whose elements are walked through `item` (a union, or another
        # node_wrapper); the container's own length, nothing padded to `count`
        return "[" + ",".join(_walk(node["item"], e) for e in value) + "]"
    if kind == "array" or kind == "wrapper":
        enc = _LEAF[node["elem"]]
        return "[" + ",".join(enc(x) for x in value) + "]"
    return _LEAF[kind](value)


def _materialize(m) -> str:
    # The top message is a struct-like list of fields; value = the decoded Probe.
    return "{" + ";".join(
        f"{f['id']}:{_walk(f, _attr(m, f['name']))}" for f in _SCHEMA["fields"]
    ) + "}"

# Corelib exception -> the canonical failure class (oracle/canonical.md), shared by the
# decode reject `R <class>` and the re-encode refusal `E <class>`. isinstance against the
# imported classes, never a table of class NAMES: corelib-py keeps deprecated aliases
# (`SofaRangeError = SofaArgumentError`, `SofaStateError` likewise), and a name table
# over aliases is what went stale here before. Anything else — another SofaError, or a
# non-corelib failure — is `other`: surfaced, never folded into a class it is not.
def _fail_class(e: Exception) -> str:
    if isinstance(e, SofaDecodeError):
        return "invalid_msg"
    if isinstance(e, SofaArgumentError):
        return "argument"
    if isinstance(e, SofaBufferError):
        return "buffer_full"
    return "other"


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
# The chunked verdict is the status the last `feed` returned, mapped the way
# CONTRACT.md "Deriving the verdict" says; only a receiver cap still arrives as an
# exception, because the generated decoder raises it (SofaLimitError).
def _env_int(name: str) -> int:
    v = os.environ.get(name, "")
    try:
        return int(v) if v else 0
    except ValueError:
        return 0


_SPLIT = _env_int("SOFAB_SPLIT")
_CHUNK = _env_int("SOFAB_CHUNK")
_FLUSH = _env_int("SOFAB_FLUSH")
# SOFAB_ENCODE_FAIL=n: the destination handed to the encoder takes n bytes.
_FAIL = _env_int("SOFAB_ENCODE_FAIL")
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
    if _SPLIT or _CHUNK or _FLUSH or _SCRUB or _ENCODE != "new" or _FAIL:
        sys.stderr.write(f"crucible-py: streaming cfg split={_SPLIT} chunk={_CHUNK} "
                         f"scrub={1 if _SCRUB else 0} enc={_ENCODE} flush={_FLUSH} "
                         f"fail={_FAIL}\n")


def _chunks(data: bytes) -> list:
    """The record cut the way drivers/common/CONTRACT.md says, piece by piece.

    `SOFAB_CHUNK=n` gives fixed-size pieces (the last one short); `SOFAB_SPLIT=k` gives
    exactly two, `[0,k)` and `[k,end)`; an empty record gives ONE empty piece, so the
    empty message goes through the decoder like any other record.

    Each piece is a `bytearray` this driver owns, so `SOFAB_CHUNK_SCRUB` has a mutable
    buffer to overwrite once `feed` has returned.
    """
    if _CHUNK > 0 and data:
        return [bytearray(data[o:o + _CHUNK]) for o in range(0, len(data), _CHUNK)]
    if 0 < _SPLIT < len(data):
        return [bytearray(data[:_SPLIT]), bytearray(data[_SPLIT:])]
    return [bytearray(data)]


def _decode_streamed(data: bytes):
    """Feed the record in pieces; return (status of the last feed, decoded message).

    `INVALID` is terminal (§5.2.1) — every later `feed` returns it again without
    consuming anything — so feeding stops at the first one rather than pushing bytes at
    a decoder that is already done. There is always at least one piece, so `st` is
    always a status `feed` returned.
    """
    d = Probe.decoder()
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
    return st, d.message


def _encode_via(m: Probe) -> bytes:
    """Re-encode through the surface SOFAB_ENCODE selects.

    Both must emit identical bytes, and SOFAB_FLUSH must not change them either: it
    puts the encoder over a fixed n-byte caller buffer whose flush sink drains it and
    hands back a fresh one, so the encoder crosses a buffer boundary at every offset.
    """
    # SOFAB_ENCODE_FAIL=n (CONTRACT.md): a destination of n bytes with NO sink, so a
    # message that does not fit is REFUSED (SofaBufferError) rather than truncated, and
    # the `E` mapping in canonical() runs for real — from the wire that branch is
    # unreachable, because every value re-encoded here came out of this driver's own
    # decoder and is in-bounds by construction.
    if _FAIL > 0:
        buf = bytearray(_FAIL)
        e = Encoder.over_buffer(buf, 0)
        m.serialize(e)
        # `bytes_used()` is a CALL, as the generated encode() spells it — a property
        # here would slice the buffer with a bound method and raise TypeError, which
        # the `E` mapping would then report as `E other` on a message that encodes
        # perfectly well. The gate caught exactly that on the first run.
        return bytes(memoryview(buf)[: e.bytes_used()])
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


def _encode_refusal(e: Exception) -> str:
    """The `E <class>` line for a RE-ENCODE that was refused (oracle/canonical.md).

    Since generator#656 the generated `serialize` refuses a value past a declared
    bound — a string/blob over `maxlen`, an array over `count`, an integer, enum or
    bitfield outside its declared width — with `SofaArgumentError`, §6.3's
    `InvalidArgument`. That is not a statement about the input: the decode above
    accepted it. Reporting it as `R` would say the bytes were malformed, which is
    the one thing that did not happen.
    """
    return "E " + _fail_class(e)


def canonical(data: bytes) -> str:
    # decode -> re-encode -> hex (oracle/canonical.md).
    try:
        # The chunked path is taken ONLY when a chunking variable is set, so the
        # default stays the one-shot Probe.decode byte for byte.
        if _CHUNKING:
            st, m = _decode_streamed(data)
        else:
            st, m = Status.COMPLETE, Probe.decode(data)
    except SofaIncompleteError:
        # §7 INCOMPLETE (one-shot): decode ended mid-message (truncation) — not an
        # error and not malformed, so it is neither "A" nor "R". SofaIncompleteError
        # is a sibling of SofaDecodeError under SofaError, so this clause MUST
        # precede the generic handler below.
        return "I"
    except SofaLimitError:
        # LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
        # cap on a schema-unbounded field. A policy rejection distinct from INVALID —
        # its own verdict `L`, not `R`. Sibling of SofaDecodeError under SofaError, so
        # this clause MUST precede the generic handler below.
        return "L"
    except Exception as e:
        return "R " + _fail_class(e)
    # The chunked path's status (the one-shot path only gets here on COMPLETE).
    if st is Status.INVALID:
        return "R invalid_msg"
    if st is Status.INCOMPLETE:
        return "I"
    if _MATERIALIZE:
        return "A " + _materialize(m)
    # The re-encode is a SEPARATE try: its failure is an encode fact (`E`), never one
    # of the decode verdicts above. Folding both into one try is what made a refusal
    # read as `R invalid_msg` here.
    try:
        b = _encode_via(m)
    except Exception as e:
        return _encode_refusal(e)
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
