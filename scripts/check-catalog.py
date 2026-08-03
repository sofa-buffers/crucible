#!/usr/bin/env python3
"""Catalog consistency gate — asserts the findings catalog and its write-ups agree.

`results/FINDINGS.md` is the single source of truth for a finding's **status**. But the
same status is legible in three other places, and each of them has drifted at least once:

  1. the catalog row itself                        (owner)
  2. `findings/<id>/NOTES.md`                      (the reproducer write-up)
  3. the `G-00NN` tracking-table row               (upstream ticket index)
  4. the `## G-00NN` detail section                (standalone codegen write-up)

On 2026-08-03 all three non-owners were found stale at once: nine paired G rows read
"open" against closed issues, three standalone G sections read "open" for tickets closed
in mid-July, and 25 NOTES.md either contradicted the catalog or carried no status at all.
Each was invisible because whichever representation you happened to read looked complete.

Being careful is not a fix — a check is. This asserts the *state token* (✅ / 🔴) agrees
everywhere it appears; the prose stays in exactly one owner per fact and is not compared.

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
        m = re.match(rf"\[?({prefix}-\d+)\]?", c[0])
        if m:
            out.append((m.group(1), c, line))
    return out


def main():
    errors = []
    text = open(CATALOG, encoding="utf-8").read()

    # --- findings: catalog row is the owner; NOTES.md must agree ------------------
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
        m = re.match(r"(F-\d+)", name)
        if m and os.path.isdir(os.path.join(FINDINGS_DIR, name)):
            dirs[m.group(1)] = name

    for fid in sorted(set(catalog) | set(dirs)):
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

    # --- codegen entries: table row vs its detail section -------------------------
    sections = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^## (G-\d+) —(.*?)(?=^## |\Z)", text, re.S | re.M)
    }
    for gid, cells, line in rows("G"):
        state = token(cells[-1])
        if state is None:
            errors.append(f"{gid}: tracking row declares no state — ✅, 🔴/🟡 or ⚪")
            continue
        paired = "(= F-" in line.split("|")[1]
        body = sections.get(gid)
        if body is None:
            if not paired:
                errors.append(f"{gid}: standalone entry with no `## {gid}` section")
            continue
        m = re.search(r"^\*\*Status:\*\*(.*)$", body, re.M)
        if not m:
            errors.append(f"{gid}: section has no `**Status:**` line")
            continue
        sec = token(m.group(1))
        if sec is None:
            errors.append(f"{gid}: section `**Status:**` declares no state (✅ or 🔴)")
        elif sec != state:
            errors.append(f"{gid}: tracking row says {state}, `## {gid}` section says {sec}")

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
        "every state token agrees"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
