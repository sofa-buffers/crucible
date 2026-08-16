#!/usr/bin/env python3
"""Delta-minimize one input while its CAMP PARTITION is unchanged.

The Crucible rule for a finding (see `findings/*/NOTES.md`): shrink only while the exact
partition of drivers into output classes stays identical. Anything that changes the
partition has changed the finding, not minimized it. A 300-byte reproducer gets an issue
closed; an 11-byte one with three controls gets it fixed the same day.

**Batched, and that is the whole design.** A check costs almost pure process startup, not
computation — measured over this repo's drivers:

    1 input    -> 1507 ms per input   (java alone 441 ms of JVM boot; py/cs/ts ~200 ms each)
    100 inputs ->   10 ms per input

Testing a hundred candidates is *cheaper* than testing one. A per-candidate minimizer pays
that 1.5 s for every shrink attempt and spends its whole run in process teardown at ~3 %
CPU — on a 1132-byte input that is hours. This one puts every candidate of a round into a
single corpus: the same input minimized in 2m15 instead.

It is additionally optimistic: when several deletions of a round each pass alone, they are
first tried together (back to front, so indices stay valid) and only applied singly if the
combination fails. Deletions rarely interact, so that usually wins another order.

Usage (the driver roster comes from run.sh, as cluster.py's does — one roster, one place):

    MINIMIZE=path/to/input.bin ./scripts/run.sh
    # or directly:
    python3 oracle/minimize.py --input x.bin --output y.bin --driver c:... --driver go:...
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comparator import run_driver, parse  # noqa: E402

_calls = 0      # batch runs (each one is 13 process spawns)
_inputs = 0     # candidates checked


def partitions(drivers, datas, timeout=None):
    """One camp signature per input.

    Soft payload differences (agreed I/R with differing bytes) are folded out: they are
    policy-soft per oracle/policy.yaml, and holding them fixed would over-constrain the
    shrink — the minimizer would refuse deletions that change nothing anyone treats as a
    divergence."""
    global _calls, _inputs
    if not datas:
        return []
    _calls += 1
    _inputs += len(datas)
    corpus = [(f"c{i}", d) for i, d in enumerate(datas)]
    outs = {}
    for name, path in drivers:
        lines, *_ = run_driver(path, corpus, timeout=timeout)
        outs[name] = lines
    sigs = []
    for i in range(len(datas)):
        cell = {}
        for name, _ in drivers:
            v, pay = parse(outs[name][i] or "")
            cell[name] = (v, pay if v == "A" else "")
        groups = {}
        for name, key in cell.items():
            groups.setdefault(key, []).append(name)
        sigs.append(tuple(sorted((tuple(sorted(v)), k) for k, v in groups.items())))
    return sigs


def minimize(drivers, data, target, timeout=None, log=sys.stderr):
    cur = data
    n = max(len(cur) // 2, 1)
    while n >= 1:
        while True:
            starts = list(range(0, len(cur), n))
            cands = [(i, cur[:i] + cur[i + n:]) for i in starts]
            cands = [(i, c) for i, c in cands if c]           # never shrink to empty
            if not cands:
                break
            sigs = partitions(drivers, [c for _, c in cands], timeout)
            ok = [i for (i, _), s in zip(cands, sigs) if s == target]
            if not ok:
                break
            merged = cur
            for i in sorted(ok, reverse=True):                # back to front: indices hold
                merged = merged[:i] + merged[i + n:]
            if merged and partitions(drivers, [merged], timeout)[0] == target:
                cur = merged
            else:
                cur = cur[:ok[0]] + cur[ok[0] + n:]           # conservative: just the first
            print(f"   n={n:<5} -> {len(cur)} B "
                  f"({len(ok)}/{len(cands)} deletion(s) held)", file=log, flush=True)
        n //= 2
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--driver", action="append", required=True,
                    help="name:path, repeatable — as cluster.py takes it")
    ap.add_argument("--timeout", type=float, default=600.0,
                    help="per-driver wall-clock budget in seconds")
    args = ap.parse_args()

    drivers = [tuple(d.split(":", 1)) for d in args.driver]
    raw = open(args.input, "rb").read()
    t0 = time.time()
    target = partitions(drivers, [raw], args.timeout)[0]

    print(f"{os.path.basename(args.input)}: {len(raw)} B", file=sys.stderr)
    for camp, key in target:
        val = (" " + key[1][:20]) if key[1] else ""
        print(f"   {key[0]}{val}: {','.join(camp)}", file=sys.stderr)
    print(file=sys.stderr)

    out = minimize(drivers, raw, target, args.timeout)
    dt = time.time() - t0
    print(f"\n-> {len(out)} B: {out.hex()}")
    print(f"   {dt:.1f} s, {_calls} batch run(s), {_inputs} candidate(s) "
          f"({_inputs / max(_calls, 1):.0f} per run)", file=sys.stderr)
    with open(args.output, "wb") as fh:
        fh.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
