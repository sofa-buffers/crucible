#!/usr/bin/env python3
"""Crucible differential comparator.

Feeds the same corpus to every replay driver (persistent mode,
drivers/common/CONTRACT.md), collects each driver's canonical line per input
(oracle/canonical.md), and reports where implementations DISAGREE — the oracle
of the whole project.

Usage:
    comparator.py --corpus <dir> --driver <name>:<path> [--driver ...] \
                  [--policy <policy.yaml>]

Exit status: 0 = all implementations agree (modulo soft axes); 1 = a hard
divergence (a finding); 2 = harness error.
"""
import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile


def load_policy(path):
    """Minimal reader for the three comparison axes we need. Avoids a YAML dep."""
    axes = {"verdict": "hard", "accept_value": "hard",
            "incomplete_value": "soft", "reject_class": "soft",
            "limit_class": "soft"}
    if path and os.path.exists(path):
        in_cmp = False
        for line in open(path):
            if re.match(r"^comparison:", line):
                in_cmp = True
                continue
            if in_cmp:
                m = re.match(r"^\s+(verdict|accept_value|incomplete_value|reject_class|limit_class):\s*(hard|soft)", line)
                if m:
                    axes[m.group(1)] = m.group(2)
                elif re.match(r"^\S", line):  # dedent → left the comparison block
                    in_cmp = False
    return axes


def read_corpus(corpus_dir):
    """Return [(name, bytes)] sorted by name for deterministic ordering."""
    items = []
    for name in sorted(os.listdir(corpus_dir)):
        p = os.path.join(corpus_dir, name)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                items.append((name, fh.read()))
    return items


CRASH = "\x00CRASH"      # sentinel: the input a driver died on
TIMEOUT = "\x00TIMEOUT"  # sentinel: the input a driver hung on (a DoS finding)


def default_timeout(corpus):
    """Whole-driver wall-clock budget: generous enough that a green run (a small
    seed corpus finishes in well under a second) never false-trips, but a genuine
    hang trips in tens of seconds. max(30s, 0.25s x corpus size)."""
    return max(30.0, 0.25 * len(corpus))


