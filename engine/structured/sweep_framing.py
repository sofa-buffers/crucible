#!/usr/bin/env python3
"""Framing & format-ceiling sweep (MESSAGE_SPEC §5.2 / CORELIB_PLAN §4.9/§6.2) — a
sweep axis for two malformation classes with no dedicated coverage.

**Stray / unbalanced sequence-end.** A `sequence end` marker (`0x07`) with no open
sequence is INVALID (`oracle/canonical.md:33`, CORELIB_PLAN §5.2:420 / §6.3:697 —
"a sequence-end marker with no open sequence"). `sweep_truncation` only ever produces
*open* sequences (→ `I`); it never emits a *surplus* end. This axis emits the stray-end
forms the mutator DESIGN planned but the grammar mutator does not yet build.

**Format-wide ceilings** (CORELIB_PLAN §6.2:640-646): a field `id > ID_MAX` (2³¹−1), a
fixlen length `> FIXLEN_MAX`, an array count `> ARRAY_MAX`, or nesting past
`MAX_DEPTH` (255) is INVALID (§6.2). Reachable today only by fuzzer luck. To test the
*format* ceiling (not the schema `count`/`maxlen`, which `sweep_overbound` covers, and
not the *open* over-schema-count+truncated corner — documentation#15, `corpus/
regression/README.md`), the over-ceiling values sit at **unknown field ids** and use
**2³¹** (over the ceiling on *every* profile — FIXLEN_MAX/ARRAY_MAX may be 65,535 on
constrained profiles or 2³¹−1 on heap ones, and 2³¹ is over both).

**§5.2 precedence.** A huge declared length/count also makes the message *truncated*
(the payload never arrives). The over-ceiling length/count is malformed **regardless
of what follows** (§6.2), so INVALID dominates INCOMPLETE — expect `R`, per the adopted
§5.2 clause (documentation#17). Crucially the vectors declare a huge size but carry
**no payload**, so a conformant decoder rejects at the header word and never allocates;
a driver that instead allocates per the declared length is an amplification/DoS finding
(the F-0013 precedent) — caught by the comparator's per-driver timeout.

Report-only first (ground rule 4); promote to blocking once green or every divergence
is a catalogued finding.

Usage: python3 engine/structured/sweep_framing.py [out_dir]   (default corpus/framing-sweep)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gen import (  # noqa: E402
    varint, WT_U, WT_FIX, WT_ARR_U, WT_SEQ_BEG, WT_SEQ_END, FL_STRING,
    hdr, scalar_u, fixlen,
)

ID_MAX = (1 << 31) - 1          # 2,147,483,647 (CORELIB_PLAN §6.2)
OVER_CEIL = 1 << 31             # over ID_MAX, and over FIXLEN_MAX/ARRAY_MAX on every profile
UNKNOWN_ID_A = 50               # ids absent from schema/probe.sofab.yaml (max real id is 201)
UNKNOWN_ID_B = 51
END = bytes([WT_SEQ_END])


def emit(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    vectors = []

    def add(name, data, expect):
        vectors.append((f"{name}.bin", data, expect))

    # --- stray / unbalanced sequence-end (INVALID) ----------------------------
    add("stray_end_toplevel", END, "reject")                       # 07 with nothing open
    add("stray_end_after_scalar", scalar_u(0, 5) + END, "reject")  # valid field, then stray end
    # open+close nested struct (id 10), then one extra end
    add("balanced_then_extra_end",
        hdr(10, WT_SEQ_BEG) + END + END, "reject")
    # open string_array wrapper (id 200) with an element, close, then extra end
    add("stray_end_in_wrapper",
        hdr(200, WT_SEQ_BEG) + fixlen(0, FL_STRING, b"A") + END + END, "reject")
    # two extra ends after a balanced close
    add("two_extra_ends", hdr(10, WT_SEQ_BEG) + END + END + END, "reject")
    # control: a balanced empty nested struct is valid (must NOT reject)
    add("balanced_ok_ctl", hdr(10, WT_SEQ_BEG) + END, "accept")

    # --- field-id ceiling (ID_MAX) --------------------------------------------
    # at ID_MAX: the largest *valid* id — unknown to the schema, so skipped -> accept.
    # Must NOT reject "for the id" (the control the WP calls out).
    add("id_at_ID_MAX_ctl", varint((ID_MAX << 3) | WT_U) + varint(5), "accept")
    # over ID_MAX: id 2³¹ -> INVALID (CORELIB_PLAN §6.2; the on_header id>ID_MAX guard)
    add("id_over_ID_MAX", varint((OVER_CEIL << 3) | WT_U) + varint(5), "reject")

    # --- fixlen length ceiling (FIXLEN_MAX) -----------------------------------
    # unknown-id fixlen declaring length 2³¹, NO payload -> INVALID at the word
    # (over FIXLEN_MAX, §6.2). Also truncated: §5.2 says INVALID dominates (doc#17).
    over_word = (OVER_CEIL << 3) | FL_STRING
    add("fixlen_len_over_FIXLEN_MAX",
        hdr(UNKNOWN_ID_A, WT_FIX) + varint(over_word), "reject")
    # control: a small skipped fixlen (len 1, 1 byte) -> skipped -> accept
    add("fixlen_len_ok_ctl",
        hdr(UNKNOWN_ID_A, WT_FIX) + varint((1 << 3) | FL_STRING) + b"A", "accept")

    # --- array count ceiling (ARRAY_MAX) --------------------------------------
    # unknown-id integer array declaring count 2³¹, NO elements -> INVALID (over
    # ARRAY_MAX, §6.2). Declared-huge / actual-empty: a conformant decoder rejects at
    # the count word and never allocates.
    add("count_over_ARRAY_MAX",
        hdr(UNKNOWN_ID_B, WT_ARR_U) + varint(OVER_CEIL), "reject")
    # control: a small skipped array (count 1, one element) -> skipped -> accept
    add("count_ok_ctl",
        hdr(UNKNOWN_ID_B, WT_ARR_U) + varint(1) + varint(5), "accept")

    # --- nesting depth ceiling (MAX_DEPTH = 255) ------------------------------
    # 300 sequence-opens (id 0) with nothing to balance them -> exceeds MAX_DEPTH
    # (255) before EOF; a conformant decoder rejects at the 256th open (INVALID, §4.9)
    # rather than reporting INCOMPLETE for the unclosed sequences.
    add("depth_over_MAX_DEPTH", hdr(0, WT_SEQ_BEG) * 300, "reject")
    # control: a modest, balanced 8-deep nest is valid -> accept
    add("depth_ok_ctl", hdr(0, WT_SEQ_BEG) * 8 + END * 8, "accept")

    for name, data, _ in vectors:
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
    by = {}
    for _, _, e in vectors:
        by[e] = by.get(e, 0) + 1
    print(f"{len(vectors)} vectors: " + ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
    return vectors


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "corpus/framing-sweep"
    emit(out)
