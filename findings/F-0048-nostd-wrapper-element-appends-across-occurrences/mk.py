"""Minimal vectors for cluster 4: a wrapper-array element written twice.

Header  = (id << 3) | wire_type          (MESSAGE_SPEC:474)
fixlen  = (length << 3) | subtype        (CORELIB_PLAN 4.6; string=0x2, blob=0x3)
SEQ start = wire type 6, SEQ end = 0x07
"""
import os, pathlib

OUT = pathlib.Path("/tmp/claude-0/-workspace/2c65ecb6-6efb-478f-8652-eb8f4eab778a/scratchpad/c4")
OUT.mkdir(parents=True, exist_ok=True)

def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)

def hdr(fid, wt):   return varint((fid << 3) | wt)
def fixlen(n, st):  return varint((n << 3) | st)

STR_ARRAY, BLOB_ARRAY, SEQ, END = 200, 201, 6, b"\x07"

def elem(idx, payload, subtype):
    return hdr(idx, 2) + fixlen(len(payload), subtype) + payload

def wrapper(fid, body):
    return hdr(fid, SEQ) + body + END

V = {}
# R1: element 0 of string_array written TWICE, short. Under 7.4 last-wins the
# value is "CD"; an appending decoder yields "ABCD" — no overflow, pure value split.
V["r1_string_elem_written_twice"] = wrapper(STR_ARRAY, elem(0, b"AB", 2) + elem(0, b"CD", 2))
# R2: same shape, repeated until an appending decoder exceeds heapless String<64>.
V["r2_string_elem_overflow_by_repeat"] = wrapper(STR_ARRAY, elem(0, b"AB", 2) * 40)
# R3: the blob twin (line 475 has the identical missing-clear shape).
V["r3_blob_elem_written_twice"] = wrapper(BLOB_ARRAY, elem(0, b"AB", 3) + elem(0, b"CD", 3))
# Controls: each write ALONE must be unanimous, so any split is about the repeat.
V["ctl_string_elem_written_once"] = wrapper(STR_ARRAY, elem(0, b"CD", 2))
V["ctl_blob_elem_written_once"] = wrapper(BLOB_ARRAY, elem(0, b"CD", 3))
# Control: two writes to DIFFERENT element ids — no duplicate id, must be unanimous.
V["ctl_string_two_distinct_elems"] = wrapper(STR_ARRAY, elem(0, b"AB", 2) + elem(1, b"CD", 2))
# Control: the scalar string field (nested.str, id 10>2) written twice — that arm
# HAS the .clear(), so it must be unanimous. Proves the defect is wrapper-specific.
V["ctl_scalar_string_written_twice"] = (
    hdr(10, SEQ) + hdr(2, 2) + fixlen(2, 2) + b"AB" + hdr(2, 2) + fixlen(2, 2) + b"CD" + END)

for name, data in V.items():
    (OUT / f"{name}.bin").write_bytes(data)
    print(f"{name:38s} {len(data):4d} B  {data[:24].hex()}")
