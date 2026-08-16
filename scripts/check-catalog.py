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

import hashlib
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


def _sha1(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


GUARD_RE = re.compile(r"^\*\*Guard:\*\*(.*)$", re.M)


def check_guard(fid, folder, text, errors):
    """A closed finding with reproducers must declare what RE-CHECKS it.

    Flipping a finding to ✅ and leaving its reproducers in `findings/<id>/` is the
    quiet failure this catches: nothing replays them, so the bug is closed but not
    guarded. It went unnoticed 18 times because the step happens weeks after the
    find, usually while several findings go green at once, and because it produces
    no visible result — adding a converged vector to a green gate leaves it green.

    Three declarations are legitimate, and the difference matters:

        **Guard:** corpus/regression       the vectors live in a gate corpus
        **Guard:** sweep_malform_truncate  a sweep axis owns the rule now, at every
                                           position — stronger than a frozen vector
        **Guard:** none — <reason>         not guardable, and why (F-0018's by-design
                                           divergence would turn a gate red)

    The reproducer-less `G-00NN` folders are exempt: a codegen defect's reproducer is
    generated source, not a wire input.
    """
    d = os.path.join(FINDINGS_DIR, folder)
    bins = [f for f in os.listdir(d) if f.endswith(".bin")]
    if not bins:
        return
    m = GUARD_RE.search(text)
    if not m:
        errors.append(
            f"{fid}: closed with {len(bins)} reproducer(s) but no `**Guard:**` line — "
            "declare what re-checks it: a gate corpus, a sweep axis, or `none — <reason>`")
        return
    decl = m.group(1).strip().strip("`").strip()
    if decl.startswith("corpus/"):
        corpus = os.path.join(ROOT, decl.split()[0])
        if not os.path.isdir(corpus):
            errors.append(f"{fid}: Guard names {decl}, which is not a directory")
            return
        # Match by CONTENT, not by filename. Several reproducers were promoted under
        # a name that says what they test rather than which finding produced them
        # (F-0027, F-0030, F-0049, F-0057, F-0059), and a name check would have called
        # those unguarded while the bytes were being replayed all along. The bytes are
        # what the gate feeds; the filename is a label.
        want = {_sha1(os.path.join(d, f)) for f in bins}
        have = {_sha1(os.path.join(corpus, f)) for f in os.listdir(corpus)
                if os.path.isfile(os.path.join(corpus, f)) and not f.endswith(".md")}
        # ...or a vector NAMED for this finding. Both patterns are legitimate and
        # neither test alone covers them: F-0027's bytes were promoted under a
        # descriptive name (content matches, name does not), while F-0003's guard is a
        # cleaner isolate built for the gate rather than the original reproducer (name
        # matches, content does not — engine/structured/isolates.py exists for exactly
        # that). What must never pass is neither.
        stem = fid.replace("-", "")
        named = any(f.startswith(stem) for f in os.listdir(corpus))
        if not (want & have) and not named:
            errors.append(
                f"{fid}: Guard says {decl}, but neither its {len(bins)} reproducer(s) nor "
                f"a {stem}_* vector is in there — the declaration is the promise, the "
                "corpus is the guard")
    elif decl.lower().startswith("none"):
        reason = decl.split("—", 1)[-1].strip() if "—" in decl else ""
        if not reason:
            errors.append(
                f"{fid}: Guard says none with no reason — an unguarded finding needs "
                "the why written down, or it reads as an oversight")
    else:
        name = decl.split()[0]
        if not (os.path.exists(os.path.join(ROOT, "engine", "structured", name + ".py"))
                or os.path.exists(os.path.join(ROOT, "scripts", name + ".sh"))
                or os.path.exists(os.path.join(ROOT, "oracle", name + ".py"))):
            errors.append(
                f"{fid}: Guard names `{name}`, which is neither a sweep axis "
                "(engine/structured/<name>.py), an oracle, nor a gate (scripts/<name>.sh)")


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
        # A finding that is no longer open must say what re-checks it.
        if state in (RESOLVED, BYDESIGN):
            check_guard(fid, dirs[fid], open(notes, encoding="utf-8").read(), errors)

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
