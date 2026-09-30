#!/usr/bin/env python3
"""Which generator CI run's sofabgen does bootstrap.sh install? (crucible#183 and its sequel)

The old rule was "the newest green run, by date, out of a list of runs". That list is a
search-index answer, and on 2026-09-30 the replay job on main was handed a run five days old
while runs from that morning existed: the bootstrap installed a generator from before
generator#608, and eleven union vectors went red for a reason that lived in no test. The rule
also had a second hole -- a generator tip whose CI was still running fell through silently to
the newest older green build, which is the same stale toolchain by another route.

The rule now walks the generator's COMMITS from the tip and asks about each one, instead of
trusting a global list:

  * a commit with a run still in progress or queued  -> ABORT ("running"). The newest build is
    about to exist; installing an older one and comparing a fresh family against it is exactly
    the mismatch this repo exists to avoid. Wait for it, pin SOFABGEN_RUN, or set
    SOFABGEN_ALLOW_RUNNING=1 to walk past it.
  * the TIP has no run at all and is younger than FRESH_MINUTES -> ABORT ("fresh"). CI has not
    started yet; the same reasoning.
  * a commit with a completed, successful run        -> pick it.
  * a commit whose runs all failed or were cancelled -> a red build, walk on to its parent.

`pick()` takes the API reader as an argument so the rule is tested without a network
(scripts/check-sofabgen-pick.py). CLI: sofabgen_pick.py <api-base> <branch> [--allow-running],
token in $TOK; prints one line.

  OK <run-id> <sha> <created_at> <tip-sha> <commits-from-tip>
  RUNNING <run-id> <sha>
  FRESH <sha>
  NONE
"""
import datetime
import json
import os
import sys
import urllib.request

FRESH_MINUTES = 30
DEPTH = 30


def _ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def pick(get, branch, allow_running=False, now=None, depth=DEPTH):
    """Return ('ok', run_id, sha, created_at, tip_sha, index) | ('running', run_id, sha)
    | ('fresh', sha) | ('none',). `get(path)` returns the parsed JSON of an API path."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    commits = get(f"/commits?sha={branch}&per_page={depth}")
    if not commits:
        return ("none",)
    tip = commits[0]["sha"]
    for i, c in enumerate(commits):
        sha = c["sha"]
        runs = get(f"/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=20").get("workflow_runs", [])
        # a run for this exact commit on this branch: a PR run of the same sha (head_branch is
        # the PR's branch) is not the branch's build
        runs = [r for r in runs if r.get("head_branch") == branch]
        live = [r for r in runs if r.get("status") != "completed"]
        if live and not allow_running:
            return ("running", live[0]["id"], sha)
        green = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"]
        if green:
            r = max(green, key=lambda x: x["created_at"])
            return ("ok", r["id"], sha, r["created_at"], tip, i)
        if i == 0 and not runs and not allow_running:
            when = c.get("commit", {}).get("committer", {}).get("date")
            if when and (now - _ts(when)) < datetime.timedelta(minutes=FRESH_MINUTES):
                return ("fresh", sha)
        # failed / cancelled / no run (a commit CI never covered): a red or unbuilt commit
    return ("none",)


def _reader(api, token):
    def get(path):
        req = urllib.request.Request(
            api + path,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    return get


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2 or not os.environ.get("TOK"):
        print("usage: TOK=<token> sofabgen_pick.py <api-base> <branch> [--allow-running]", file=sys.stderr)
        return 2
    res = pick(_reader(args[0], os.environ["TOK"]), args[1], allow_running="--allow-running" in argv)
    print(" ".join(str(x) for x in (res[0].upper(),) + tuple(res[1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
