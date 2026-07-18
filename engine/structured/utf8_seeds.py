#!/usr/bin/env python3
"""Invalid-UTF-8 seed generator for F-0004 (MESSAGE_SPEC §8 / CORELIB_PLAN §6.4).

Emits `probe` messages whose *only* anomaly is the `nested.str` field (id 2)
payload — a byte sequence that is not valid UTF-8. With the strict-UTF-8 check ON
family-wide (sofabgen 0.18.0 codegen for rust/java/cs/zig + the corelib-internal
checks in c/cpp/go/py/ts; c-cpp opts in via `-DSOFAB_ENABLE_STRICT_UTF8`), every
driver MUST reject such a message on decode (`R invalid_msg`). The valid controls
(embedded U+0000, a valid multi-byte scalar, plain ASCII) MUST still be accepted
(`A`) — proving the check rejects *only* malformed UTF-8, never a lossy U+FFFD.

The malformed vectors are pulled from corelib-c-cpp's `assets/test_vectors.json`
`invalid_utf8` group (the family's shared source of truth, byte-identical across
all 10 corelibs) so we cannot drift from upstream. Each `string_hex` is embedded
as the raw `string` payload; `serialized_hex`/outcomes are upstream's own scalar
form and are not used here (Crucible wraps the value in a full `probe`).

Usage: python3 engine/structured/utf8_seeds.py [out_dir]   (default corpus/regression)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen  # noqa: E402  (reuse the one reference encoder's wire primitives)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VECTORS = os.path.join(ROOT, "vendor", "corelib-c-cpp", "assets", "test_vectors.json")

# Valid controls — must decode to ACCEPT and round-trip identically on every
# driver (proves the strict check rejects only malformed UTF-8, never a valid
# multi-byte scalar, and is never a lossy U+FFFD replacement).
VALID_CONTROLS = [
    ("utf8_valid_2byte", b"\xc3\xa9"),   # 'é' U+00E9 — valid multi-byte
    ("utf8_valid_3byte", b"\xe2\x82\xac"),  # '€' U+20AC — valid 3-byte
    ("utf8_valid_ascii", b"hello"),
]

# Embedded U+0000 is *valid* UTF-8 and MUST NOT be rejected by the strict check
# (issue #55) — verified separately that all drivers accept it (verdict A). It is
# deliberately NOT in the green corpus: the C object API re-encodes `A\0B` -> `A`
# (NUL-terminated string storage), a value divergence on a *separate* axis from
# UTF-8 validity, tracked as its own finding. Exposed here for that write-up.
NUL_CONTROL = ("utf8_valid_embedded_nul", b"A\x00B")


def probe_with_raw_str(raw: bytes) -> bytes:
    """A canonical `probe` whose only set field is nested.str = `raw` (id 2).

    Frames exactly like gen.encode({'str': ...}) but carries arbitrary bytes the
    Python `str` path cannot express — so the sole divergence axis is the UTF-8
    validity of the string payload."""
    out = bytearray()
    out += gen.hdr(10, gen.WT_SEQ_BEG)             # open nested (id 10)
    out += gen.fixlen(2, gen.FL_STRING, raw)       #   str (id 2) = raw bytes
    out += bytes([gen.WT_SEQ_END])                 # close nested
    out += gen.hdr(100, gen.WT_SEQ_BEG)            # open arrays (id 100)
    out += gen.hdr(10, gen.WT_SEQ_BEG)             #   open arrays.nested
    out += bytes([gen.WT_SEQ_END])                 #   close arrays.nested
    out += bytes([gen.WT_SEQ_END])                 # close arrays
    out += gen.hdr(200, gen.WT_SEQ_BEG)            # open string_array (id 200)
    out += bytes([gen.WT_SEQ_END])                 # close string_array
    return bytes(out)


def load_invalid_vectors():
    with open(VECTORS) as f:
        doc = json.load(f)
    group = doc.get("invalid_utf8", [])
    if not group:
        raise SystemExit(f"no invalid_utf8 group in {VECTORS} — is corelib-c-cpp up to date?")
    return [(v["name"], bytes.fromhex(v["string_hex"])) for v in group]


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "corpus", "regression")
    os.makedirs(out_dir, exist_ok=True)

    # self-check: our framing of a valid str must match the reference encoder
    assert probe_with_raw_str(b"A") == gen.encode({"str": "A"}), "framing drift vs gen.encode"

    written = []
    for name, raw in load_invalid_vectors():
        path = os.path.join(out_dir, f"F0004_{name}.bin")
        with open(path, "wb") as f:
            f.write(probe_with_raw_str(raw))
        written.append((os.path.basename(path), "reject", raw.hex()))
    for name, raw in VALID_CONTROLS:
        path = os.path.join(out_dir, f"F0004_control_{name}.bin")
        with open(path, "wb") as f:
            f.write(probe_with_raw_str(raw))
        written.append((os.path.basename(path), "accept", raw.hex()))

    for fn, expect, hx in written:
        print(f"{fn:44s} expect={expect:6s} str_hex={hx}")
    print(f"\n{len(written)} seeds -> {out_dir}")


if __name__ == "__main__":
    main()
