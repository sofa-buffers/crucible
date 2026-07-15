#!/usr/bin/env python3
"""Cluster differential divergences into root causes.

The pacemaker + comparator produce one divergence row per (input, driver-pair);
over a big corpus that is thousands of rows for a handful of actual bugs. This
groups them by ROOT CAUSE.

Key idea: for a divergent input, partition the drivers into equivalence classes by
identical output, then drop the exact bytes and keep only the *shape* — which
driver-set landed in each class and whether it accepted / rejected / crashed. Two
inputs with the same shape share a root cause (e.g. every "C/C++ keep raw bytes |
Java/C# emit U+FFFD | Go/TS/Zig/Python reject" input is the same UTF-8 bug,
whatever the string was). Clusters are ranked by size with a minimal
representative each.

Usage (same driver args as comparator.py):
    cluster.py --corpus <dir> --driver <name>:<path> [--driver ...] [--top N]
"""
import argparse
import sys

from comparator import (run_driver, parse, read_corpus, CRASH, TIMEOUT,
                        default_timeout)


def run_driver_recover(path, corpus, timeout=None):
    """Like run_driver but recover past a crash OR a hang: a driver that dies or
    hangs at input k has its line marked CRASH/TIMEOUT and is re-run on k+1.. so
    later inputs are not lost."""
    lines = []
    start = 0
    while start < len(corpus):
        sub = corpus[start:]
        ls, fail_idx, _, _ = run_driver(path, sub, timeout)
        if fail_idx is None:
            lines.extend(ls)
            break
        lines.extend(ls[:fail_idx])
        lines.append(ls[fail_idx])   # CRASH or TIMEOUT sentinel
        start += fail_idx + 1
    return lines


def verdict_tag(line):
    if line == CRASH:
        return "CRASH", ""
    if line == TIMEOUT:
        return "TIMEOUT", ""
    v, p = parse(line)
    return {"A": "accept", "R": "reject"}.get(v, v), p


def signature(outputs):
    """(cluster-key, groups) for a divergent input, or None if all agree.
    groups: {output_line: [driver_names]}. key drops the accepted value, keeping
    only (driver-set, verdict) per group."""
    groups = {}
    for name, line in outputs:
        if line is None:
            continue  # unknown (driver died earlier and we couldn't recover)
        groups.setdefault(line, []).append(name)
    if len(groups) <= 1:
        return None
    key = frozenset(
        (frozenset(names), verdict_tag(line)[0]) for line, names in groups.items()
    )
    return key, groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--driver", action="append", required=True)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-driver wall-clock budget in seconds "
                         "(default max(30, 0.25 x corpus size))")
    args = ap.parse_args()

    corpus = read_corpus(args.corpus)
    if not corpus:
        sys.stderr.write(f"[cluster] empty corpus: {args.corpus}\n")
        return 2
    timeout = args.timeout if args.timeout is not None else default_timeout(corpus)

    drivers = []
    for spec in args.driver:
        name, _, path = spec.partition(":")
        drivers.append((name, run_driver_recover(path, corpus, timeout)))

    clusters = {}  # key -> {count, min:(size, seed, groups)}
    for i, (seed, data) in enumerate(corpus):
        outputs = [(nm, ln[i] if i < len(ln) else None) for nm, ln in drivers]
        res = signature(outputs)
        if res is None:
            continue
        key, groups = res
        c = clusters.setdefault(key, {"count": 0, "min": (1 << 62, None, None)})
        c["count"] += 1
        if len(data) < c["min"][0]:
            c["min"] = (len(data), seed, groups)

    ranked = sorted(clusters.items(), key=lambda kv: -kv[1]["count"])
    total = sum(c["count"] for _, c in ranked)
    agree = len(corpus) - total
    print(f"{len(corpus)} inputs: {agree} agree, {total} diverge "
          f"→ {len(ranked)} root-cause cluster(s)\n")

    for n, (key, c) in enumerate(ranked[:args.top], 1):
        size, seed, groups = c["min"]
        print(f"CLUSTER {n}  ({c['count']} input(s))  rep {seed[:12]} ({size} B)")
        # largest camps first; rejects/crashes read naturally at the bottom
        for line, names in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            tag, val = verdict_tag(line)
            if tag == "accept":
                val = "wire=" + (val[:28] + "…" if len(val) > 28 else val)
            elif tag == "reject":
                val = val
            print(f"    {tag:7} {', '.join(sorted(names)):46} {val}")
        print()

    if len(ranked) > args.top:
        print(f"… {len(ranked) - args.top} smaller cluster(s) not shown (--top)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
