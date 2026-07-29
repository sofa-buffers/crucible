# Runbook — fixing the open corelib issues in parallel

Campaign tooling, not a project doc: this file describes *how to run a fix wave*, it
does not restate anything owned by `docs/` or `results/` (see `CLAUDE.md`). The board
below is a snapshot taken **2026-07-29**; re-derive it with the one-liner in §1 rather
than trusting it after a merge.

The executable form of §4–§6 is [`fix-corelib-cluster.js`](fix-corelib-cluster.js) —
one run per cluster.

---

## 1. The board

```sh
for r in corelib-c-cpp corelib-cpp corelib-cs corelib-dart corelib-go corelib-java \
         corelib-py corelib-rs corelib-rs-no-std corelib-ts corelib-zig \
         generator documentation; do
  echo "=== $r ==="
  gh issue list -R sofa-buffers/$r --state open --limit 100 \
     --template '{{range .}}#{{.number}} {{.title}}{{"\n"}}{{end}}'
done
```

28 open issues on 2026-07-29 — **20 real, 8 Renovate "Dependency Dashboard"**. The 20
are **six root causes**, not twenty bugs: 13 of them are two clauses replicated across
languages, which is exactly what makes the campaign parallel.

| # | root cause (Crucible finding) | issues | parallel? | wave |
|---|---|---|---|---|
| **C1** | CORELIB_PLAN §6.4 — a **skipped** `string` is still UTF-8-validated (F-0038) | go#57, rs#39, rs-no-std#59, java#52, cs#44, dart#22 | **6 repos, fully independent** — no shared contract, no wire-format change | 1 |
| **C2** | CORELIB_PLAN §4.8 — the fixlen-array schema `count` bound is applied **before** the element subtype decides the field is skippable (F-0042) | cs#45, dart#23, go#58, java#53, rs#40, rs-no-std#60, zig#27 | **7 repos, but only after one ABI decision** — the array-header hook must move past the `fixlen_word` *and* carry the subtype, so it changes the corelib↔generated-code contract | 0 then 2 |
| **C3** | MESSAGE_SPEC §7.3 — an over-index wrapper element is rejected before the subtype skip decides it is not an element (F-0041) | c-cpp#117, cpp#58 | 2 repos, **after a spec answer** — the issue itself raises whether §7.3 is scoped to the fixlen count word; if it is, the *other 11* impls are wrong and the fix moves to `documentation` | 0 then 3 |
| **C4** | §4.1/§5.2 — an already-overlong varint reports INCOMPLETE where INVALID wins (F-0040) | c-cpp#116 | single repo, independent | 1 |
| **C5** | generator backends | #239 (reserved-name collisions, all backends), #235 (ts fp32 sNaN must use `readFp32Raw`, §4.6), #254 (§7.3-mistyped array allocated into the declared field, F-0039) | #239/#235 independent; **#254 is held** (`d24d2ba` — hold the merge rather than weaken the §7.3 gate) and rides with C2/C3 | 1, #254 in 3 |
| **C6** | documentation#26 — a scalar exceeding its declared width is unspecified, 3-way split (F-0033) | documentation#26 | **not a fix — a ruling.** Nothing downstream can start until it lands | 0 |
| **C7** | 8× Renovate *Dependency Dashboard* | every repo | not bugs. One sweep by hand; never spend an agent on them | — |

Attribution is already done — every issue sits in the repo that can fix it (the
`CLAUDE.md` triage step). Do not re-open that question inside a fix wave; if a worker
believes an issue is misfiled, it **stops and reports**, it does not move the fix.

---

## 2. Why the family branch is the whole trick

`scripts/bootstrap.sh` vendors every corelib **and** the generator at *Crucible's own
branch* (`FAMILY_BRANCH`, default = the branch you are on), falling back to `main` per
repo when a repo does not carry it.

That gives the campaign its join point for free:

> Give every repo in a cluster the **same branch name**, then run Crucible on a branch
> of that name — and all N fixes are differentially tested **together, before any of
> them merges**. A wave that is only half-pushed still runs: the repos without the
> branch fall back to `main`, so the run measures exactly "the fixes that exist so far
> against the released rest".

Consequences that are not optional:

- **One cluster per branch name.** `fix/F-0038-skip-no-utf8-validation`,
  `fix/F-0042-array-count-after-subtype`, … Two clusters sharing a branch makes a
  regression unattributable, which is the one thing the harness exists to prevent.
- **The branch name is identical in all N repos, character for character** — it is a
  lookup key (`git ls-remote --heads`), not a label.
