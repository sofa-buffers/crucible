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

**Every applied deletion has been observed to hold the target — no exceptions.** That
sounds like a truism and was not one until 2026-08-16. Three things could break it, and
all three are closed now:

  * a driver that hangs or dies answers the inputs before the culprit and leaves the
    REST OF THE BATCH unanswered. Unanswered slots used to collapse into the same bucket
    as a hang, so after one hang every later candidate in that batch matched a TIMEOUT
    target exactly — "holding" it without ever being measured. Unanswered now yields
    None and can match nothing;
  * the single-deletion fallback was applied WITHOUT being checked on its own, having
    only ever been seen inside the combined batch. It is verified now, and the round
    stops if it does not hold;
  * a target rests on a hang or a crash, which is not a property of the bytes and can
    stop reproducing after the first deletion. Such a target is now re-measured
    (--confirm, default 2 extra times) and the run REFUSES rather than shrink against
    something that has gone away.

The failure that motivated this produced a wrong artifact, not a weak one: two
reproducers of two different TIMEOUT camps both minimized to the same 1-byte input,
which was the representative of an unrelated, long-known camp.

One cost is worth knowing before you hit it: minimizing a TIMEOUT target is SLOW. A hang
ends the batch it occurs in, so every candidate after it is unobserved and the run
degrades to roughly one candidate per batch — the 100x batching win does not apply. That
is the honest price of not accepting unmeasured deletions, and it only applies to targets
that rest on a hang.

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
from comparator import run_driver, parse, CRASH, TIMEOUT  # noqa: E402

_calls = 0      # batch runs (each one is 13 process spawns)
_inputs = 0     # candidates checked


# A driver that crashes or hangs answers for the inputs BEFORE the culprit, marks the
# culprit, and leaves the rest of the batch unanswered (comparator.run_driver). Those
# unanswered slots are not observations, and must never compare equal to anything.
UNOBSERVED = None


def partitions(drivers, datas, timeout=None):
    """One camp signature per input, or None where the batch could not observe it.

    Soft payload differences (agreed I/R with differing bytes) are folded out: they are
    policy-soft per oracle/policy.yaml, and holding them fixed would over-constrain the
    shrink — the minimizer would refuse deletions that change nothing anyone treats as a
    divergence.

    **A driver that did not answer yields None for that candidate, and a crash and a hang
    are distinct cells.** Both used to collapse into the same `("?", "")` bucket as an
    unanswered slot, and that one line produced a wrong artifact rather than a weak one:
    when a driver hangs on candidate 3 of a batch, candidates 4..N are unanswered, so they
    matched a TIMEOUT target exactly — deletions "held" that were never measured at all.
    Two reproducers of two different TIMEOUT camps minimized to the same 1-byte input on
    2026-08-15, each naming a finding it had nothing to do with."""
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
            line = outs[name][i]
            if line is None:                       # this driver never got here
                cell = None
                break
            if line == TIMEOUT:
                cell[name] = ("TIMEOUT", "")
            elif line == CRASH:
                cell[name] = ("CRASH", "")
            else:
                v, pay = parse(line)
                cell[name] = (v, pay if v == "A" else "")
        if cell is None:
            sigs.append(UNOBSERVED)
            continue
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
            ok = [i for (i, _), s in zip(cands, sigs) if s is not UNOBSERVED
                  and s == target]
            if not ok:
                break
            merged = cur
            for i in sorted(ok, reverse=True):                # back to front: indices hold
                merged = merged[:i] + merged[i + n:]
            if merged and partitions(drivers, [merged], timeout)[0] == target:
                cur = merged
            else:
                # Fall back to the first deletion alone — but VERIFY it alone first.
                # It was only ever seen inside the combined batch, and this line used to
                # apply it unchecked, which is how a run could keep shrinking after the
                # target had already stopped reproducing.
                single = cur[:ok[0]] + cur[ok[0] + n:]
                if single and partitions(drivers, [single], timeout)[0] == target:
                    cur = single
                else:
                    print(f"   n={n:<5} -> stop: no deletion holds the target on its own",
                          file=log, flush=True)
                    break
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
    ap.add_argument("--confirm", type=int, default=2,
                    help="extra measurements of the input before shrinking, when the "
                         "target rests on a TIMEOUT or CRASH (default 2)")
    args = ap.parse_args()

    drivers = [tuple(d.split(":", 1)) for d in args.driver]
    raw = open(args.input, "rb").read()
    t0 = time.time()
    target = partitions(drivers, [raw], args.timeout)[0]
    if target is UNOBSERVED:
        print("minimize: the input could not be measured — a driver stopped before "
              "answering it. Nothing to minimize against.", file=sys.stderr)
        return 2

    # A target that rests on a hang or a crash is only as stable as the machine. A stall
    # is not a property of the bytes: it can stop reproducing after the first deletion,
    # and then every later comparison is against a target that no longer exists. Confirm
    # it before shrinking, and refuse rather than produce an artifact for a different
    # finding than the one asked about.
    unstable = sorted({key[0] for _, key in target} & {"TIMEOUT", "CRASH"})
    if unstable:
        print(f"minimize: the target rests on {', '.join(unstable)} — re-measuring "
              f"{args.confirm}x before shrinking", file=sys.stderr)
        for k in range(args.confirm):
            again = partitions(drivers, [raw], args.timeout)[0]
            if again != target:
                print(f"minimize: NOT REPRODUCIBLE — measurement {k + 2} of the same "
                      f"input gave a different partition. A {'/'.join(unstable)} target "
                      "that comes and goes cannot be minimized against: the result would "
                      "name whichever camp happened to survive, not the one you started "
                      "from. Re-run the input on a quiet machine, or raise --timeout.",
                      file=sys.stderr)
                return 3
        print(f"minimize: target reproduced {args.confirm + 1}x — continuing, but a "
              f"{'/'.join(unstable)} reproducer stays sensitive to load",
              file=sys.stderr)

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
