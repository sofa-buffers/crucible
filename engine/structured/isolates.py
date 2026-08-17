#!/usr/bin/env python3
"""Minimal isolates — clean inputs that a finding's *original* reproducer can't express.

Most resolved findings kept their original reproducer in `findings/<id>/`, and that file
is the regression test. Some findings' originals are **contaminated**: they trip the
still-open INVALID-vs-INCOMPLETE precedence spec-hole
([documentation#15](https://github.com/sofa-buffers/documentation/issues/15)) *as well
as* the bug they were filed for, so the family legitimately splits on them and they can
never join a green gate. Their write-ups instead assert the fix against a **clean
isolate** quoted only as prose hex (the F-0004 lesson: characterize a divergence with a
minimal isolate, not a raw fuzzer input).

This script materializes those isolates as real files, so a claim like "all drivers agree"
is executable rather than prose. Wire primitives are imported from `gen.py` — the one
reference encoder — so an encoding change cannot silently desync them.

Each isolate declares its own destination: a *green* isolate goes to
`corpus/regression/` (the gate); a *diverging* one is a finding reproducer and goes to
`findings/<id>/`. Regenerating is idempotent — the committed bytes are the contract.

Usage: python3 engine/structured/isolates.py [repo_root]   (default: cwd)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import WT_SEQ_BEG, WT_SEQ_END, arr_u, fstr, hdr, scalar_u

# schema/probe.sofab.yaml: every array is `count: 5`; string_array is id 200.
SCHEMA_COUNT = 5


def f0003_overcount_clean() -> bytes:
    """F-0003 / generator#100 — a *clean* (non-truncated) over-count scalar array.

    `a6 06 03 08 01 02 03 04 05 06 07 08 07` — the arrays struct (id 100) carrying a u8
    array (id 0) whose wire count is 8, over the schema's count of 5. Per MESSAGE_SPEC
    §3+§7 an over-count array is INVALID, so every driver must reject (`R`).

    Contrast the kept original `array_overflow.bin`, which is over-count *and*
    truncated: there rust reports `I` (lazy — runs out of bytes first) and the family
    `R`, which is documentation#15's precedence hole, not the over-count axis. This is
    the exact input results/FINDINGS.md quotes as the 2026-07-15 re-verification.
    """
    return (
        hdr(100, WT_SEQ_BEG)
        + arr_u(0, [1, 2, 3, 4, 5, 6, 7, 8])  # count 8 > schema count 5
        + bytes([WT_SEQ_END])
    )


def f0012_overindex_clean() -> bytes:
    """F-0013 / G-0013 — a string_array element at an index at/beyond the schema count.

    `c6 0c c2 07 0a 78 07` — string_array (id 200) opened, one fixlen-string element at
    wire index 120 (>= the schema count of 5), closed. Complete and non-truncated, so it
    isolates the over-index axis alone (no documentation#15 precedence contamination).

    The family splits on the *value*, all accepting: the fixed-capacity profiles (c,
    cpp-c-cpp, rust-nostd) drop the element per MESSAGE_SPEC §5.1, while every heap
    profile keeps it at index 120. See the finding's NOTES.md.
    """
    return (
        hdr(200, WT_SEQ_BEG)
        + fstr(120, "x")  # element index 120 >= schema count 5
        + bytes([WT_SEQ_END])
    )


def f0012_overindex_amplify() -> bytes:
    """F-0013 / G-0013 — the memory-amplification probe (same shape, huge index).

    `c6 0c 82 c8 d0 07 0a 78 07` — 9 bytes claiming element index 2,000,000. The heap
    profiles' unbounded `while (len <= id) push(default)` fill materializes id+1
    elements, so this 9-byte input costs cpp ~226 MB / go ~122 MB of RSS while the
    fixed-capacity profiles stay flat at ~8 MB. The index is a varint (up to 2^64), so
    an attacker raises it until OOM. Not a gate input — it is the DoS evidence.
    """
    return (
        hdr(200, WT_SEQ_BEG)
        + fstr(2_000_000, "x")
        + bytes([WT_SEQ_END])
    )



# --- The explicit empty array vs a non-empty declared default --------------------
#
# The case Crucible could not reach until 2026-08-17, and the reason was its own: no
# schema declared `default:` on any field, so "absent" and "explicitly empty" denoted
# the same value everywhere and the distinction did not exist to test.
# `schema/probe-dyn.sofab.yaml` now carries `def_arr` (id 3, u32 array, default
# [7, 9]), and these vectors pin what each wire form means there.
#
# `def_arr` is a NUMERIC array, so its declared type maps to the compact
# unsigned-array wire type, and MESSAGE_SPEC §3 is the clause that governs it:
#
#     absent            -> the declared default, here [7, 9]
#     compact, M = 0    -> the EMPTY array (§3: a length of zero IS the explicit
#                          empty array — it overrides the non-empty default)
#     compact, M > 0    -> those elements
#
# The wrapper form is NOT the empty-array spelling here. A `SEQ_BEG` frame carries a
# wire type the declared type does not map to, so MESSAGE_SPEC §7.3 applies instead:
# the field MUST be skipped, a decoder MUST NOT report INVALID, and it MUST NOT
# decode the payload into the declared field — the field keeps [7, 9]. Two vectors
# below pin exactly that, because it is the reading a §2-shaped intuition gets wrong.
#
# §2's empty-frame table (where an empty wrapper DOES mean the empty array) governs
# the WRAPPER arrays — `string_array` / `blob_array` / `struct_array` in
# `schema/probe.sofab.yaml`. None of those declares a non-empty default, so that half
# of the case is still untested; see the WP-08(c) entry in docs/TODO.md.

DEF_ARR = 3          # probe-dyn `def_arr`


def _dyn_filler() -> bytes:
    """A minimal valid probe-dyn body: dyn_arr = [1]. Present so a vector is never the
    zero-length record, which drivers treat as the all-defaults message."""
    return arr_u(0, [1])


def defarr_absent() -> bytes:
    """`def_arr` not on the wire -> the declared default [7, 9]. Canonical: the field
    equals its default, so a conformant encoder omits it and the round trip is a
    fixed point."""
    return _dyn_filler()


def defarr_compact_empty() -> bytes:
    """A compact array of length 0 at `def_arr` -> the EMPTY array, NOT [7, 9].

    The vector the whole exercise is about: MESSAGE_SPEC §3 makes `M = 0` the explicit
    empty array, so this is the one wire form that overrides a non-empty declared
    default. A driver that decodes it as [7, 9] — i.e. that treats "no elements" as
    "nothing was said" — fails here. It is also a fixed point: the value differs from
    the default, so a conformant encoder writes it back exactly like this."""
    return _dyn_filler() + arr_u(DEF_ARR, [])


def defarr_empty_wrapper() -> bytes:
    """An empty `SEQ_BEG` frame at `def_arr` -> the field is SKIPPED, keeping [7, 9].

    Not an empty-array spelling: `def_arr` maps to the compact unsigned-array wire
    type, so a wrapper frame is a wire-type mismatch and MESSAGE_SPEC §7.3 governs —
    skip the field, do not report INVALID, do not decode the payload into it. Kept as
    a vector precisely because a §2-shaped reading expects `[]` here and gets the
    default instead; that reading nearly became a filed finding on 2026-08-17."""
    return _dyn_filler() + hdr(DEF_ARR, WT_SEQ_BEG) + bytes([WT_SEQ_END])


def defarr_wrapper_values() -> bytes:
    """A wrapper carrying elements 0 and 1 -> also SKIPPED, keeping [7, 9].

    The control for the one above. Same §7.3 mismatch, but with a payload that would
    be a perfectly good [5, 6] if the field were read: it separates "skipped the frame"
    from "read the frame and found it empty". A driver decoding this to [5, 6] has
    decoded a payload §7.3 forbids it to decode."""
    body = scalar_u(0, 5) + scalar_u(1, 6)
    return _dyn_filler() + hdr(DEF_ARR, WT_SEQ_BEG) + body + bytes([WT_SEQ_END])


def defarr_compact_values() -> bytes:
    """[5, 6] in the compact form — the canonical encoding of a non-empty value, and
    the contrast that makes the two §7.3 vectors above readable: this is what the wire
    looks like when the elements DO reach the field."""
    return _dyn_filler() + arr_u(DEF_ARR, [5, 6])


def defarr_default_written() -> bytes:
    """The declared default written out explicitly. §2 says a field at its default is
    omitted, so this is well-formed but NON-canonical: every decoder must accept it
    and re-encode it as absent. A driver that echoes it back has not normalised."""
    return _dyn_filler() + arr_u(DEF_ARR, [7, 9])


# (destination dir, filename, builder)
ISOLATES = [
    ("corpus/regression", "F0003_overcount_clean.bin", f0003_overcount_clean),
    ("findings/F-0013-overindex-string-array-element-kept-vs-dropped",
     "overindex_clean.bin", f0012_overindex_clean),
    ("findings/F-0013-overindex-string-array-element-kept-vs-dropped",
     "overindex_amplify.bin", f0012_overindex_amplify),
    # Array-default vectors — probe-dyn only, so they live in the limit-mode corpus,
    # the one gate that builds against that schema.
    ("corpus/limits/default", "absent.bin", defarr_absent),
    ("corpus/limits/default", "compact_empty.bin", defarr_compact_empty),
    ("corpus/limits/default", "empty_wrapper.bin", defarr_empty_wrapper),
    ("corpus/limits/default", "wrapper_values.bin", defarr_wrapper_values),
    ("corpus/limits/default", "compact_values.bin", defarr_compact_values),
    ("corpus/limits/default", "default_written.bin", defarr_default_written),
]


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    for subdir, name, fn in ISOLATES:
        out_dir = os.path.join(root, subdir)
        os.makedirs(out_dir, exist_ok=True)
        data = fn()
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        print(f"{subdir}/{name:26s} {len(data):3d} B  {data.hex()}")


if __name__ == "__main__":
    main()
