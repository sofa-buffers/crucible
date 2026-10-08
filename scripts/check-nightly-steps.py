#!/usr/bin/env python3
"""Make a non-blocking nightly step that failed visible, instead of letting it go dark.

`continue-on-error` is right for the nightly's fuzz engines and cluster steps — a Go panic is a
finding to upload, not a reason to stop the job — but it also hides a step that simply stopped
working: GitHub reports such a step as a success, in the UI and in the jobs API alike. Its real
result is only in the workflow's `steps.<id>.outcome`, so this script reads that.

  STEPS='${{ toJSON(steps) }}' python3 scripts/check-nightly-steps.py
      the last step of nightly.yml: one annotation + one summary line per failed step, exit 1
      when any failed (the artifact upload runs before it, so nothing is lost to the red run)

  python3 scripts/check-nightly-steps.py --lint [workflow]
      static, in replay.yml's catalog job: every `continue-on-error` step carries an `id`.
      A step without one is absent from `steps`, so its failure would be silent again.
"""
import json
import os
import sys

WORKFLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "nightly.yml")


def steps_of(text):
    """The steps of a workflow as dicts of their top-level keys, by indentation alone (the
    nightly is one job; no YAML library is needed to see `- name:` / `id:` / a flag)."""
    steps, cur, ind = [], None, None
    for line in text.splitlines():
        s = line.lstrip()
        if not s or s.startswith("#"):
            continue
        lead = len(line) - len(s)
        if s.startswith("- name:"):
            cur = {"name": s[len("- name:"):].strip()}
            ind = lead + 2
            steps.append(cur)
        elif cur is not None and lead == ind and ":" in s:
            k, v = s.split(":", 1)
            cur[k.strip()] = v.strip()
        elif cur is not None and lead < ind:
            cur = None
    return steps


def lint(path):
    bad = [s["name"] for s in steps_of(open(path, encoding="utf-8").read())
           if s.get("continue-on-error") == "true" and "id" not in s]
    for name in bad:
        print(f"FAIL: continue-on-error step without an id (its failure would be silent): {name}")
    if bad:
        return 1
    print(f"OK: every continue-on-error step in {os.path.relpath(path)} carries an id")
    return 0


def report(steps):
    failed = [k for k, v in steps.items() if v.get("outcome") == "failure"]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["### Non-blocking step outcomes", "", "| step | outcome |", "|---|---|"]
    lines += [f"| `{k}` | {v.get('outcome')} |" for k, v in steps.items()]
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for k in failed:
        print(f"::error title=non-blocking step failed::step '{k}' failed; the run went on without it")
    print(f"{len(steps) - len(failed)}/{len(steps)} non-blocking step(s) succeeded"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def main(argv):
    if "--lint" in argv:
        rest = [a for a in argv[1:] if a != "--lint"]
        return lint(rest[0] if rest else WORKFLOW)
    raw = os.environ.get("STEPS")
    if raw is None:
        print("usage: STEPS='<toJSON(steps)>' check-nightly-steps.py | check-nightly-steps.py --lint [workflow]",
              file=sys.stderr)
        return 2
    return report(json.loads(raw))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
