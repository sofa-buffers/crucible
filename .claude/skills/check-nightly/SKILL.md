---
name: check-nightly
description: Download the latest Crucible nightly fuzzing artifact (grown corpus, crashes, cluster report) and triage it locally — merge into corpus/interesting, re-cluster against results/known-clusters.txt with freshly built drivers, minimize and attribute anything new. Use when the user says "check nightly", "nightly checken", "look at the nightly", or asks what last night's fuzzing found.
---

# Check the nightly

`nightly.yml` fuzzes for ~45 min, grows `corpus/interesting`, clusters it against
`results/known-clusters.txt` and uploads everything as an artifact. **The artifact is not
the finding** — CI only says *"this camp is not in the baseline"*. Turning that into a
finding (or into "already explained") is this procedure.

What each file/gate *is* stays in its owner (`docs/CI.md`, `docs/ARCHITECTURE.md`,
`results/CLUSTERS.md`, `results/known-clusters.txt`); this skill is only the **procedure**.
Do not restate counts or purposes from those files here — they drift.

## 0. Orient (cheap, no build)

```sh
gh run list --workflow nightly.yml --limit 5
gh run view <run-id>                       # step status + annotations (the red continue-on-error steps)
```

Then check whether this run was already triaged — the last analysed run id is stamped in
the `results/known-clusters.txt` header and in `results/CLUSTERS.md` snapshots:

```sh
grep -rn "<run-id>" results/ docs/ ; git log --oneline -5
```

If it is already recorded, say so and stop — don't re-triage silently.

Read what CI already reported before spending a build (the log is huge; grep it):

```sh
gh run view --job=<job-id> --log | grep -E "baseline:|NEW CAMP|CRASH|panic|total:" | tail -20
```

That gives the fuzz yield (execs / new interesting), the Go-engine step, crash artifacts,
and the camp verdict — often enough to know whether this is a 5-minute or a 2-hour session.

## 1. Download the artifact

Into the scratchpad, never straight into the repo — a stale artifact must not silently
become the local corpus:

```sh
DL=<scratchpad>/nightly-<run-id>
gh run download <run-id> -n nightly-<run-id> -D "$DL"
ls "$DL"/corpus/interesting | wc -l ; ls "$DL"/corpus/crashes
```

Artifacts expire after 14 days; if it is gone, re-run `nightly.yml` via
`gh workflow run nightly.yml -f fuzz_time=<sec>` instead of analysing a stale one.

## 2. Merge into the local corpus — union, kept whole

Policy (decided 2026-08-03, STATUS-LOG): the corpus is the **union** of CI's and ours, and
it is **never minimized for maintenance** — minimization preserves only the divergences
measurable at that instant and throws away inputs that start diverging after the next
corelib rewrite. Minimizing is a triage tool for one input, not corpus hygiene.

```sh
before=$(ls corpus/interesting | wc -l)
cp -n "$DL"/corpus/interesting/* corpus/interesting/
echo "$before -> $(ls corpus/interesting | wc -l)"
cp -n "$DL"/corpus/crashes/* corpus/crashes/ 2>/dev/null
```

`corpus/interesting` and `corpus/crashes` are gitignored — the local accumulation is not in
git, so state the counts in the report.

## 3. Freshen the family, then measure

```sh
FAMILY_BRANCH=main ./scripts/bootstrap.sh      # corelibs @ main + latest green sofabgen CI build
```

Pass `FAMILY_BRANCH=main` explicitly when the checkout is on a working branch: a scheduled
nightly always runs the **main** family, and bootstrap otherwise tracks the local branch
name. Bootstrap already fetches and hard-resets each vendored corelib, so no manual pull.

A codegen finding is only meaningful against a current sofabgen — check the version line
bootstrap prints before concluding anything about generated code.

## 4. Re-cluster locally against the baseline

```sh
CLUSTER=1 TIMEOUT=5 CORPUS=corpus/interesting BASELINE=results/known-clusters.txt ./scripts/run.sh
```

Always via `run.sh` — it builds the roster and passes `--driver` from `drivers/roster`.
Calling `oracle/cluster.py`/`comparator.py` directly risks measuring whatever binaries the
limit/sweep suites left in `drivers/*/build/`.

