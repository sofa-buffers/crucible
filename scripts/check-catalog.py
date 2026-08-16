#!/usr/bin/env python3
"""Catalog gate — the write-ups are the data, and this asserts what generation cannot.

`results/FINDINGS.md` is **generated** from `findings/*/NOTES.md` by
`scripts/gen-findings.py`. That removes a whole class of check rather than automating it:
the index can no longer disagree with a write-up about a state, a pairing or a ticket,
because it no longer holds those facts — it derives them. What used to be 46 drifted
declarations (2026-08-03) is unreachable now.

What is left to assert, and why each still needs asserting:

  * **the index is current.** Generation only helps if the committed file is what the
    write-ups produce today. Same shape as `materialize.sh`'s check on the generated
    schema table: regenerate, compare, fail with the command that fixes it.
  * **every write-up declares a state.** The generator cannot invent one, and a missing
    `**Status:**` would otherwise fail deep inside rendering.
  * **every closed finding declares what re-checks it** — the `**Guard:**` line. This is
    the one fact with no other home: promotion into a gate corpus happens weeks after the
    find and produces no visible change (a converged vector in a green gate leaves it
    green), so it was skipped 13 times before this check existed.

Run: `python3 scripts/check-catalog.py`   (exit 1 on any failure)
"""

import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR = os.path.join(ROOT, "scripts", "gen-findings.py")
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


def main():
    errors = []

    # --- the index is a view: it must be what the write-ups produce right now --------
    gen = subprocess.run([sys.executable, GENERATOR, "--check"],
                         capture_output=True, text=True)
    sys.stdout.write(gen.stdout)
    if gen.returncode != 0:
        sys.stderr.write(gen.stderr)
        errors.append("results/FINDINGS.md is stale — regenerate it "
                      "(python3 scripts/gen-findings.py)")

    # --- per write-up: a declared state, and a declared guard where one is owed ------
    n = 0
    for folder in sorted(os.listdir(FINDINGS_DIR)):
        notes = os.path.join(FINDINGS_DIR, folder, "NOTES.md")
        if not os.path.exists(notes):
            continue
        n += 1
        fid = folder[:6]
        text = open(notes, encoding="utf-8").read()
        m = re.search(r"^\*\*Status:\*\*(.*)$", text, re.M)
        if not m:
            errors.append(f"{fid}: NOTES.md has no `**Status:**` line")
            continue
        state = token(m.group(1))
        if state is None:
            errors.append(f"{fid}: NOTES.md `**Status:**` declares no state (✅, 🔴 or ⚪)")
            continue
        if state in (RESOLVED, BYDESIGN):
            check_guard(fid, folder, text, errors)

    if errors:
        print(f"catalog check: {len(errors)} failure(s)\n", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print("\nThe write-ups own the facts; results/FINDINGS.md is generated from them.",
              file=sys.stderr)
        return 1
    print(f"catalog check: OK — {n} write-up(s), index current, every closed finding "
          "declares its guard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
