"""Reproducer: a mistyped element inside an array-of-struct is read, not skipped.

Generate `message.py` from rows.sofab.yaml with `sofabgen --lang python`, put it
on PYTHONPATH next to an installed corelib-py, and run this file. Set
SOFAB_PUREPYTHON=1 to use the pure engine instead of the Cython one; both
answer the same.
"""
from message import Table
from sofab import SofaArgumentError, SofaIncompleteError, SofaLimitError


def varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b, v = v & 0x7F, v >> 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def header(fid: int, wire_type: int) -> bytes:
    return varint((fid << 3) | wire_type)


ARRAY_UNSIGNED, SEQUENCE_START, SEQUENCE_END = 3, 6, 7
ROWS = header(0, SEQUENCE_START)  # opens `rows` (id 0), the array-of-struct wrapper
END = header(0, SEQUENCE_END)


def uarray(fid: int, count: int, present: int) -> bytes:
    """An unsigned-array field announcing `count` one-byte elements, `present` of them on the wire."""
    return header(fid, ARRAY_UNSIGNED) + varint(count) + b"\x01" * present


CASES = [
    # (name, wire, what MESSAGE_SPEC §7.3 requires)
    ("A  mistyped element, count 3, complete", ROWS + uarray(1, 3, 3) + END, "COMPLETE"),
    ("B  mistyped element, count 70000, complete", ROWS + uarray(1, 70000, 70000) + END, "COMPLETE"),
    ("C  mistyped element, count 20, 17 present", ROWS + uarray(1, 20, 17), "INCOMPLETE"),
    ("D  mistyped element, count 1886575, 0 present", ROWS + uarray(1, 1886575, 0), "INCOMPLETE"),
    ("E  `rows` itself (a sequence) carrying an array, count 70000", uarray(0, 70000, 70000), "COMPLETE"),
    ("F  `k` (u32) inside an element carrying an array, count 70000",
     ROWS + header(0, SEQUENCE_START) + uarray(0, 70000, 70000) + END + END, "COMPLETE"),
    ("G  `k` (u32) inside an element, count 1886575, 0 present",
     ROWS + header(0, SEQUENCE_START) + uarray(0, 1886575, 0), "INCOMPLETE"),
    # controls: the same arrays as an UNKNOWN id in the root scope -- skipped correctly
    ("B' unknown root id 5, count 70000, complete", uarray(5, 70000, 70000), "COMPLETE"),
    ("C' unknown root id 5, count 20, 17 present", uarray(5, 20, 17), "INCOMPLETE"),
    ("D' unknown root id 5, count 1886575, 0 present", uarray(5, 1886575, 0), "INCOMPLETE"),
]


def outcome(wire: bytes) -> str:
    try:
        Table.decode(wire)
        return "COMPLETE"
    except SofaIncompleteError:
        return "INCOMPLETE"
    except SofaLimitError as e:
        return f"SofaLimitError: {e}"
    except SofaArgumentError as e:
        return f"SofaArgumentError: {e}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


for name, wire, want in CASES:
    got = outcome(wire)
    mark = "ok " if got == want else "BUG"
    print(f"{mark} {name:48} want {want:10}  got {got}")
