#!/usr/bin/env python3
"""Value relations a cluster signature can name, so a baseline row matches a CAUSE.

A camp signature (cluster.py) records which drivers split and with which verdict, never
the values. That is right for a verdict split, and wrong for a value split: a row
`accept:c | accept:<everyone else>` would match *any* future defect where one driver
decodes a different value, whatever the cause. A row that explains a value split must
therefore name the relation between the two values, and the clustering must check it.

One relation is defined today:

``nul-projection`` — the one camp's value is the other camp's value with every string
cut at its first U+0000. That is F-0018's mechanism: a profile whose string storage is
NUL-terminated keeps only the bytes before the first NUL — by design per MESSAGE_SPEC §8 /
CORELIB_PLAN §6.4's interop note (see the `c-embedded-nul-string-projection` entry in
oracle/policy.yaml). Nothing here
names a driver; any camp whose value stands in this relation to the other camp's is
tagged, and any camp that does not is reported on its own merits.

Both canonical forms are handled:

* the materialized form (oracle/materialized.md) carries strings as ``t<n>:<hex>``, so
  the projection is applied to the text directly;
* the round-trip form (oracle/canonical.md) carries the re-encoded wire. The wire is
  self-describing (CORELIB_PLAN §4), so both lines are parsed into a field tree, the
  projection is applied to every string, and the trees are compared after dropping the
  default leaves a canonical encoder omits (a string cut to empty is such a leaf).

Anything that does not parse is *not* related — the conservative answer, which leaves
the camp to be reported as new.
"""
import re

NUL_PROJECTION = "nul-projection"

# wire types (low 3 bits of a field header) and the fixlen subtypes, CORELIB_PLAN §4
_WT_U, _WT_S, _WT_FIX, _WT_ARR_U, _WT_ARR_S, _WT_ARR_FIX, _WT_SEQ_BEG, _WT_SEQ_END = range(8)
_FL_STRING = 2

_TEXT = re.compile(r"t(\d+):([0-9a-f]*)")


def _project_materialized(value):
    def cut(m):
        raw = bytes.fromhex(m.group(2))
        raw = raw.split(b"\0", 1)[0]
        return f"t{len(raw)}:{raw.hex()}"
    return _TEXT.sub(cut, value)


class _Malformed(Exception):
    pass


def _varint(b, i):
    n = shift = 0
    while True:
        if i >= len(b):
            raise _Malformed()
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return n, i
        if shift > 63:
            raise _Malformed()


def _parse_seq(b, i, nested):
    """{field id: value} up to the matching sequence end (or the end of input at the
    top level). A value is a tuple for a leaf or array, a dict for a sequence."""
    out = {}
    while i < len(b):
        h, i = _varint(b, i)
        fid, wt = h >> 3, h & 7
        if wt == _WT_SEQ_END:
            if not nested:
                raise _Malformed()
            return out, i
        if wt in (_WT_U, _WT_S):
            v, i = _varint(b, i)
            val = ("n", v)
        elif wt == _WT_FIX:
            word, i = _varint(b, i)
            n = word >> 3
            if i + n > len(b):
                raise _Malformed()
            val = ("fix", word & 7, b[i:i + n])
            i += n
        elif wt in (_WT_ARR_U, _WT_ARR_S):
            cnt, i = _varint(b, i)
            items = []
            for _ in range(cnt):
                v, i = _varint(b, i)
                items.append(v)
            val = ("arr", tuple(items))
        elif wt == _WT_ARR_FIX:
            cnt, i = _varint(b, i)
            word, i = _varint(b, i)
            n = cnt * (word >> 3)
            if i + n > len(b):
                raise _Malformed()
            val = ("arrfix", word & 7, b[i:i + n])
            i += n
        elif wt == _WT_SEQ_BEG:
            val, i = _parse_seq(b, i, True)
        else:
            raise _Malformed()
        if fid in out:
            raise _Malformed()          # a re-encode never repeats an id
        out[fid] = val
    if nested:
        raise _Malformed()
    return out, i


def _normalize(tree, project):
    """Drop default leaves and empty sequences; cut strings at NUL when `project`."""
    out = {}
    for fid, val in tree.items():
        if isinstance(val, dict):
            val = _normalize(val, project)
            if not val:
                continue
        elif val[0] == "fix":
            payload = val[2]
            if project and val[1] == _FL_STRING:
                payload = payload.split(b"\0", 1)[0]
            if not any(payload):
                continue                # "" / empty blob / +0.0 — omitted when default
            val = ("fix", val[1], payload)
        elif val[0] == "n" and val[1] == 0:
            continue
        elif val[0] in ("arr", "arrfix") and not val[-1]:
            continue
        out[fid] = val
    return out


def _wire_tree(hexstr, project):
    b = bytes.fromhex(hexstr)
    tree, _ = _parse_seq(b, 0, False)
    return _normalize(tree, project)


def related(line, other, relation=NUL_PROJECTION):
    """Is `line` the `relation`-projection of `other`? Both are canonical `A` lines of
    the same oracle (round-trip wire hex, or a materialized value)."""
    if relation != NUL_PROJECTION or line == other:
        return False
    if not (line.startswith("A ") and other.startswith("A ")):
        return False
    a, b = line[2:], other[2:]
    if a.startswith(("{", "[")) or b.startswith(("{", "[")):
        return a == _project_materialized(b)
    try:
        return _wire_tree(a, False) == _wire_tree(b, True) and \
            _wire_tree(b, False) != _wire_tree(b, True)
    except (_Malformed, ValueError):
        return False
