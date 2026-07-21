#!/usr/bin/env python3
"""Materialized-value reference — the ground truth for the element-access oracle
(oracle/materialized.md).

Given a `gen.py` message dict (the same value model the cross-encode corpus is built
from), produce the exact materialized-form dump a *correct* driver must emit under
`SOFAB_MATERIALIZE=1` after decoding that message's wire. Every driver's dump is
validated byte-for-byte against this reference.

It models the decoded value, not the source dict — i.e. `decode(encode(msg))`:
  * a numeric / fp array is materialized to its full schema `count` N (fill-to-N,
    MESSAGE_SPEC §5.1) — trailing defaults included, since the in-memory value keeps
    them (only the *wire* elides them);
  * a wrapper array (`string_array` / `blob_array`) is grown to highest-populated
    index + 1 (the wire omits default/empty elements, so the container's in-memory
    length is max-present-index + 1, with any interior gaps as empty elements);
  * a scalar / fp / string / blob is its value or the type default.

Usage: python3 engine/structured/materialize.py            # dump every gen.py vector
       python3 engine/structured/materialize.py --check DIR # compare a driver's
                                                            # SOFAB_MATERIALIZE output in DIR
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import SCALARS, NUM_ARRAYS, vectors  # noqa: E402

ARR_COUNT = 5   # schema count for every array/wrapper in schema/probe.sofab.yaml


# --- value encoders (one per materialized-form leaf) -------------------------
def _u(v):    return f"u{v}"
def _s(v):    return f"s{v}"
def _f32(x):  return "f%08x" % struct.unpack("<I", struct.pack("<f", x))[0]
def _f64(x):  return "F%016x" % struct.unpack("<Q", struct.pack("<d", x))[0]
def _text(s): b = s.encode("utf-8"); return f"t{len(b)}:{b.hex()}"
def _blob(b): return f"b{len(b)}:{b.hex()}"
def _obj(fields): return "{" + ";".join(f"{i}:{v}" for i, v in fields) + "}"
def _arr(vals):   return "[" + ",".join(vals) + "]"


def _num_array(vals, signed):
    """A fixed-count numeric array, materialized to N with the type default (0)."""
    padded = list(vals) + [0] * (ARR_COUNT - len(vals))
    enc = _s if signed else _u
    return _arr([enc(v) for v in padded[:ARR_COUNT]])


def _fp_array(vals, enc):
    padded = list(vals) + [0.0] * (ARR_COUNT - len(vals))
    return _arr([enc(v) for v in padded[:ARR_COUNT]])


def _scalar_fp(v):
    """A scalar fp *field* (not an array element) is omitted on the wire when it
    equals its default — and -0.0 is falsy, so it is omitted too and decodes to +0.0
    (mirrors gen.py's emit condition; the round-trip can't distinguish ±0.0 either,
    canonical.md §Tradeoff). A nonzero value, ±inf, or NaN is emitted and preserved.
    Array *elements* are always emitted explicitly, so they are NOT normalized here."""
    if v or (v != v) or v in (float("inf"), float("-inf")):
        return v
    return 0.0


def _wrapper(items, leaf, empty):
    """A wrapper array (string_array/blob_array). The wire omits empty (default)
    elements, so the decoded container length is highest-non-empty-index + 1, and any
    interior omitted element materializes as the type's empty value."""
    present = [i for i, v in enumerate(items) if v]
    if not present:
        return _arr([])
    length = max(present) + 1
    out = []
    for i in range(length):
        v = items[i] if i < len(items) else empty
        out.append(leaf(v if v else empty))
    return _arr(out)


def materialize(msg):
    """Return the materialized-form value string (no 'A ' prefix) for a gen.py msg."""
    # top-level scalars (ids 0..7)
    fields = []
    for name, fid, signed in SCALARS:
        v = msg.get(name, 0)
        fields.append((fid, (_s if signed else _u)(v)))

    # nested struct (id 10): f32(0) f64(1) str(2) blob(3)
    nested = _obj([
        (0, _f32(_scalar_fp(msg.get("f32", 0.0)))),
        (1, _f64(_scalar_fp(msg.get("f64", 0.0)))),
        (2, _text(msg.get("str", ""))),
        (3, _blob(msg.get("blob", b""))),
    ])
    fields.append((10, nested))

    # arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10)
    arr_fields = []
    for name, fid, signed in NUM_ARRAYS:
        arr_fields.append((fid, _num_array(msg.get(name, []), signed)))
    arr_nested = _obj([
        (0, _fp_array(msg.get("afp32", []), _f32)),
        (1, _fp_array(msg.get("afp64", []), _f64)),
    ])
    arr_fields.append((10, arr_nested))
    fields.append((100, _obj(arr_fields)))

    # wrapper arrays: string_array (id 200), blob_array (id 201)
    fields.append((200, _wrapper(msg.get("strarr", []), _text, "")))
    fields.append((201, _wrapper(msg.get("blobarr", []), _blob, b"")))

    return _obj(fields)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        _check(sys.argv[2])
        return
    for i, (name, msg) in enumerate(vectors()):
        print(f"{i:03d}_{name}\tA {materialize(msg)}")


def _check(driver_out_dir):
    """Compare a driver's SOFAB_MATERIALIZE dump (one file `NNN_name` per vector,
    holding its `A <dump>` line) against the reference. Reports mismatches."""
    bad = 0
    for i, (name, msg) in enumerate(vectors()):
        expected = "A " + materialize(msg)
        path = os.path.join(driver_out_dir, f"{i:03d}_{name}")
        if not os.path.exists(path):
            print(f"MISSING {i:03d}_{name}"); bad += 1; continue
        got = open(path).read().strip()
        if got != expected:
            print(f"MISMATCH {i:03d}_{name}\n  ref: {expected}\n  got: {got}"); bad += 1
    print(f"\n{'OK' if not bad else 'FAIL'}: {bad} mismatch(es) of {len(vectors())} vectors")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