def run_driver(cmd, corpus, timeout=None):
    """Feed every input framed as <u32 le len><payload>; return one line each.

    stdout/stderr go to temp files (not pipes) so a per-driver ``timeout`` can be
    enforced while still recovering the bytes the driver already flushed — on
    POSIX a killed process's TimeoutExpired does not carry partial output.

    If the driver stops early (fewer lines than inputs), the input at index
    len(lines) is the culprit: a CRASH if the process exited, a TIMEOUT if it was
    killed for hanging. Both mark that slot and leave the rest None (unknown).
    Returns (lines, fail_index_or_None, stderr_tail, kind) where kind is None,
    'crash', or 'timeout'."""
    stream = b"".join(struct.pack("<I", len(data)) + data for _, data in corpus)
    n = len(corpus)
    timed_out = False
    with tempfile.TemporaryFile() as outf, tempfile.TemporaryFile() as errf:
        try:
            subprocess.run([cmd], input=stream, stdout=outf, stderr=errf,
                           timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True  # process killed; outf holds whatever it flushed
        outf.seek(0)
        lines = outf.read().decode("utf-8", "replace").splitlines()
        errf.seek(0)
        stderr_tail = "\n".join(errf.read().decode("utf-8", "replace")
                                .splitlines()[-8:])

    # All lines present ⇒ success, even if a post-last-input slow exit tripped the
    # timeout (nothing to localize; the comparison has every verdict it needs).
    if len(lines) >= n:
        return lines[:n], None, stderr_tail, None

    fail_idx = len(lines)
    kind = "timeout" if timed_out else "crash"
    sentinel = TIMEOUT if timed_out else CRASH
    padded = lines + [sentinel] + [None] * (n - fail_idx - 1)
    return padded[:n], fail_idx, stderr_tail, kind


def parse(line):
    """(verdict, payload): ('A', hex), ('I', hex-or-empty), ('R', class), or
    ('L', class-or-empty).

    Verdicts per oracle/canonical.md: A=complete, I=incomplete (decode ended
    mid-message, MESSAGE_SPEC §7 — not an error), R=reject (INVALID), L=limit
    exceeded (a configured receiver-side cap, generator#102 — a policy rejection
    distinct from R, appears in limit mode only). These are distinct hard verdict
    values; disagreeing on which is a verdict divergence."""
    if line.startswith("A"):
        return ("A", line[1:].strip())
    if line.startswith("I"):
        return ("I", line[1:].strip())
    if line.startswith("R"):
        return ("R", line[1:].strip())
    if line.startswith("L"):
        return ("L", line[1:].strip())
    return ("?", line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--driver", action="append", required=True,
                    help="name:path, repeatable")
    ap.add_argument("--policy", default=None)
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-driver wall-clock budget in seconds "
                         "(default max(30, 0.25 x corpus size))")
    args = ap.parse_args()

    axes = load_policy(args.policy)
    corpus = read_corpus(args.corpus)
    if not corpus:
        sys.stderr.write(f"[harness] empty corpus: {args.corpus}\n")
        return 2
    timeout = args.timeout if args.timeout is not None else default_timeout(corpus)

    drivers = []  # (name, [lines])
    hard = 0
    crashed = timed = 0  # counts for the summary
    for spec in args.driver:
        name, _, path = spec.partition(":")
        lines, fail_idx, stderr_tail, kind = run_driver(path, corpus, timeout)
        drivers.append((name, lines))
        if fail_idx is not None:
            seed = corpus[fail_idx][0]
            hard += 1
            if kind == "timeout":
                timed += 1
                got = fail_idx  # lines produced before the hang
                print(f"[TIMEOUT] driver {name} hung after {timeout:g}s "
                      f"(produced {got}/{len(corpus)} lines; culprit ≈ input "
                      f"'{seed}', #{fail_idx})")
            else:
                crashed += 1
                print(f"[CRASH] driver {name} died on input '{seed}' "
                      f"(input #{fail_idx} of {len(corpus)})")
            if stderr_tail:
                print("        " + stderr_tail.replace("\n", "\n        "))

    soft = 0
    # Reference = first driver that did NOT crash/hang on a given input.
    for i, (seed, _) in enumerate(corpus):
        present = [(nm, ln[i]) for nm, ln in drivers
                   if ln[i] not in (None, CRASH, TIMEOUT)]
        if len(present) < 2:
            continue
        ref_name, ref_line = present[0]
        rv, rp = parse(ref_line)
        for name, line in present[1:]:
            v, p = parse(line)
            axis = reason = None
            if v != rv:
                axis, reason = "verdict", f"{ref_name}={rv!r} {name}={v!r}"
            elif rv == "A" and p != rp:
                axis, reason = "accept_value", f"{ref_name}: {rp}\n        {name}: {p}"
            elif rv == "I" and p != rp:
                axis, reason = "incomplete_value", f"{ref_name}: {rp}\n        {name}: {p}"
            elif rv == "R" and p != rp:
                axis, reason = "reject_class", f"{ref_name}={rp} {name}={p}"
            elif rv == "L" and p != rp:
                axis, reason = "limit_class", f"{ref_name}={rp} {name}={p}"
            if axis:
                sev = axes.get(axis, "hard")
                tag = "DIVERGENCE" if sev == "hard" else "warning"
                print(f"[{tag}] {seed}  ({axis})\n        {reason}")
                if sev == "hard":
                    hard += 1
                else:
                    soft += 1

    n = len(corpus)
    d = len(drivers)
    names = ", ".join(name for name, _ in drivers)
    print(f"\n{n} inputs × {d} drivers ({names}): "
          f"{hard} divergence(s) ({crashed} crash, {timed} timeout), "
          f"{soft} warning(s)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
