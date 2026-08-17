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



def sig_text(key):
    """A stable, diffable text form of a cluster's camp partition.

    The signature is *only* the (driver-set, verdict) partition — deliberately not the
    representative or the accepted bytes, so it survives the corpus changing under it.
    Two runs that disagree on which input represents a cluster still agree on this."""
    return " | ".join(sorted(
        f"{verdict}:{','.join(sorted(names))}" for names, verdict in key))


def parse_sig(text):
    """A signature's text form back into {(verdict, frozenset(drivers))}."""
    camps = set()
    for part in text.split(" | "):
        verdict, _, names = part.partition(":")
        camps.add((verdict.strip(), frozenset(n.strip() for n in names.split(",") if n.strip())))
    return frozenset(camps)


def project(partition, keep):
    """The partition as it would look if only `keep` had been running.

    Drivers outside `keep` are dropped and camps that become empty disappear. This is
    what lets a baseline written before a driver existed still match: the drivers it
    knows about are still split the same way."""
    out = set()
    for verdict, names in partition:
        common = frozenset(names) & keep
        if common:
            out.add((verdict, common))
    return frozenset(out)


def camp_matches(camp, base_sig):
    """Does this camp match a baseline row, ignoring drivers the row never named?

    Compared on the intersection of the two driver sets, so neither an added driver nor
    a retired one invalidates the row — while a driver that CHANGED CAMP still does,
    because it is inside both sets and lands on the other side of the split.

    Returns None on no match, otherwise the drivers the row did not know about. An empty
    intersection is not a match: a camp made only of drivers this row never heard of is
    genuinely new information (a fresh driver alone in a camp is exactly the divergence
    worth seeing), and must not be swallowed by a row it has nothing in common with."""
    base = parse_sig(base_sig)
    base_drivers = frozenset().union(*(names for _, names in base))
    camp_drivers = frozenset().union(*(frozenset(names) for names, _ in camp))
    common = base_drivers & camp_drivers
    if not common:
        return None
    cur = project([(v, frozenset(n)) for n, v in camp], common)
    if cur != project(base, common):
        return None
    # The projection alone is too generous, and the first test of it said so: a driver
    # this row never heard of, sitting ALONE in a camp, projects to nothing and the row
    # matches — reporting "it joined an existing camp" about a driver that agrees with
    # nobody. That is the divergence most worth seeing on the day a driver is added.
    # So an unknown driver counts as accounted for only where it shares a camp with a
    # driver the row does name.
    for names, _ in camp:
        if not (frozenset(names) & base_drivers):
            return None
    return camp_drivers - base_drivers


def load_baseline(path):
    """(camps, roster) — accounted-for signatures, and the drivers they were recorded
    against.

    A camp is in here only once it is *explained* — a catalogued finding, a legal
    divergence, or a benign soft axis. Anything else is reported as NEW and exits
    non-zero, which is what turns an unread nightly artifact into a visible signal.

    Every signature names every driver it knew about, which used to mean one added
    driver invalidated every row at once: on 2026-08-05 that read as "9 NEW CAMPS, 0/9
    accounted for" with zero new root causes. Rows are therefore matched **modulo the
    drivers a row does not name** (see `camp_matches`), so adding a driver no longer
    invalidates anything — only a driver *moving* between camps does.

    The `# roster: a,b,c` line records which drivers the file was written against. It is
    informational now rather than a gate: matching no longer depends on it, but a run
    whose roster differs says so, because "these signatures predate two of your drivers"
    is worth knowing when reading the result. One line, no continuation — an earlier
    version accepted wrapped lines and swallowed every ordinary comment containing a
    comma, inventing driver names out of prose."""
    out, roster = {}, None
    with open(path) as fh:
        for raw in fh:
            if roster is None and raw.lstrip().startswith("# roster:"):
                roster = [n.strip() for n in raw.split(":", 1)[1].split(",") if n.strip()]
                continue
            line = raw.split("#")[0].strip()
            if line:
                out[line] = raw.split("#", 1)[1].strip() if "#" in raw else ""
    return out, roster


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--driver", action="append", required=True)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--baseline", help="file of accounted-for camp signatures; unknown camps are reported and exit non-zero")
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
    baseline, base_roster = load_baseline(args.baseline) if args.baseline else (None, None)
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

    if baseline is None:
        return 0

    # The roster stamp is informational now: matching tolerates a roster change on its
    # own (camp_matches compares on the drivers a row actually names), so a difference
    # here is context for the reader rather than a reason to stop.
    running = sorted(name for name, _ in drivers)
    if base_roster is not None and sorted(base_roster) != running:
        added = [n for n in running if n not in base_roster]
        gone = [n for n in base_roster if n not in running]
        note = ", ".join(filter(None, [("+ " + ", ".join(added)) if added else "",
                                       ("− " + ", ".join(gone)) if gone else ""]))
        print(f"\nnote: these signatures were recorded against a different roster ({note}). "
              "Rows are matched on the drivers they name, so this does not invalidate them "
              "— but where an added driver landed is called out per camp below.")

    # Every camp is either accounted for or new. "Accounted for" means a catalogued
    # finding, a legal divergence or a benign soft axis — see results/known-clusters.txt.
    new_camps, joined = [], []
    for n, (key, c) in enumerate(ranked, 1):
        text = sig_text(key)
        if text in baseline:                       # exact row, nothing to say
            continue
        hit = next((extra for sig in baseline
                    if (extra := camp_matches(key, sig)) is not None), None)
        if hit is None:
            new_camps.append((n, key, c))
        elif hit:
            joined.append((n, sorted(hit), text))
    known = len(ranked) - len(new_camps)
    print(f"\nbaseline: {known}/{len(ranked)} camp(s) accounted for")
    for n, extra, text in joined:
        print(f"  CLUSTER {n}: accounted for, and {', '.join(extra)} joined an existing "
              f"camp — the drivers this row names are still split the same way.\n"
              f"    now: {text}")
    if not new_camps:
        print("no new camp")
        return 0
    print(f"\n*** {len(new_camps)} NEW CAMP(S) — not in {args.baseline} ***\n")
    for n, key, c in new_camps:
        size, seed, _ = c["min"]
        print(f"  CLUSTER {n}  ({c['count']} input(s))  rep {seed} ({size} B)")
        print(f"    {sig_text(key)}\n")
    print("Triage each, then add its signature to the baseline with a label.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
