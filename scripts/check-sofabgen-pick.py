#!/usr/bin/env python3
"""The rule that chooses which generator build bootstrap.sh installs, tested offline.

Every case is a history of commits (newest first) with the CI runs each one has. What the rule
must do is written next to it; the case that started this is `stale_list_cannot_win`: the old
rule read a global list of successful runs and was once handed one that was five days old.

  python3 scripts/check-sofabgen-pick.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sofabgen_pick import pick  # noqa: E402

NOW = datetime.datetime(2026, 9, 30, 15, 0, tzinfo=datetime.timezone.utc)


def iso(minutes_ago):
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(rid, status="completed", conclusion="success", branch="main", minutes_ago=100, event="push"):
    return {"id": rid, "status": status, "conclusion": conclusion,
            "head_branch": branch, "created_at": iso(minutes_ago), "event": event}


def history(*commits):
    """commits: (sha, age_in_minutes, [runs]) newest first -> a `get` over that history."""
    by_sha = {sha: runs for sha, _, runs in commits}

    def get(path):
        if path.startswith("/commits?"):
            return [{"sha": sha, "commit": {"committer": {"date": iso(age)}}} for sha, age, _ in commits]
        sha = path.split("head_sha=")[1].split("&")[0]
        return {"workflow_runs": by_sha.get(sha, [])}
    return get


FAILED = []


def case(name, got, want):
    ok = got[: len(want)] == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got[0]}" + ("" if ok else f"  (wanted {want}, got {got})"))
    if not ok:
        FAILED.append(name)


# the tip is green: use it
case("tip_green", pick(history(("t", 20, [run(1)]), ("p", 90, [run(2)])), "main", now=NOW),
     ("ok", 1, "t"))

# the tip's CI is still running: ABORT, do not fall through to the older green build
case("tip_running_aborts", pick(history(("t", 5, [run(9, "in_progress", None)]), ("p", 90, [run(2)])),
                                "main", now=NOW), ("running", 9, "t"))
case("tip_queued_aborts", pick(history(("t", 5, [run(9, "queued", None)]), ("p", 90, [run(2)])),
                               "main", now=NOW), ("running", 9, "t"))

# ...unless told to walk past it
case("running_walked_past_when_allowed",
     pick(history(("t", 5, [run(9, "in_progress", None)]), ("p", 90, [run(2)])), "main", allow_running=True, now=NOW),
     ("ok", 2, "p"))

# a re-run in progress on a commit that also has an older success is still "running"
case("rerun_in_progress_aborts",
     pick(history(("t", 30, [run(1), run(9, "in_progress", None)]), ("p", 90, [run(2)])), "main", now=NOW),
     ("running", 9, "t"))

# a red tip is skipped to the newest green ancestor (and reported by the caller as such)
case("red_tip_uses_green_ancestor",
     pick(history(("t", 20, [run(1, conclusion="failure")]), ("p", 90, [run(2)])), "main", now=NOW),
     ("ok", 2, "p", iso(100), "t", 1))
case("cancelled_tip_uses_green_ancestor",
     pick(history(("t", 20, [run(1, conclusion="cancelled")]), ("p", 90, [run(2)])), "main", now=NOW),
     ("ok", 2, "p"))

# CI has not started on a fresh tip: abort; on an old tip CI never covered: walk on
case("fresh_tip_without_run_aborts", pick(history(("t", 5, []), ("p", 90, [run(2)])), "main", now=NOW),
     ("fresh", "t"))
case("old_tip_without_run_walks_on", pick(history(("t", 300, []), ("p", 400, [run(2)])), "main", now=NOW),
     ("ok", 2, "p"))
case("fresh_tip_without_run_walks_when_allowed",
     pick(history(("t", 5, []), ("p", 90, [run(2)])), "main", allow_running=True, now=NOW), ("ok", 2, "p"))

# a run of the same sha from a PR branch is not the branch's build
case("pr_run_of_the_same_sha_is_ignored",
     pick(history(("t", 300, [run(1, branch="feature")]), ("p", 400, [run(2)])), "main", now=NOW),
     ("ok", 2, "p"))

# the case that started this: a newer green run exists, and an older one must not win. The old
# rule took the newest of a global list and was once handed a stale one; this rule asks per
# commit, so the newest green COMMIT wins. (Offline this checks the rule, not GitHub's API.)
case("newest_green_commit_wins",
     pick(history(("t", 60, [run(50, minutes_ago=60)]), ("m", 900, [run(40, minutes_ago=900)]),
                  ("o", 7000, [run(3, minutes_ago=7000)])), "main", now=NOW),
     ("ok", 50, "t"))

# the nightly schedule run of the tip is newer than its push run but attaches no binary: the
# push run wins (2026-10-07: picking the schedule run sent every bootstrap to a week-old release)
case("push_run_beats_newer_schedule_run",
     pick(history(("t", 120, [run(7, minutes_ago=110), run(8, minutes_ago=30, event="schedule")])),
          "main", now=NOW),
     ("ok", 7, "t"))
# a commit with only a schedule run is still green (the caller reports a missing artifact)
case("schedule_only_still_picked",
     pick(history(("t", 120, [run(8, minutes_ago=30, event="schedule")])), "main", now=NOW),
     ("ok", 8, "t"))

# nothing green anywhere
case("nothing_green", pick(history(("t", 200, [run(1, conclusion="failure")]),
                                   ("p", 300, [run(2, conclusion="failure")])), "main", now=NOW), ("none",))
case("empty_history", pick(lambda path: [], "main", now=NOW), ("none",))

print()
if FAILED:
    print(f"sofabgen pick: {len(FAILED)} case(s) FAILED: {', '.join(FAILED)}")
    sys.exit(1)
print("sofabgen pick: OK — every case behaves as the rule states")
