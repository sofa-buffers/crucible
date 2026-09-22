#!/usr/bin/env python3
"""Family-copies gate — every place Crucible reimplements family logic says why (crucible#192).

A test that brings its own copy of something the family already owns tests its own copy:
it passes while the library is wrong, and it keeps passing after the library changes
underneath it. This repository exists to catch that class of drift, so it must not
quietly produce it. The C anchor already did once — generator#581 widened a boolean
field to `SOFAB_OBJECT_FIELDTYPE_BOOLEAN`, `md_value()` fell into its `default:` arm, and
`materialize.sh` went red with 1904 "divergences" the family never had (crucible#190).

So every such place is listed below with a verdict, and the gate fails on anything that
is neither listed nor honest:

  1. **inventory.** Tracked sources under drivers/ engine/ oracle/ scripts/ are scanned
     for the signatures of a family-logic copy (a wire codec, a descriptor field-type
     dispatch, a materialized-value walk, a wrapper-array placement helper). Every hit
     must be covered by an `INVENTORY` entry naming that file and that signature, and
     every entry must still match something — a stale entry is a claim nobody checks.
     `findings/` is out of scope: its reproducers are frozen evidence for one finding,
     byte builders by nature, and are never run by a gate.
  2. **the C anchor knows every field-type tag.** Every `SOFAB_OBJECT_FIELDTYPE_*` that
     the vendored corelib-c-cpp defines must have a `case` in `md_value()`. A new tag
     then fails here, by name, instead of as a family-wide divergence.
  3. **every walker knows every kind.** Every kind in `oracle/materialized-schema.json`
     must be named by every materialized-value walker. `enum` and `bitfield` are the
     next two (docs/TODO.md); this is what makes a walker that missed one fail by name.
  4. **generated code reaches the corelib layer.** Since generator#587 no backend emits
     its own wrapper-array placement; for every roster driver, its generated probe code
     must call its corelib's collector/placement layer at least once per wrapper field.
     A driver that keeps working while that layer is bypassed tells us nothing.

Checks 2 and 4 read vendor/ and the built drivers, so they need `scripts/bootstrap.sh`
and `scripts/run.sh` first; `--static` runs 1 and 3 only (the catalog job has neither).

Run: `python3 scripts/check-family-copies.py [--static]`   (exit 1 on any failure)
"""

import fnmatch
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = "scripts/check-family-copies.py"

SCOPE = ("drivers/", "engine/", "oracle/", "scripts/")
SOURCE_EXT = (".py", ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".ts", ".js", ".java",
              ".kt", ".cs", ".dart", ".zig")

# The signatures of a family-logic copy. Deliberately narrow: each names a thing the
# family ships, so a hit is worth a sentence of justification rather than noise.
SIGNATURES = {
    # defining a varint/zigzag coder — the wire mechanics the corelibs own
    "wire-codec": re.compile(
        r"(?:\bdef|\bfn|\bfunc|\bfun|\bstatic[\w\s\*]*?)\s+\w*(?:varint|zigzag)\w*\s*\(", re.I),
    # dispatching on corelib-c-cpp's descriptor vocabulary
    "fieldtype-dispatch": re.compile(r"\bcase\s+SOFAB_OBJECT_FIELDTYPE_"),
    # walking a decoded value into the materialized form (oracle/materialized.md);
    # `struct_wrapper` is the one kind name that exists nowhere else
    "materialized-walk": re.compile(r"[\"']struct_wrapper[\"']"),
    # DEFINING a wrapper-array placement helper — the layer generator#587 moved into
    # the corelibs. Calling the corelib's is fine; owning one is the drift.
    "placement-helper": re.compile(
        r"(?:\bdef|\bfn|\bfunc|\bfun|\bstatic|\bvoid|\bpublic|\bprivate)\s+[\w<>\[\]\s]*?"
        r"\b(?:place_?elem|reserve_?(?:elem|row|leaf)|check_?index|fill_?gaps?)\s*[(<]", re.I),
}

WALKER_REASON = (
    "the materialized form is Crucible's own oracle format (oracle/materialized.md); no "
    "corelib emits it, so each driver walks its decoded value itself — kind coverage is "
    "asserted below")
BYTES_REASON = (
    "builds adversarial wire bytes (malformed, over-bound, non-canonical) that a "
    "conformant corelib writer refuses to produce — and the reference must not share "
    "code with the implementations it judges")

