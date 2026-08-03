#!/usr/bin/env python3
"""Catalog consistency gate — asserts the findings catalog and its write-ups agree.

`results/FINDINGS.md` is the single source of truth for a finding's **status**. But the
same status is legible in three other places, and each of them has drifted at least once:

`findings/<id>/NOTES.md` is the single owner of everything about a finding. `results/
FINDINGS.md` is a pure index: one row per entry, carrying the link, the upstream ticket and
the state — nothing that can drift out of step with the write-up.

That structure exists because the previous one rotted on three strands in a single day: a
tracking table whose rows read "open" against closed issues, detail sections that disagreed
with their own rows, and 46 write-ups that either contradicted the index or declared nothing
at all. Being careful is not a fix — a check is.

This asserts the **state token** (✅ / 🔴 / ⚪) in the index matches the one in the write-up,
and that the index and `findings/` cover exactly the same set of entries. Prose is never
compared: it has one owner.

Run: `python3 scripts/check-catalog.py`   (exit 1 on any mismatch)
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "results", "FINDINGS.md")
FINDINGS_DIR = os.path.join(ROOT, "findings")

RESOLVED, OPEN, BYDESIGN = "resolved", "open", "by-design"


def token(text):
    """The state a status cell/line declares, or None if it declares none."""
    head = text.strip()[:12]
    if "✅" in head:
        return RESOLVED
    if "🔴" in head or "🟡" in head:
        return OPEN
    if "⚪" in head:
        return BYDESIGN
    return None


def cells(line):
    """Split a table row on unescaped pipes — `\\|` inside a cell is content, not a border."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def rows(prefix):
    """(id, cells) for every table row whose first cell starts with `prefix`."""
    out = []
    for line in open(CATALOG, encoding="utf-8"):
        if not line.startswith("| "):
            continue
        c = cells(line)
        m = re.match(rf"[\*\[\s]*({prefix}-\d+)", c[0])
        if m:
            out.append((m.group(1), c, line))
    return out


def main():
    errors = []
    text = open(CATALOG, encoding="utf-8").read()

    # --- every row: the write-up it points at must declare the same state --------
    catalog = {}
    for fid, cells, _ in rows("F"):
        state = token(cells[-1])
        if state is None:
            errors.append(
                f"{fid}: catalog row declares no state — it must open with ✅, 🔴/🟡 or ⚪"
            )
        catalog[fid] = state

    dirs = {}
    for name in sorted(os.listdir(FINDINGS_DIR)):
        m = re.match(r"([FG]-\d+)", name)
        if m and os.path.isdir(os.path.join(FINDINGS_DIR, name)):
            dirs[m.group(1)] = name

    for fid in sorted(set(catalog) | {d for d in dirs if d.startswith("F-")}):
        if fid not in dirs:
            errors.append(f"{fid}: in the catalog but has no findings/ directory")
            continue
        if fid not in catalog:
            errors.append(f"{fid}: has findings/{dirs[fid]}/ but no catalog row")
            continue
        notes = os.path.join(FINDINGS_DIR, dirs[fid], "NOTES.md")
        if not os.path.exists(notes):
            errors.append(f"{fid}: findings/{dirs[fid]}/NOTES.md is missing")
            continue
        m = re.search(r"^\*\*Status:\*\*(.*)$", open(notes, encoding="utf-8").read(), re.M)
        if not m:
            errors.append(f"{fid}: NOTES.md has no `**Status:**` line")
            continue
        state = token(m.group(1))
        if state is None:
            errors.append(f"{fid}: NOTES.md `**Status:**` declares no state (✅, 🔴 or ⚪)")
        elif catalog[fid] is not None and state != catalog[fid]:
            errors.append(
                f"{fid}: catalog says {catalog[fid]}, NOTES.md says {state}"
            )

    # --- codegen rows: standalone ones own a folder, paired ones borrow the F one -
    for gid, cells, line in rows("G"):
        state = token(cells[-1])
        paired = re.search(r"=\s*(F-\d+)", cells[0])
        if state is None:
            errors.append(f"{gid}: index row declares no state — ✅, 🔴/🟡 or ⚪")
            continue
        if paired:
            fid = paired.group(1)
            if fid not in catalog:
                errors.append(f"{gid}: paired with {fid}, which has no row")
            elif catalog[fid] is not None and state != catalog[fid]:
                errors.append(
                    f"{gid}: says {state}, but {fid} — the same defect — says {catalog[fid]}"
                )
            continue
        if gid not in dirs:
            errors.append(f"{gid}: standalone codegen entry with no findings/ directory")
            continue
        notes = os.path.join(FINDINGS_DIR, dirs[gid], "NOTES.md")
        m = re.search(r"^\*\*Status:\*\*(.*)$", open(notes, encoding="utf-8").read(), re.M)
        if not m:
            errors.append(f"{gid}: NOTES.md has no `**Status:**` line")
            continue
        sec = token(m.group(1))
        if sec is None:
            errors.append(f"{gid}: NOTES.md `**Status:**` declares no state")
        elif sec != state:
            errors.append(f"{gid}: index says {state}, NOTES.md says {sec}")

    if errors:
        print(f"catalog check: {len(errors)} mismatch(es)\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\nresults/FINDINGS.md owns a finding's status. Fix the non-owner, "
            "or the catalog if the catalog is what is wrong.",
            file=sys.stderr,
        )
        return 1

    print(
        f"catalog check: OK — {len(catalog)} findings, {len(rows('G'))} codegen entries, "
        f"{len(dirs)} folders; every state token agrees"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