- For a cluster that also needs the generator (C2, C5#254), push the same branch in
  `generator` too; `bootstrap.sh` builds it from source there when its CI publishes no
  binary for that branch, and it never silently falls back to a released generator.

---

## 3. Parallel-safety rules

1. **One repo per worker, one cluster per branch.** Workers never see each other's
   checkouts.
2. **Never touch `vendor/`.** `bootstrap.sh` owns it, and when a sibling checkout
   exists it is *symlinked* — an edit there silently rewrites your working copy of
   another repo. Workers clone to scratch (`$CLAUDE_JOB_DIR/tmp/<repo>`).
3. **Decide a shared contract once, up front, or it forks N ways.** C2 changes a hook
   signature. Seven workers asked to "fix §4.8" will invent seven hook shapes. The
   wave-0 step writes the intended signature into the issue thread *first*; the fix
   workers implement it, they do not design it.
4. **`assets/test_vectors.json` is shared across corelibs.** If a cluster genuinely
   changes the shared vector set, that is its own step applied to all repos at once —
   not a line each worker edits on its own.
5. **`vendor/documentation` is never fetched by bootstrap.** A worker quoting a clause
   must check the spec repo out by hand; a §-number remembered from an issue body is
   not evidence.
6. **Workers open PRs; they never merge, never close the issue, never edit Crucible.**
   The join in §5 is what decides whether a fix is real.

---

## 4. The per-repo worker contract

Each parallel worker gets exactly one `(repo, issue, cluster-branch)` and does:

1. `gh issue view -R sofa-buffers/<repo> <n>` — the body already carries the wire
   isolates, the per-implementation verdict table, the controls, and the clause. It is
   the spec for the fix; do not re-derive it from the fuzzer.
2. Read the clause itself in the `documentation` checkout (§5 of the issue names it).
3. Clone the repo, branch **`<cluster-branch>`** off `main`.
4. Implement the fix, and add a regression test **in that repo's own suite** using the
   isolate bytes from the issue (`strict_utf8_test.go`, `malformed_test.go`, and the
   language's equivalents).
5. Build + run the repo's full test suite locally. Green, or the worker reports failure
   — it does not push a red branch.
6. Push and open a **draft** PR: title = the issue title, body = the clause, the
   isolate, the before/after verdict table, `Fixes #<n>`.
7. Report back: repo, PR URL, files touched, the tests added, and **every place the
   clause was ambiguous** — that list is the input to the next spec question.

The isolates are already in this repo under `findings/F-00NN-…/*.bin`; the issue bodies
give the same bytes in hex.

---

## 5. The join — verify the wave, once, in Crucible

Per wave, not per repo:

```sh
git switch -c <cluster-branch>          # in Crucible; FAMILY_BRANCH picks it up
scripts/bootstrap.sh                    # vendors every repo at that branch, main elsewhere
CORPUS=findings/F-00NN-…  scripts/run.sh   # the cluster's own isolates + controls
CORPUS=corpus/regression  scripts/run.sh   # the standing gate (98 inputs)
scripts/sweep.sh                           # plus the conformance/limit suites
```

The wave passes only when **both** halves hold:

- the split the cluster is about is **closed** — all 13 drivers agree, with the verdict
  the clause requires; and
- every **control** in the finding still holds. These are the ones that catch a fix that
  simply deleted the check: F-0042 rows 3 and 5 must keep rejecting (the bound applies
  when the subtype *matches*), and F-0038's `ctl_known_field_invalid_utf8` must stay
  `R invalid_msg` (strict UTF-8 on a *materialized* string is correct).

Then, and only then: PRs out of draft → merge → promote the isolates into
`corpus/regression/` → update `results/FINDINGS.md` and `docs/STATUS-LOG.md` (their
owners, per `CLAUDE.md`).

---

## 6. Wave ordering

| wave | content | agents | gated on |
|---|---|---|---|
| **0** | three decisions, serial and cheap: (a) the C2 array-hook signature, written into the seven issues; (b) the C3 §7.3-scope question — 2-impl fix or 11-impl fix; (c) documentation#26's ruling | 3 | — |
| **1** | **C1 ×6**, **C4 ×1**, generator **#239**, **#235** — three independent family branches, nothing shared | 9 | — |
| **2** | **C2 ×7** + the generator backends consuming the new hook | 8 | 0a |
| **3** | **C3 ×2**, then un-hold generator **#254** | 3 | 0b, 2 |

Waves 1 and 2 do not block each other and can run concurrently if you want the whole
board moving — they touch disjoint code paths (skip-time validation vs the fixlen-array
header) and use different branch names. Wave 3 is last because #254's merge is
deliberately held behind the §7.3 gate.

Each wave ends with §5. A wave that fails §5 does not proceed — the branch stays
unmerged and the finding stays open, which is the point of testing the family before it
lands.
