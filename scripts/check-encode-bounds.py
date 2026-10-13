#!/usr/bin/env python3
"""Is any driver BUILT with an encode-bound opt-out switched on?

generator#656 made the generated encoder refuse a value past a declared bound (generator
`docs/ARCHITECTURE.md` §9.6.1), and two profiles can compile that refusal out:
`SOFAB_DISABLE_ENCODE_BOUNDS` (C / C++ with the c-cpp corelib) and the
`disable_encode_bounds` cargo feature (`rs-no-std` + `allow_dynamic`). Crucible compares
implementations as a user gets them, so switching a refusal out in one of its own build
recipes would make that profile silently more permissive than every other.

That is a question about Crucible's own build configuration, and it is the whole of this
check. Whether each profile's *generated code* carries the guards its mechanism calls for
is the generator's conformance question — `tests/conformance/lib/check_encode_bounds.py`
there owns it, by filling values past their bounds through the generated setters. Crucible
reads generated code only by calling it (drivers/common/CONTRACT.md, "Decode core
requirements"); it does not grep it.

    ./scripts/check-encode-bounds.py          # run.sh calls it; reads the build recipes
                                              # and the generated Cargo.toml files

Exit 0 = no opt-out is switched on anywhere a driver is built.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The opt-outs §9.6.1 names, and the one spelling each takes. Searched in the BUILD
# recipes (what the compiler is actually told) and in the generated projects.
OPT_OUTS = [
    ("SOFAB_DISABLE_ENCODE_BOUNDS", "C / C++ (corelib c-cpp): compiles every refusal out"),
    ("disable_encode_bounds", "rs-no-std cargo feature: compiles every guard out"),
]
OPT_OUT_SCOPE = (["drivers/%s/build.sh" % d for d in
                  ("c", "cpp", "rust", "zig", "go", "python", "java", "kotlin", "cs",
                   "ts", "dart")]
                 + ["scripts/fuzz.sh",
                    "drivers/rust/build/rs/Cargo.toml",
                    "drivers/rust/build/rs-no-std/Cargo.toml",
                    "drivers/rust/build/rs-no-std-h09/Cargo.toml",
                    # the one generated project that DECLARES the opt-out: what is
                    # checked here is that it stays a declaration
                    "drivers/rust/build/rs-no-std-dyn/Cargo.toml"])


def opt_out_enabled(line, token):
    """Is this line SWITCHING the opt-out on, rather than declaring it exists?

    `rs-no-std` with allow_dynamic puts `disable_encode_bounds = []` in the generated
    Cargo.toml -- that is the feature being DECLARED, off by default, which is exactly
    the state this check wants. What would switch it on is the feature appearing in a
    list: `default = ["disable_encode_bounds"]`, another feature enabling it, a
    dependency's `features = [...]`, or `--features` in a build recipe. So a line that
    merely defines the feature is fine, and a line that mentions it inside brackets or on
    a cargo/compiler command line is not. (`SOFAB_DISABLE_ENCODE_BOUNDS` has no such
    declaration form -- any mention of it in a build recipe is a definition being passed
    to the compiler.)
    """
    # Comments first, in both file kinds: `#` starts one in Cargo.toml and in a shell
    # recipe alike, and the word appears in prose on both sides of this repo — the build
    # script explains the opt-out it does not use, which is not the same as using it.
    bare = line.split("#", 1)[0].strip()
    if token not in bare:
        return False
    if re.fullmatch(re.escape(token) + r"\s*=\s*\[\s*\]", bare):
        return False      # the declaration itself: the feature exists, switched off
    return True


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as fh:
        return fh.read()


SELF_TEST = [
    ("disable_encode_bounds = []", "disable_encode_bounds", False),
    ('default = ["disable_encode_bounds"]', "disable_encode_bounds", True),
    ("cargo build --features disable_encode_bounds", "disable_encode_bounds", True),
    ("# we never pass disable_encode_bounds", "disable_encode_bounds", False),
    ("$CC -DSOFAB_DISABLE_ENCODE_BOUNDS x.c", "SOFAB_DISABLE_ENCODE_BOUNDS", True),
]


def main():
    fail = 0
    for line, token, want in SELF_TEST:
        if opt_out_enabled(line, token) != want:
            print(f"  !! self-test: opt_out_enabled({line!r}) should be {want}")
            fail += 1
    for token, what in OPT_OUTS:
        where = [rel for rel in OPT_OUT_SCOPE
                 if any(opt_out_enabled(line, token)
                        for line in (read(rel) or "").splitlines())]
        if where:
            print(f"  !! {token} appears in {', '.join(where)} — {what}. Crucible compares "
                  "implementations as a user gets them; switching a refusal out here would "
                  "make the profile silently more permissive than every other.")
            fail += 1
        else:
            print(f"  ok  no {token} switched on in any build recipe")
    if fail:
        print(f"\n{fail} problem(s).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
