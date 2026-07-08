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


def load_policy(path):
    """Minimal reader for the three comparison axes we need. Avoids a YAML dep."""
    axes = {"verdict": "hard", "accept_value": "hard", "reject_class": "soft"}
    if path and os.path.exists(path):
        in_cmp = False
        for line in open(path):
            if re.match(r"^comparison:", line):
                in_cmp = True
                continue
            if in_cmp:
                m = re.match(r"^\s+(verdict|accept_value|reject_class):\s*(hard|soft)", line)
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


def run_driver(cmd, corpus):
    """Feed every input framed as <u32 le len><payload>; return one line each."""
    stream = b"".join(struct.pack("<I", len(data)) + data for _, data in corpus)
    proc = subprocess.run([cmd], input=stream, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    if len(lines) != len(corpus):
        sys.stderr.write(
            f"[harness] driver {cmd} returned {len(lines)} lines for "
            f"{len(corpus)} inputs (exit {proc.returncode})\n"
            f"{proc.stderr.decode('utf-8', 'replace')}\n")
        raise SystemExit(2)
    return lines


def parse(line):
    """(verdict, payload): ('A', fields-string) or ('R', class)."""
    if line.startswith("A"):
        return ("A", line[1:].strip())
    if line.startswith("R"):
        return ("R", line[1:].strip())
    return ("?", line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--driver", action="append", required=True,
                    help="name:path, repeatable")
    ap.add_argument("--policy", default=None)
    args = ap.parse_args()

    axes = load_policy(args.policy)
    corpus = read_corpus(args.corpus)
    if not corpus:
        sys.stderr.write(f"[harness] empty corpus: {args.corpus}\n")
        return 2

    drivers = []  # (name, [lines])
    for spec in args.driver:
        name, _, path = spec.partition(":")
        drivers.append((name, run_driver(path, corpus)))

    hard = 0
    soft = 0
    ref_name, ref_lines = drivers[0]

    for i, (seed, _) in enumerate(corpus):
        rv, rp = parse(ref_lines[i])
        for name, lines in drivers[1:]:
            v, p = parse(lines[i])
            axis = reason = None
            if v != rv:
                axis, reason = "verdict", f"{ref_name}={rv!r} {name}={v!r}"
            elif rv == "A" and p != rp:
                axis, reason = "accept_value", f"{ref_name}: {rp}\n        {name}: {p}"
            elif rv == "R" and p != rp:
                axis, reason = "reject_class", f"{ref_name}={rp} {name}={p}"
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
          f"{hard} divergence(s), {soft} warning(s)")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
