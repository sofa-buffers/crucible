#!/usr/bin/env python3
"""Truncation sweep (MESSAGE_SPEC §7 — the finish-less model) — the fifth sweep axis.

§7: decoding is three-valued. A message whose bytes end mid-field, mid-varint, or
with an open sequence is **INCOMPLETE** (`I`) — a first-class non-error, neither
COMPLETE (`A`) nor INVALID (`R`). F-0001 established this at the top level (all 12
emit `I` on a truncated message; corelib-ts once accepted an unterminated nested
sequence as `A`). This sweep generalizes it: take a **structurally rich, valid**
message and truncate it at **every byte offset**, so every field boundary and every
nesting depth (nested struct, arrays struct, arrays.nested, string_array and
blob_array wrappers) is a truncation point.

Two oracles (engine/structured/sweep_run.py):
  * agreement   — at each offset all 12 must emit the SAME verdict. A split
                  (some `A`, some `I`, some `R`) is a finding — F-0001's shape a
                  level deeper (an impl that accepts an unterminated inner sequence,
                  or rejects an incomplete one).
  * conformance — a prefix of a valid message can only be `A` (a complete valid
                  sub-message) or `I` (incomplete); it is **never** `R`, because a
                  valid message contains no malformed construct. So every truncation
                  vector carries `expect="not_reject"`: a verdict of `R` is a
                  conformance failure (an incomplete message mis-classified as
                  invalid — the F-0006/F-0007 precedence bug, at a truncation point).

The full (untruncated) message is included as an `accept` control.

Wire primitives / the reference encoder come from `gen.py`.

Usage: python3 engine/structured/sweep_truncation.py [out_dir]
       (default corpus/truncation-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import encode  # noqa: E402  (the one reference encoder)


def rich_message():
    """A valid probe with every field populated at every depth, so truncating it
    passes through every field boundary and every open-sequence state."""
    return encode({
        "u8": 200, "i8": -50, "u16": 40000, "i16": -20000,
        "u32": 3_000_000_000, "i32": -1_000_000, "u64": 10**18, "i64": -(10**17),
        "f32": 1.5, "f64": 2.5, "str": "hello", "blob": b"\xde\xad\xbe\xef",
        "au8": [1, 2, 3], "ai8": [-1, -2], "au16": [100, 200], "ai16": [-5, 5],
        "au32": [7, 8], "ai32": [-8], "au64": [9], "ai64": [-10],
        "afp32": [1.0, 2.0], "afp64": [3.0, 4.0],
        "strarr": ["alpha", "beta", "gamma"],
        "blobarr": [b"\xde\xad", b"\xbe\xef", b"\x01\x02\x03"],
    })


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    full = rich_message()
    vectors = [("full_valid.bin", full, "accept")]
    for L in range(1, len(full)):
        vectors.append((f"trunc_{L:04d}.bin", full[:L], "not_reject"))
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    print(f"{len(vectors)} vectors: 1 full-valid control + "
          f"{len(vectors)-1} truncations of a {len(full)}-byte rich message")
    return vectors


# --- union pass (schema/probe-union.sofab.yaml) ------------------------------
# WP-01: §7 over the union schema. A rich, valid union message (tag + an active member
# + trailer) truncated at every byte offset passes the cut through the union open, the
# member header, the member's fixlen word and payload, the union close, and the
# trailer. A prefix of a valid message is `A` or `I`, never `R` (expect not_reject).
def _union_rich_message():
    from gen import (  # noqa: E402
        scalar_u, fixlen, FL_STRING, hdr, WT_SEQ_BEG, WT_SEQ_END,
    )
    out = bytearray()
    out += scalar_u(0, 5)                                          # tag = 5
    out += hdr(1, WT_SEQ_BEG)                                      # union `choice` open
    out += fixlen(2, FL_STRING, b"hello")                         #   as_text = "hello"
    out += bytes([WT_SEQ_END])                                     # union close
    out += scalar_u(2, 12)                                        # trailer = 12
    return bytes(out)


def emit_union(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    full = _union_rich_message()
    vectors = [("u_full_valid.bin", full, "accept")]
    for L in range(1, len(full)):
        vectors.append((f"u_trunc_{L:04d}.bin", full[:L], "not_reject"))
    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/truncation-sweep"
    emit(out)