# path glob -> (signatures it may carry, walker?, reason). A walker is checked by 3.
INVENTORY = {
    "drivers/c/driver.c": (
        {"fieldtype-dispatch"}, False,
        "the C anchor walks corelib-c-cpp's object descriptor into the materialized form; "
        "corelib-c-cpp ships no such dump — tag coverage is asserted below"),
    "drivers/*/materialize_gen.py": ({"materialized-walk"}, True, WALKER_REASON),
    "drivers/cs/Driver.cs": ({"materialized-walk"}, True, WALKER_REASON),
    "drivers/go/driver.go": ({"materialized-walk"}, True, WALKER_REASON),
    "drivers/java/ProbeDump.java": ({"materialized-walk"}, True, WALKER_REASON),
    "drivers/python/driver.py": ({"materialized-walk"}, True, WALKER_REASON),
    "drivers/ts/driver.ts": ({"materialized-walk"}, True, WALKER_REASON),
    "engine/structured/materialize.py": (
        {"materialized-walk"}, True,
        "the reference the materialized oracle is judged against; it models the spec, "
        "independently of every implementation under test"),
    "engine/structured/schema.py": (
        {"materialized-walk"}, False,
        "produces oracle/materialized-schema.json (the kind vocabulary itself) from "
        "schema/probe.sofab.yaml; materialize.sh asserts the committed copy is current"),
    "engine/structured/gen.py": ({"wire-codec"}, False, BYTES_REASON),
    "engine/structured/sweep_varint.py": ({"wire-codec"}, False, BYTES_REASON),
}

# Check 4: roster driver -> (generated probe sources, the corelib layer they must call).
# Paths are the build outputs of drivers/<lang>/build.sh for the default probe schema.
# (corelib-c-cpp's static profile spells its collectors Fixed*Seq)
SEQ = r"\b(?:Fixed)?(?:String|Blob|Message|Framed|Element)Seq\b"
PLACE = r"\b(?:place_?[Ee]lem|reserve_?[Ee]lem|reserve_?[Rr]ow|reserve_?[Ll]eaf)\b"
PLACE_CS = r"\bSeq\.(?:PlaceElem|ReserveElem|ReserveRow)\b"
GENERATED = {
    # C decodes through corelib-c-cpp's descriptor transcoder: the generated code is
    # only the descriptor, so one SOFAB_OBJECT_FIELD per wrapper is the whole call.
    "c":             (["drivers/c/gen/probe.c"], r"\bSOFAB_OBJECT_FIELD\w*\("),
    "go":            (["drivers/go/message/probe.go"], r"\bNew(?:String|Blob|Message)Seq\b"),
    "rust-std":      (["drivers/rust/build/rs/src/message.rs"], PLACE),
    "rust-nostd":    (["drivers/rust/build/rs-no-std/src/message.rs"], PLACE),
    "cpp":           (["drivers/cpp/gen/cpp/probe.hpp"], SEQ),
    "cpp-fixed":     (["drivers/cpp/gen/cpp-fixed/probe.hpp"], SEQ),
    "cpp-c-cpp":     (["drivers/cpp/gen/c-cpp/probe.hpp"], SEQ),
    "cpp-c-cpp-dyn": (["drivers/cpp/gen/c-cpp-dyn/probe.hpp"], SEQ),
    "py-cython":     (["drivers/python/build/gen/message.py"], PLACE),
    "py-pure":       (["drivers/python/build/gen/message.py"], PLACE),
    "java":          (["drivers/java/build/gen/src/main/java/message/Probe.java"], PLACE),
    "typescript":    (["drivers/ts/build/message.ts"], SEQ),
    "csharp":        (["drivers/cs/build/Message.cs"], PLACE_CS),
    "zig":           (["drivers/zig/build/src/message.zig"], PLACE),
    "dart":          (["drivers/dart/build/bin/message.dart"], SEQ),
    "kotlin-jvm":    (["drivers/kotlin/build/jvm/gen/src/main/kotlin/message/Probe.kt"], PLACE),
    "kotlin-native": (["drivers/kotlin/build/native/gen/src/main/kotlin/message/Probe.kt"], PLACE),
}

OBJECT_H = "vendor/corelib-c-cpp/src/include/sofab/object.h"
ANCHOR = "drivers/c/driver.c"
MATERIALIZED_SCHEMA = "oracle/materialized-schema.json"


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def tracked_sources():
    # safe.directory: the CI container runs as a different uid than the one that checked
    # the repo out, and git then refuses the repository ("dubious ownership").
    run = subprocess.run(["git", "-c", f"safe.directory={ROOT}", "-C", ROOT, "ls-files", *SCOPE],
                         capture_output=True, text=True)
    if run.returncode != 0:
        sys.exit(f"git ls-files failed ({run.returncode}): {run.stderr.strip()}")
    return [f for f in run.stdout.split() if f.endswith(SOURCE_EXT) and f != SELF]


def entry_for(path):
    for pattern in INVENTORY:
        if fnmatch.fnmatchcase(path, pattern):
            return pattern
    return None


