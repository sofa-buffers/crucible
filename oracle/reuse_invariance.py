#!/usr/bin/env python3
"""Reuse-invariance oracle — a decode into a reused destination against a fresh one.

Most backends' generated decode now writes into a destination the caller owns and may
reuse across messages (`try_decode(data, &mut out)`, `Probe__TryDecode(data, out)`,
`TryDecode(data, msg)`, `tryDecode(data, out)`, ...). Each documents the same contract:
the destination is reset first and **reads as a fresh decode** of the new bytes —
nothing of the message it held before survives, on a refusal included. Most of them
also keep the old storage (strings, blobs, arrays, rows) and write into it, which is
exactly where a stale element, a stale length or a stale union option can leak through.

Every other gate feeds each record into a fresh message (CONTRACT.md, "Decode core
requirements"), so that path is never taken. `SOFAB_REUSE=1` opens it: the driver holds
ONE destination for the whole process and decodes every record into it through the
generated reuse entry point. The canonical line for each record must then equal the line
the same driver prints with a fresh destination.

Like the chunk and encode gates this is **not differential** — a driver against itself —
so it catches a defect the whole family shares, and drivers join one at a time.

Three streams per driver, each in both output forms (round-trip and SOFAB_MATERIALIZE):

1. **primed** — every corpus record is preceded by a value-rich primer (the structured
   corpus by default), so the destination holds full strings, arrays and nested rows
   when the record arrives. This is the receive-loop case the reuse exists for.
2. **sequential** — the corpus in its own order, so a record also follows a rejected
   or incomplete one and inherits whatever that refusal left in the destination.
3. **reversed** — the same, backwards, so each pair is also seen the other way round.

Plus the contract's two checks on the driver itself:

* **the announcement** — under `SOFAB_REUSE=1` stderr must carry `reuse=1`; a driver
  that ignores the variable emits byte-identical output, so agreement alone proves
  nothing;
* **the hard-fail** — a roster row whose backend has no reuse entry point (`meta`
  `reuse_decode`) must exit 3 when asked, never fall back to a fresh destination.
"""

import argparse
import os
import struct
import subprocess
import sys

import roster

ROOT = roster.ROOT
ROWS = {name: (builder, arg, binary)
        for name, builder, arg, _, binary in roster.rows(roster.gate_tag())}

FEED_TIMEOUT = int(os.environ.get("REUSE_FEED_TIMEOUT", "180"))


def load(d):
    files = sorted(f for f in os.listdir(d) if not f.endswith(".md") and f != ".gitkeep")
    return files, [open(os.path.join(d, f), "rb").read() for f in files]


def run(path, inputs, env=None):
    """Run a driver over `inputs`; returns (lines, returncode, stderr)."""
    blob = b"".join(struct.pack("<I", len(d)) + d for d in inputs)
    e = dict(os.environ)
    for k in ("SOFAB_REUSE", "SOFAB_SPLIT", "SOFAB_CHUNK", "SOFAB_CHUNK_SCRUB"):
        e.pop(k, None)
    if env:
        e.update(env)
    p = subprocess.run([path], input=blob, capture_output=True, env=e,
                       timeout=FEED_TIMEOUT)
    return (p.stdout.decode(errors="replace").splitlines(), p.returncode,
            p.stderr.decode(errors="replace").strip())


