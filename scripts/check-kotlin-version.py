#!/usr/bin/env python3
"""Is the image's Kotlin compiler new enough for the corelib's klibs?

`corelib-kotlin-mp` is a Kotlin Multiplatform library: Gradle builds it, and
`drivers/kotlin/build.sh` compiles a handful of driver files against the result with the
standalone compiler the image carries. For the **jvm** leg that result is a jar, which is
version-tolerant. For **js** and **native** it is a **klib**, which is not — and the two
failures are not symmetric:

  * a NEWER compiler than the library fails loudly, on metadata version;
  * an OLDER one ignores the klib **silently**. The JS leg then compiles to nothing and
    the next step fails on a missing file: `No module with …/driver.klib found`, two
    steps away from the cause (crucible#244).

So the relationship is an invariant with two sync points — `.devcontainer/Dockerfile`'s
`KOTLIN_VERSION` and that repo's `kotlin("multiplatform") version` — and the second moves
on its own, because Renovate bumps it whenever Kotlin releases. A comment asking the
reader to keep them in step is what was there before; this asserts it.

Two questions, because they fail independently — and only one of them is a PR's to fix:

  1. **the Dockerfile** — does its `KOTLIN_VERSION` satisfy `>= corelib`? **Hard.** This
     is the sync point the repo owns, it is reviewable in the diff, and it is what the
     next image will carry.
  2. **the image** — does the `kotlinc` on PATH satisfy `>= corelib`? **Reported, not
     enforced.** The image is a build artifact that lags a merge by construction: it
     rebuilds on a push to **main** touching the Dockerfile
     (.github/workflows/image.yml), so the very PR that fixes (1) necessarily runs under
     the old image. Failing on it would make the fix unmergeable. What covers the
     consequence meanwhile is the `kotlin-js` quarantine and the loud pre-flight in
     `drivers/kotlin/build.sh`, which exits 3 naming both numbers instead of failing two
     steps later on a missing klib.

    python3 scripts/check-kotlin-version.py

Exit 0 = both hold (or are not checkable here, which it says). Needs vendor/, so it runs
after bootstrap rather than in the driver-free `catalog` job.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = ".devcontainer/Dockerfile"
CORELIB_BUILD = "vendor/corelib-kotlin-mp/build.gradle.kts"


def ver(s):
    """'2.4.21' -> (2, 4, 21); a trailing qualifier ('2.5.0-RC') sorts below the release."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(.*)", s.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1)


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        return None
    with open(path, errors="replace") as fh:
        return fh.read()


def corelib_version():
    text = read(CORELIB_BUILD)
    if text is None:
        return None, f"{CORELIB_BUILD} is not vendored (scripts/bootstrap.sh)"
    m = re.search(r'kotlin\("multiplatform"\)\s+version\s+"([^"]+)"', text)
    if not m:
        return None, f"no `kotlin(\"multiplatform\") version` in {CORELIB_BUILD}"
    return m.group(1), None


def dockerfile_version():
    text = read(DOCKERFILE)
    if text is None:
        return None, f"{DOCKERFILE} is missing"
    found = set(re.findall(r"KOTLIN_VERSION=([0-9][^\s\\]*)", text))
    if not found:
        return None, f"no KOTLIN_VERSION in {DOCKERFILE}"
    if len(found) > 1:
        # Both uses (the standalone compiler and the Kotlin/Native prebuilt) consume
        # klibs from the same library, so one number has to serve both.
        return None, (f"{DOCKERFILE} pins {len(found)} different KOTLIN_VERSIONs "
                      f"({', '.join(sorted(found))}) — the standalone compiler and the "
                      "Kotlin/Native prebuilt both read the corelib's klibs, so they "
                      "must agree")
    return found.pop(), None


def installed_version():
    try:
        out = subprocess.run(["kotlinc", "-version"], capture_output=True, text=True,
                             timeout=120)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        return None, f"no usable kotlinc on PATH ({e.__class__.__name__})"
    # `kotlinc -version` writes to stderr: "info: kotlinc-jvm 2.4.21 (JRE 21...)"
    m = re.search(r"kotlinc(?:-\w+)?\s+(\d+\.\d+\.\d+\S*)", out.stderr + out.stdout)
    if not m:
        return None, "could not read a version out of `kotlinc -version`"
    return m.group(1), None


def main():
    core, err = corelib_version()
    if core is None:
        print(f"  -- skipped: {err}")
        return 0
    print(f"corelib-kotlin-mp builds its klibs with Kotlin {core}")

    fail = 0
    for what, (got, why), hard, consequence in (
        (f"{DOCKERFILE}", dockerfile_version(), True,
         "the NEXT image gets this one; the image rebuilds on a push to main that "
         "touches the Dockerfile (.github/workflows/image.yml)"),
        ("the image's kotlinc", installed_version(), False,
         "a build in THIS container reads the corelib's klibs with it — js silently "
         "compiles to nothing, native reads a newer klib than it knows. Reported rather "
         "than failed: the image lags the Dockerfile by one merge, so the fix would be "
         "unmergeable otherwise"),
    ):
        if got is None:
            print(f"  -- {what}: not checkable — {why}")
            continue
        a, b = ver(got), ver(core)
        if a is None or b is None:
            print(f"  -- {what}: {got} — cannot compare with {core}")
            continue
        if a < b:
            mark = "!!" if hard else "warning:"
            print(f"  {mark} {what} is {got}, older than the corelib's {core} — "
                  f"{consequence}")
            fail += hard
        else:
            print(f"  ok  {what} is {got} (>= {core})")

    if fail:
        print(f"\n{fail} version gap(s) that this repo owns. An older compiler than the "
              "library is the SILENT half of this: the klib is ignored without a word, "
              "and the failure surfaces as a missing driver.klib two steps later "
              "(crucible#244).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
