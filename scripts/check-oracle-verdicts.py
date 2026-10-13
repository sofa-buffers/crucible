#!/usr/bin/env python3
"""Does the comparator actually react to each verdict the canonical form defines?

Every other gate here needs built drivers and a corpus, and reports what the family
does. This one reports what the ORACLE does, by driving `oracle/comparator.py` with
stub drivers that emit chosen canonical lines. No corelib, no schema, no build.

It exists because of `E` (the refused re-encode, generator#656). An `E` is only
reachable from the wire through a decoder bug, so there is no input that produces one
today and no gate that would notice if the plumbing for it were wrong — a verdict whose
handling nothing exercises is decoration. The same reasoning covers the per-line checks
that cannot be reached by agreement either: the forbidden `usage` class, and `E` itself.

    ./scripts/check-oracle-verdicts.py

Exit 0 = every case below reacted as oracle/canonical.md says it must.
"""
import os
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPARATOR = os.path.join(ROOT, "oracle", "comparator.py")
POLICY = os.path.join(ROOT, "oracle", "policy.yaml")

# A stub driver: reads the length-prefixed records (drivers/common/CONTRACT.md) and
# answers with one fixed line per record, so the comparator sees a real driver process.
STUB = """#!/usr/bin/env python3
import struct, sys
line = {line!r}
while True:
    n = sys.stdin.buffer.read(4)
    if len(n) < 4:
        break
    (ln,) = struct.unpack("<I", n)
    sys.stdin.buffer.read(ln)
    sys.stdout.write(line + "\\n")
    sys.stdout.flush()
"""

CASES = [
    # (description, {driver: line}, expect_hard_failure, must_appear_in_output)
    ("unanimous A agrees",
     {"a": "A 00", "b": "A 00"}, False, []),
    ("A vs A with different bytes is an accept_value divergence",
     {"a": "A 00", "b": "A 01"}, True, ["accept_value"]),
    # The reason `E` is not just another verdict: it fails on its own. Two drivers
    # agreeing that they cannot re-encode what they accepted is two drivers with the
    # same bug, and agreement is what green looks like on every other axis.
    ("unanimous E still fails, per line",
     {"a": "E argument", "b": "E argument"}, True, ["encode_refused"]),
    ("E against A is also a verdict divergence",
     {"a": "A 00", "b": "E argument"}, True, ["encode_refused", "verdict"]),
    ("E classes that differ name the encode_class axis",
     {"a": "E argument", "b": "E other"}, True, ["encode_refused", "encode_class"]),
    # The neighbour it must not be confused with: a decode reject is an R, and two
    # drivers agreeing on one is green.
    ("unanimous R agrees",
     {"a": "R invalid_msg", "b": "R invalid_msg"}, False, []),
    ("the abolished `usage` class fails per line, as before",
     {"a": "R usage", "b": "R usage"}, True, ["reject_class_forbidden"]),
    # I has no payload (oracle/canonical.md "The `I` line has no payload"): one that
    # carries one is outside the grammar, and that fails per line — even unanimously.
    ("unanimous bare I agrees",
     {"a": "I", "b": "I"}, False, []),
    ("an I with a payload is a malformed line, even unanimously",
     {"a": "I 00", "b": "I 00"}, True, ["malformed_line"]),
    # The payload is compared inside every verdict camp, not only the reference's: when
    # the reference rejects, two accepters with different values are still a split.
    ("a value split outside the reference's camp is reported",
     {"a": "R invalid_msg", "b": "A 00", "c": "A 01"}, True,
     ["verdict", "accept_value", "outside the reference's camp"]),
]


def main():
    fail = 0
    with tempfile.TemporaryDirectory() as tmp:
        corpus = os.path.join(tmp, "corpus")
        os.makedirs(corpus)
        with open(os.path.join(corpus, "one.bin"), "wb") as fh:
            fh.write(b"\x00")

        for desc, lines, expect_fail, expect_tokens in CASES:
            args = [sys.executable, COMPARATOR, "--corpus", corpus, "--policy", POLICY]
            for name, line in lines.items():
                path = os.path.join(tmp, f"drv-{name}-{abs(hash(line))}.py")
                with open(path, "w") as fh:
                    fh.write(STUB.format(line=line))
                os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
                args += ["--driver", f"{name}:{path}"]
            p = subprocess.run(args, capture_output=True, text=True, timeout=120)
            failed = p.returncode != 0
            missing = [t for t in expect_tokens if t not in p.stdout]
            ok = (failed == expect_fail) and not missing
            print(f"  {'ok  ' if ok else 'FAIL'} {desc}")
            if not ok:
                fail += 1
                print(f"       exit={p.returncode} (wanted "
                      f"{'non-zero' if expect_fail else 'zero'})"
                      + (f", missing from the report: {missing}" if missing else ""))
                print("       " + p.stdout.strip().replace("\n", "\n       "))

    if fail:
        print(f"\n{fail} case(s) where the comparator does not do what "
              "oracle/canonical.md says.")
        return 1
    print("\nevery canonical verdict reacts as specified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
