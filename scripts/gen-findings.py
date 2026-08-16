#!/usr/bin/env python3
"""Generate `results/FINDINGS.md` from the write-ups in `findings/`.

The index used to be maintained by hand beside the write-ups, and it carried no
information of its own: the id is the folder name, the title is the write-up's heading,
the state is its `**Status:**` line. Two copies of the same facts drift, and on
2026-08-03 they had drifted 46 times. The answer then was a checker — 241 lines of
Python parsing a markdown table to police a copy. This removes the copy instead: the
folders are the data, this file is a view, and `scripts/check-catalog.py` only has to
regenerate and compare (the pattern `scripts/materialize.sh` already uses for the
generated schema table).

WHAT EACH WRITE-UP DECLARES — the header block, directly under the heading:

    # F-0043 — a schema-bound violation is not `INVALID` until payload bytes arrive

    **Status:** ✅ **RESOLVED** — …
    **Guard:** corpus/regression — …
    **Issue:** [generator#267](https://github.com/sofa-buffers/generator/issues/267)
    **Codegen:** G-0027 | [generator#267](…) | the generator side of F-0043 — …

`Issue` is the upstream ticket(s), verbatim markdown. `Codegen` names a `G-00NN` row
that is the generator side of THIS finding — id, its own ticket, its own title, since
11 of the 21 such rows carry a ticket different from their finding's and 6 phrase their
title independently. Repeat the line for a second one (F-0038 has two). A codegen defect
with no divergence behind it gets its own folder and its own `Issue`, no `Codegen` line.

Everything below the header block is prose and belongs to the write-up alone.

Usage:
    python3 scripts/gen-findings.py            # write results/FINDINGS.md
    python3 scripts/gen-findings.py --check    # exit 1 if the file is not what this
                                               # would write (what CI runs)
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDINGS_DIR = os.path.join(ROOT, "findings")
INDEX = os.path.join(ROOT, "results", "FINDINGS.md")

# The file's prose. It describes what the table is and how to read it, which is not a
# per-finding fact and therefore has no folder to live in.
PREAMBLE = """# Findings

**One row per finding. The write-up lives in `findings/<id>/NOTES.md` — that file is the
single owner of everything about the finding: what it is, how it reproduces, who it was
attributed to, and how it was resolved.** This table carries only the link, the upstream
ticket and the state, so there is nothing here that can drift out of step with the write-up.

- `F-00NN` — a divergence the differential oracle found. Reproducer in the same folder.
- `G-00NN` — a **codegen** defect (the generator, not a corelib). Where it is the generator
  side of a divergence, the row is marked `(= F-00NN)` and points at that finding's folder,
  because it is one defect and gets one write-up.
- State: ✅ resolved · 🔴 open · ⚪ by-design or withdrawn (not open work).

**This file is generated** by `scripts/gen-findings.py` from the write-ups — do not edit it
by hand. Change the write-up and regenerate; `scripts/check-catalog.py` fails the build when
the two disagree, which is a stale index rather than a drifted one.

Chronology and decisions are **not** here — they are in
[`../docs/STATUS-LOG.md`](../docs/STATUS-LOG.md). Raw camps are in
[`CLUSTERS.md`](CLUSTERS.md).
"""

TOKENS = {"resolved": "✅", "open": "🔴", "by-design": "⚪"}


def state_of(text):
    """The state a `**Status:**` line declares."""
    m = re.search(r"^\*\*Status:\*\*(.*)$", text, re.M)
    head = m.group(1).strip()[:12] if m else ""
    if "✅" in head:
        return "resolved"
    if "🔴" in head or "🟡" in head:
        return "open"
    if "⚪" in head:
        return "by-design"
    return None


def field(text, key):
    m = re.search(rf"^\*\*{key}:\*\*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def read_all():
    """[(id, title, folder, issue, state, [codegen...])] for every write-up."""
    out = []
    for name in sorted(os.listdir(FINDINGS_DIR)):
        notes = os.path.join(FINDINGS_DIR, name, "NOTES.md")
        if not os.path.exists(notes):
            continue
        text = open(notes, encoding="utf-8").read()
        h1 = re.search(r"^# ([FG]-\d{4})\s+—\s+(.*)$", text, re.M)
        if not h1:
            sys.stderr.write(f"{name}: heading is not `# <ID> — <title>`\n")
            return None
        codegen = []
        for line in re.findall(r"^\*\*Codegen:\*\*(.*)$", text, re.M):
            parts = [p.strip() for p in re.split(r"(?<!\\)\|", line.strip())]
            if len(parts) != 3:
                sys.stderr.write(f"{name}: **Codegen:** needs `id | issue | title`\n")
                return None
            codegen.append(tuple(parts))
        out.append((h1.group(1), h1.group(2).strip(), name,
                    field(text, "Issue"), state_of(text), codegen))
    return out


def row(ident, title, folder, issue, state, pair=None):
    label = f"**{ident}**" if not pair else f"**{ident} (= {pair})**"
    link = f"[{title}](../findings/{folder}/NOTES.md)"
    return f"| {label} | {link} | {issue or '—'} | {TOKENS[state]} |"


def render(entries):
    rows, counts = [], {"resolved": 0, "open": 0, "by-design": 0}
    findings = [e for e in entries if e[0].startswith("F")]
    codegen_own = [e for e in entries if e[0].startswith("G")]
    paired = []
    for ident, title, folder, issue, state, cgs in findings:
        rows.append(row(ident, title, folder, issue, state))
        counts[state] += 1
        for gid, gissue, gtitle in cgs:
            paired.append((gid, gtitle, folder, gissue, state, ident))
    for ident, title, folder, issue, state, _ in codegen_own:
        paired.append((ident, title, folder, issue, state, None))
    for gid, gtitle, folder, gissue, state, pair in sorted(paired):
        rows.append(row(gid, gtitle, folder, gissue, state, pair))
        counts[state] += 1

    total = len(rows)
    tally = (f"**{total} entries — {counts['resolved']} resolved, {counts['open']} open, "
             f"{counts['by-design']} by-design/withdrawn.**")
    return (PREAMBLE + "\n| id | finding | issue | state |\n|---|---|---|---|\n"
            + "\n".join(rows) + "\n\n" + tally + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the committed file differs")
    args = ap.parse_args()

    entries = read_all()
    if entries is None:
        return 2
    want = render(entries)

    if args.check:
        have = open(INDEX, encoding="utf-8").read() if os.path.exists(INDEX) else ""
        if have == want:
            print(f"findings index: OK — {len(entries)} write-up(s), index is current")
            return 0
        print("results/FINDINGS.md is STALE — it is generated from the write-ups.\n"
              "  regenerate: python3 scripts/gen-findings.py", file=sys.stderr)
        return 1

    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(want)
    sys.stderr.write(f"[findings] wrote results/FINDINGS.md from {len(entries)} write-up(s)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