def streams(files, inputs, pfiles, primers, same):
    """(label, [(name, bytes)]) for the three reuse streams."""
    recs = list(zip(files, inputs))
    prim = list(zip(pfiles, primers))
    primed = []
    for i, r in enumerate(recs):
        # When the corpus IS the primer set, shift by one so no record primes itself.
        primed.append(prim[(i + 1) % len(prim)] if same else prim[i % len(prim)])
        primed.append(r)
    return [("primed", primed), ("sequential", recs), ("reversed", recs[::-1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--primers", required=True,
                    help="corpus of value-rich messages decoded before each record")
    ap.add_argument("--drivers", required=True,
                    help="comma/space-separated driver names that honour SOFAB_REUSE")
    ap.add_argument("--absent", default="",
                    help="roster names whose backend has no reuse entry point; each "
                         "must exit 3 under SOFAB_REUSE=1")
    args = ap.parse_args()

    names = [n for n in args.drivers.replace(",", " ").split() if n]
    absent = [n for n in args.absent.replace(",", " ").split() if n]
    unknown = [n for n in names + absent if n not in ROWS]
    if unknown:
        print(f"unknown driver(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    files, inputs = load(args.corpus)
    pfiles, primers = load(args.primers)
    if not inputs or not primers:
        print("empty corpus or primer set", file=sys.stderr)
        return 2
    same = os.path.realpath(args.corpus) == os.path.realpath(args.primers)
    plan = streams(files, inputs, pfiles, primers, same)

    failures = 0
    for name in names:
        builder, arg, path = ROWS[name]
        if not roster.reuse_decode(builder, arg):
            print(f"  [{name}] meta's reuse_decode does not list this row — it cannot "
                  "be a participant", file=sys.stderr)
            failures += 1
            continue
        bad = tried = 0
        for form, fenv in (("round-trip", {}), ("materialize", {"SOFAB_MATERIALIZE": "1"})):
            # The baseline is the driver's own fresh-destination output for every
            # record either stream uses, keyed by record so each stream can look it up.
            allrecs = dict(zip(files, inputs))
            allrecs.update(zip(pfiles, primers))
            keys = list(allrecs)
            base, rc, err = run(path, [allrecs[k] for k in keys], fenv)
            if rc != 0 or len(base) != len(keys):
                print(f"  [{name}] {form} baseline failed (rc={rc}, {len(base)} lines): "
                      f"{err}", file=sys.stderr)
                bad += 1
                continue
            want = dict(zip(keys, base))
            for label, recs in plan:
                tried += 1
                lines, rc, err = run(path, [d for _, d in recs],
                                     dict(fenv, SOFAB_REUSE="1"))
                if rc != 0 or len(lines) != len(recs):
                    print(f"  [{name}] {form}/{label}: rc={rc}, {len(lines)} lines, "
                          f"expected {len(recs)}: {err}", file=sys.stderr)
                    bad += 1
                    continue
                if "reuse=1" not in err:
                    print(f"  [{name}] {form}/{label}: stderr does not announce reuse=1 "
                          "— stdout cannot tell honouring the variable from ignoring "
                          f"it. stderr was: {err!r}", file=sys.stderr)
                    bad += 1
                    continue
                for i, ((rname, _), got) in enumerate(zip(recs, lines)):
                    if got != want[rname]:
                        prev = recs[i - 1][0] if i else "(none)"
                        print(f"  [{name}] {form}/{label}: {rname} after {prev}: "
                              f"fresh={want[rname]!r} reused={got!r}", file=sys.stderr)
                        bad += 1
        status = "OK" if not bad else "FAIL"
        print(f"[{name}] {len(inputs)} input(s), {len(primers)} primer(s) x {tried} "
              f"stream(s) — {bad} mismatch(es)  [{status}]")
        failures += bad

    for name in absent:
        _, _, path = ROWS[name]
        _, rc, err = run(path, inputs[:1], {"SOFAB_REUSE": "1"})
        if rc != 3:
            print(f"  [{name}] SOFAB_REUSE=1: no reuse entry point (meta) but the driver "
                  f"exited {rc}, not 3 — a silent fallback to a fresh destination "
                  f"reports a mode as passing that never ran: {err}", file=sys.stderr)
            failures += 1
        else:
            print(f"[{name}] no reuse entry point — refuses SOFAB_REUSE=1 (exit 3)  [OK]")

    print(f"\nTOTAL: {failures} reuse-invariance mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