## 5. Triage the NEW camps — in this order

**5a. Rule out the false alarm first.** Every baseline signature names *every* driver, so a
**roster change invalidates all of them at once** and the run screams "N NEW CAMPS" with
zero new root causes (2026-08-05: 9 "new" camps = 6 old rows plus two driver names, 3 known
moves). Before triaging: diff the driver roster against the baseline's stamped roster; strip
the added names from each new signature and check whether it matches an old row byte for
byte. If that is all it is, **rebase the baseline** with a commit that says which rows moved
and why — do not open findings. (Making the baseline survive a roster change is in
`docs/TODO.md`.)

**5b. Also cheap: a driver that merely *moved* camps** for a reason already on record
(a fix that landed, a quarantine lifted). Check STATUS-LOG/FINDINGS for that driver before
assuming a new defect.

**5c. What is left is the real queue.** Per camp, minimize its representative:

```sh
MINIMIZE=corpus/interesting/<repr> ./scripts/run.sh      # -> <repr>.min.bin
```

⚠️ **Never run a minimization concurrently with any other `run.sh`** — the rebuild unlinks
the rust binary mid-relink and the minimizer dies with a `FileNotFoundError` that looks like
a timeout. Two runs were lost to this.

Then attribute **before** filing — schema facts (`count`, `maxlen`, `N`, declared types) →
`generator` as a `G-00NN`; wire mechanics (varints, framing, INVALID-vs-INCOMPLETE) →
`corelib-<lang>`. Read the generated code *and* the corelib function, and diff a sibling
profile (`cpp` vs `cpp-c-cpp`, `rust-std` vs `rust-nostd`, `py-cython` vs `py-pure`) — a
split inside one language indicts codegen. Full rule: `CLAUDE.md`.

Re-read every cited §-clause **at the documentation tip** before filing (`vendor/documentation`
is not fetched by bootstrap — clone/pull it yourself), and name the owner explicitly in the
write-up.

Refuted hypotheses are worth recording: each one narrows the next isolate.

## 6. The two extra passes that pay for themselves

The round-trip oracle is not the whole net:

```sh
./scripts/materialize.sh                                             # value defects the round-trip can't see
                                                                     # (defaults to corpus/structured; CORPUS= to widen)
CORPUS=corpus/interesting ./scripts/run-chunked.sh --modes chunk,scrub
CORPUS=corpus/interesting ./scripts/run-encode.sh
```

`--modes chunk,scrub` deliberately omits `split`: its per-`k` sweep is O(maxlen) per driver
and takes ~44 h over a fuzzed corpus (`docs/TODO.md`). The chunked pass over the fuzzed
corpus is where F-0060 came from, on a corpus the hand-written suites called green.

If the run.sh comparison anchors on `c` rejecting, value splits among the accepters stay
hidden — read camp structure with `CLUSTER=1` rather than trusting a clean comparator line.

## 7. Crashes

Any new file in `corpus/crashes/` (including a Go panic from the second steering engine, and
`slow-unit-*` from libFuzzer) is a finding candidate: reproduce it locally, minimize, attribute.
A sanitizer hit is a second net, not the oracle — but it is never noise.

## 8. Record and report

- New root cause → `findings/<id>/NOTES.md` + a row in `results/FINDINGS.md`, upstream issue
  filed against the owning repo.
- Camp explained (finding, legal divergence, benign soft axis) → add its signature to
  `results/known-clusters.txt`, with the reason.
- A snapshot worth keeping → `results/CLUSTERS.md`; the session narrative and any decision →
  `docs/STATUS-LOG.md` (dated); anything left open → `docs/TODO.md`, with what was *eliminated*.
- Never restate a fact across two of those files.

Report back: run id + date, fuzz yield, corpus before → after, camps total / accounted /
new, what each new camp turned out to be, crashes, and the open queue. If nothing is new,
say that plainly — a quiet nightly is the expected outcome and is a result.

## Timing

Bootstrap + a full 15-driver build is minutes; a cluster run over ~9k inputs is ~10 min at
`TIMEOUT=5`; the chunked pass is ~1 min per driver. Don't poll CI in a loop — differential
CI is ~8 min, the catalog job seconds.
