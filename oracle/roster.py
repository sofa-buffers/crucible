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
