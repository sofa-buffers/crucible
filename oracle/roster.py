"""The driver roster, read from `drivers/roster` — the Python side of one source.

`drivers/roster` is the single source of truth for who is in the family; the shell
side reads it through `scripts/roster.sh`. Both used to carry their own copy of the
list (five copies in total), which is the shape CLAUDE.md warns about: a list kept in
several places drifts on the first change that touches only some of them. Adding the
two C++ configurations of crucible#129 was that change.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER = os.path.join(ROOT, "drivers", "roster")


def rows(tag=None):
    """Roster rows as (name, builder, arg, tags, binary), optionally filtered by tag.

    `arg` is None where build.sh takes no argument; `binary` is absolute.
    """
    out = []
    with open(ROSTER, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].split()
            if len(line) != 5:
                continue
            name, builder, arg, tags, binary = line
            tagset = set() if tags == "-" else set(tags.split(","))
            if tag is not None and tag not in tagset:
                continue
            out.append((name, builder, None if arg == "-" else arg, tagset,
                        os.path.join(ROOT, binary)))
    return out


def gate_tag():
    """The tag a blocking gate selects: $ROSTER_TAG, defaulting to `blocking`.

    Setting ROSTER_TAG to the empty string selects the whole roster, quarantine
    included — that is how a quarantined driver is exercised. See drivers/roster.
    """
    return os.environ.get("ROSTER_TAG", "blocking") or None


def drivers(tag=None):
    """name -> absolute binary path, in roster order."""
    return {name: binary for name, _, _, _, binary in rows(tag)}


def meta(builder):
    """`drivers/<builder>/meta` as a dict of its key=value lines.

    Carries the declarative half of the driver contract — `chunked_decode` and
    `encode_surfaces` say what the *backend* offers, so a gate can tell "this driver
    was not taught the axis" from "this backend has no such surface".
    """
    out = {}
    path = os.path.join(ROOT, "drivers", builder, "meta")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def encode_surfaces(builder):
    """The encode surfaces this backend has, as a set: {'new','to','stream'}."""
    v = meta(builder).get("encode_surfaces", "")
    return set() if v in ("", "-") else set(v.split(","))


def min_output_buffer(builder):
    """This port's declared `MIN_OUTPUT_BUFFER` (CORELIB_PLAN §5.1).

    The smallest buffer the corelib accepts **for streaming**. A port that splits
    atomic units declares 1; one that requires them to land contiguously declares the
    largest run it reserves as one piece, and the spec caps any declaration at 20.

    It is declared here rather than read out of the corelib because the constant's
    spelling differs per language (`MIN_OUTPUT_BUFFER`, `MinOutputBuffer`,
    `minOutputBuffer`, `SOFAB_MIN_OUTPUT_BUFFER`) and a gate that grepped for it would
    silently fall back to a wrong default the day a port renamed it. A missing
    declaration is an error at the point of use, never an assumed 1 — assuming the old
    universal floor is exactly the bug this replaced.
    """
    v = meta(builder).get("min_output_buffer", "")
    return None if v == "" else int(v)


def pass_through(builder):
    """Whether this port implements the §5.1 pass-through permission.

    An encoder MAY hand a `string`/`blob` run to its sink directly rather than copying
    it through the output buffer, when the caller granted it at installation. The
    permission is optional and wire-neutral — §5.1: "A port MAY ignore the permission
    entirely and always copy. That is conformant" — so a `no` here is a statement about
    the port, never a defect.

    Declared rather than detected for the same reason as `min_output_buffer`: the
    spelling differs per language, and most ports state it only in prose in their
    README. A missing declaration returns None and is an error at the point of use, so
    a new driver cannot join the roster silently untested on this axis.
    """
    v = meta(builder).get("pass_through", "").strip().lower()
    if v in ("yes", "true", "1"):
        return True
    if v in ("no", "false", "0"):
        return False
    return None
