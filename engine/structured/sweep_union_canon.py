#!/usr/bin/env python3
"""Reference-encoder canonicality over schema/probe-union.sofab.yaml (union pass only).

`gen.py` hand-writes the canonical wire of every value in `corpus/structured-union`. Until now
that encoder was checked against NOTHING: the differential asks whether the drivers agree with
each other, and a whole roster that drops a held union option agrees perfectly (the
mutation probe against the pre-generator#608 sofabgen showed exactly that: 0 divergences).

This axis states every one of those vectors as `identity`: each is the canonical form, so it
must be accepted and re-encode to exactly its own bytes. It pins `gen.py` and the roster to each
other and to MESSAGE_SPEC §2 -- a held option other than `default_id` written at its own default
(`i32_zero`, `text_empty`, `blob_empty`, `flag_false`), `default_id` at its default omitted
(`00_default`).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import encode_union, union_vectors  # noqa: E402


def emit_union(out_dir=None):
    """[(filename, bytes, 'identity')] for every union vector gen.py defines."""
    vectors = []
    for name, msg in union_vectors():
        vectors.append((f"canon_{name}.bin", encode_union(msg), "identity"))
    if out_dir is not None:
        os.makedirs(out_dir, exist_ok=True)
        for fn, data, _ in vectors:
            with open(os.path.join(out_dir, fn), "wb") as fh:
                fh.write(data)
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/union-canon-sweep"
    v = emit_union(out)
    print(f"[union-canon] {len(v)} identity vectors -> {out}", file=sys.stderr)