def check_inventory(errors):
    used = set()
    for path in tracked_sources():
        text = read(path)
        for sig, rx in SIGNATURES.items():
            if not rx.search(text):
                continue
            pattern = entry_for(path)
            if pattern is None or sig not in INVENTORY[pattern][0]:
                errors.append(
                    f"{path}: carries a `{sig}` copy of family logic that INVENTORY does not "
                    f"account for — call the corelib's instead, or add an entry saying why "
                    f"it is a deliberate copy")
            else:
                used.add((pattern, sig))
    for pattern, (sigs, _, _) in INVENTORY.items():
        for sig in sigs:
            if (pattern, sig) not in used:
                errors.append(
                    f"INVENTORY `{pattern}` claims a `{sig}` copy that no longer exists — "
                    f"remove or correct the entry")


def schema_kinds():
    kinds = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("kind"), str):
                kinds.add(node["kind"])
            if isinstance(node.get("elem"), str):
                kinds.add(node["elem"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    doc = json.loads(read(MATERIALIZED_SCHEMA))
    walk(doc)
    return kinds, doc


def check_walkers(errors):
    kinds, _ = schema_kinds()
    walkers = [p for p in tracked_sources()
               if (e := entry_for(p)) is not None and INVENTORY[e][1]]
    if not walkers:
        errors.append("no materialized-value walker found — INVENTORY globs are wrong")
    for path in walkers:
        text = read(path)
        missing = sorted(k for k in kinds if not re.search(rf"[\"']{re.escape(k)}[\"']", text))
        if missing:
            errors.append(
                f"{path}: materialized-value walker never names kind(s) {missing} from "
                f"{MATERIALIZED_SCHEMA} — it cannot render them")
    return len(walkers), len(kinds)


def check_anchor(errors):
    tags = re.findall(r"^#define\s+(SOFAB_OBJECT_FIELDTYPE_\w+)\s", read(OBJECT_H), re.M)
    if not tags:
        errors.append(f"{OBJECT_H}: no SOFAB_OBJECT_FIELDTYPE_* defines found — the "
                      f"header moved; update OBJECT_H")
        return 0
    src = read(ANCHOR)
    # the definition, not the forward declaration above it (`...);` vs `...) {`)
    m = re.search(r"static void md_value\([^;{]*\)\s*\{.*?\n}\n", src, re.S)
    if not m:
        errors.append(f"{ANCHOR}: md_value() not found — update the anchor check")
        return len(tags)
    cases = set(re.findall(r"\bcase\s+(SOFAB_OBJECT_FIELDTYPE_\w+)", m.group(0)))
    for tag in tags:
        if tag not in cases:
            errors.append(
                f"{ANCHOR}: md_value() has no case for {tag} (defined in {OBJECT_H}); the "
                f"anchor would print `?` there and turn materialize.sh red for a reason "
                f"that is not a family divergence")
    return len(tags)


def check_generated(errors):
    _, doc = schema_kinds()
    wrappers = json.dumps(doc).count('"kind": "wrapper"') + \
        json.dumps(doc).count('"kind": "struct_wrapper"')
    roster = [ln.split()[0] for ln in read("drivers/roster").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    for name in roster:
        if name not in GENERATED:
            errors.append(f"drivers/roster: `{name}` has no GENERATED entry — say which "
                          f"corelib layer its generated code must reach")
    for name in sorted(set(GENERATED) - set(roster)):
        errors.append(f"GENERATED `{name}` is not in drivers/roster — remove the entry")
    for name, (paths, rx) in GENERATED.items():
        if name not in roster:
            continue
        files = [f for p in paths for f in glob.glob(os.path.join(ROOT, p))]
        if not files:
            errors.append(f"{name}: generated probe code {paths} not found — build it "
                          f"first (./scripts/run.sh)")
            continue
        calls = sum(len(re.findall(rx, read(os.path.relpath(f, ROOT)))) for f in files)
        if calls < wrappers:
            errors.append(
                f"{name}: generated probe code calls its corelib's collector layer {calls} "
                f"time(s) for {wrappers} wrapper field(s) — some wrapper is placed by "
                f"generated code again (generator#587)")
    return len(roster), wrappers


def main():
    static = "--static" in sys.argv[1:]
    errors = []
    check_inventory(errors)
    n_walkers, n_kinds = check_walkers(errors)
    summary = [f"{len(INVENTORY)} inventory entries", f"{n_walkers} walkers x {n_kinds} kinds"]
    if not static:
        missing = [p for p in (OBJECT_H,) if not os.path.exists(os.path.join(ROOT, p))]
        if missing:
            errors.append(f"{missing[0]} missing — run scripts/bootstrap.sh, or pass "
                          f"--static to skip the checks that need vendor/ and built drivers")
        else:
            n_tags = check_anchor(errors)
            n_drivers, n_wrappers = check_generated(errors)
            summary += [f"{n_tags} C field-type tags",
                        f"{n_drivers} drivers x {n_wrappers} wrapper fields"]
    for e in errors:
        print(f"FAIL: {e}")
    print(f"{'OK' if not errors else 'FAIL'}: family copies — " + ", ".join(summary)
          + ("" if not static else " (static: anchor + generated checks skipped)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
