export const meta = {
  name: 'fix-corelib-cluster',
  description: 'Fix one root-cause cluster across every affected corelib in parallel, on one shared family branch, then verify the whole family in Crucible',
  whenToUse: 'When several corelibs carry the same clause-level defect (the usual shape of a Crucible finding) and you want one worker per repo. Run it once per cluster: args {"cluster":"C1"}. The board, the waves and the gating rules are in fix-corelib-issues.md.',
  phases: [
    { title: 'Clause', detail: 'pin the shared fix contract once, before any repo starts' },
    { title: 'Fix', detail: 'one worker per affected repo — branch, fix, test, draft PR' },
    { title: 'Verify', detail: 'run the family branch through Crucible: isolates, controls, regression gate' },
  ],
}

// ---------------------------------------------------------------- the board --
// Snapshot 2026-07-29. Re-check with the gh one-liner in fix-corelib-issues.md
// before a run; an issue number that moved makes a worker fix the wrong thing.
const CLUSTERS = {
  C1: {
    branch: 'fix/F-0038-skip-no-utf8-validation',
    finding: 'F-0038-skipped-string-utf8-validated',
    clause: 'CORELIB_PLAN §6.4 — skipped fields are never validated (normative)',
    summary: 'a `string` field the decoder SKIPS is still strict-UTF-8-validated, turning a never-materialized payload into INVALID',
    control: 'ctl_known_field_invalid_utf8 must STAY `R invalid_msg` — strict UTF-8 on a materialized string is correct; only its placement on the skip path is the bug',
    repos: [
      { repo: 'corelib-go', issue: 57 },
      { repo: 'corelib-rs', issue: 39 },
      { repo: 'corelib-rs-no-std', issue: 59 },
      { repo: 'corelib-java', issue: 52 },
      { repo: 'corelib-cs', issue: 44 },
      { repo: 'corelib-dart', issue: 22 },
    ],
  },
  C2: {
    branch: 'fix/F-0042-array-count-after-subtype',
    finding: 'F-0042-fixlen-array-count-bound-precedes-subtype',
    clause: 'CORELIB_PLAN §4.8 + MESSAGE_SPEC §7.3 — subtype first, schema bound only on a field that survives it',
    summary: 'the fixlen-array schema `count` bound is applied before the element subtype decides the field is skippable; a message truncated between the count word and the fixlen_word is judged on the count alone',
    control: 'rows 3 and 5 (over-count with a MATCHING fp32 subtype) must keep rejecting, and row 6 must keep round-tripping byte-identically — the bound applies exactly when the subtype matches',
    // The hook signature is a cross-repo ABI. The Clause phase pins it; the fix
    // workers implement it. Do not let seven workers design it seven ways.
    abi: true,
    repos: [
      { repo: 'corelib-cs', issue: 45 },
      { repo: 'corelib-dart', issue: 23 },
      { repo: 'corelib-go', issue: 58 },
      { repo: 'corelib-java', issue: 53 },
      { repo: 'corelib-rs', issue: 40 },
      { repo: 'corelib-rs-no-std', issue: 60 },
      { repo: 'corelib-zig', issue: 27 },
    ],
  },
  C3: {
    branch: 'fix/F-0041-skip-before-overindex',
    finding: 'F-0041-overindex-reject-precedes-7-3-skip',
    clause: 'MESSAGE_SPEC §7.3 — against a schema bound, the skip clause wins',
    summary: 'an array-wrapper element whose id is past the schema `count` AND whose wire type contradicts the declared element type is rejected on the id, where §7.3 requires it to be skipped first',
    control: 'the correctly-typed over-index vector must keep rejecting on all 13, and the in-range mistyped vector must keep accepting on all 13 — each rule alone is already unanimous',
    // Blocked: the issue itself asks whether §7.3 is scoped to the fixlen count
    // word. If it is, these 2 impls are right and the other 11 are wrong.
    blockedOn: 'the §7.3-scope question in corelib-c-cpp#117 must be answered in `documentation` before either repo changes',
    repos: [
      { repo: 'corelib-c-cpp', issue: 117 },
      { repo: 'corelib-cpp', issue: 58 },
    ],
  },
  C4: {
    branch: 'fix/F-0040-overlong-varint-invalid',
    finding: 'F-0040-overlong-varint-deferred-to-incomplete',
    clause: 'CORELIB_PLAN §4.1/§5.2 — INVALID wins over INCOMPLETE; the width guard must fire on the byte that makes the varint overlong',
    summary: 'an already-overlong varint is reported INCOMPLETE instead of INVALID — the width guard fires one byte too late',
    control: 'a legal maximum-width varint must keep decoding, and a genuinely truncated (not overlong) varint must stay INCOMPLETE',
    repos: [{ repo: 'corelib-c-cpp', issue: 116 }],
  },
}

const key = (args && args.cluster) || 'C1'
const C = CLUSTERS[key]
if (!C) throw new Error(`unknown cluster ${key} — pick one of ${Object.keys(CLUSTERS).join(', ')}`)
if (C.blockedOn) log(`!! ${key} is gated: ${C.blockedOn} — run this only once that is settled`)

log(`${key}: ${C.repos.length} repos on one family branch \`${C.branch}\` — ${C.clause}`)

const SCRATCH = '$CLAUDE_JOB_DIR/tmp'
const RULES = `
Hard rules (from .claude/workflows/fix-corelib-issues.md):
- NEVER touch this repo's vendor/ — bootstrap.sh owns it and symlinks sibling checkouts,
  so an edit there rewrites someone's working copy. Clone to ${SCRATCH}/<repo>.
- NEVER edit anything in the Crucible checkout. The verification join is a separate step.
- Do not merge, do not close the issue, do not take the PR out of draft.
- The branch name is a lookup key for bootstrap.sh: it must be exactly \`${C.branch}\`
  in every repo, character for character.
- If you conclude the issue is misfiled (codegen vs corelib), STOP and report that
  instead of moving the fix yourself.
`

// ------------------------------------------------------- 1. the fix contract --
// One reading of the clause, shared by every worker. For an ABI cluster this is
// the only thing standing between 7 fixes and 7 incompatible hook signatures.
phase('Clause')
const contract = await agent(`
You are pinning the shared fix contract for Crucible finding ${C.finding} before any repo is touched.

Cluster: ${C.summary}
Governing clause: ${C.clause}

Do this:
1. Read the finding write-up at findings/${C.finding}/NOTES.md in the Crucible checkout, and the
   .bin isolates next to it.
2. Read the clause itself in the documentation repo. bootstrap.sh does NOT fetch vendor/documentation,
   so check it out yourself if it is missing (git clone https://github.com/sofa-buffers/documentation
   into ${SCRATCH}). A clause quoted from an issue body is not evidence.
3. Read the issue body on ONE representative repo: gh issue view -R sofa-buffers/${C.repos[0].repo} ${C.repos[0].issue}
${C.abi ? `4. This cluster changes the corelib -> generated-code contract. Decide the exact hook signature ONCE:
   what the array-header hook is called, where in the decode order it fires relative to the fixlen_word,
   and how the element subtype reaches generated code. Name it concretely per language family.
   State what the generator backends must then emit. This decision is the deliverable.` : `4. State exactly which code path moves and which must not change.`}

Return the contract: what every implementation must change, what MUST NOT regress (the controls),
and the wire isolates with their required verdicts. Be concrete enough that a worker who reads only
your contract and its own repo's issue implements the same thing as the other ${C.repos.length - 1}.
`, { label: `contract:${key}`, schema: {
  type: 'object',
  required: ['change', 'mustNotRegress', 'vectors'],
  properties: {
    change: { type: 'string', description: 'what every impl must change, concretely' },
    abi: { type: 'string', description: 'the pinned hook/API signature, if this cluster changes one; else empty' },
    mustNotRegress: { type: 'array', items: { type: 'string' } },
    vectors: { type: 'array', items: {
      type: 'object',
      required: ['bytes', 'required'],
      properties: { bytes: { type: 'string' }, required: { type: 'string' }, note: { type: 'string' } },
    } },
    specGaps: { type: 'array', items: { type: 'string' }, description: 'anything the clause does not actually settle' },
  },
} })

if (contract.specGaps && contract.specGaps.length) {
  log(`spec gaps surfaced before any fix: ${contract.specGaps.length} — see the final report`)
}

// ------------------------------------------------- 2. one worker per corelib --
phase('Fix')
const fixes = await parallel(C.repos.map(r => () => agent(`
Fix sofa-buffers/${r.repo}#${r.issue} — one repo, one issue, one branch.

The issue body is the spec for this fix: it carries the wire isolates, the per-implementation
verdict table and the controls. Read it first and do not re-derive it:
  gh issue view -R sofa-buffers/${r.repo} ${r.issue}

The shared fix contract, already pinned for all ${C.repos.length} affected corelibs — implement THIS,
do not redesign it:
${JSON.stringify(contract, null, 2)}

Steps:
1. git clone https://github.com/sofa-buffers/${r.repo} ${SCRATCH}/${r.repo} && branch \`${C.branch}\` off main.
2. Implement the fix.
3. Add a regression test in that repo's OWN suite using the isolate bytes from the issue
   (e.g. Go: strict_utf8_test.go / malformed_test.go; mirror the local convention in other languages).
   The controls go in as tests too — they are what catches a "fix" that just deleted the check:
   ${JSON.stringify(contract.mustNotRegress)}
4. Build and run the repo's FULL test suite. If it is red, stop and report — do not push a red branch.
   If the toolchain is missing, say so plainly rather than skipping the suite silently.
5. Push \`${C.branch}\` and open a DRAFT PR: title = the issue title, body = the clause, the isolate
   bytes, the before/after verdict, and \`Fixes #${r.issue}\`.
${RULES}
Return: the PR url (or why there is none), files touched, tests added, whether the suite was green,
and every place the clause was ambiguous while you implemented it.
`, { label: `fix:${r.repo}`, phase: 'Fix', schema: {
  type: 'object',
  required: ['repo', 'pushed', 'suiteGreen', 'summary'],
  properties: {
    repo: { type: 'string' },
    pushed: { type: 'boolean' },
    prUrl: { type: 'string' },
    suiteGreen: { type: 'boolean' },
    filesTouched: { type: 'array', items: { type: 'string' } },
    testsAdded: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    ambiguities: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'string', description: 'why this repo could not be fixed, if it could not' },
  },
} })))

const done = fixes.filter(Boolean)
const pushed = done.filter(f => f.pushed && f.suiteGreen)
log(`${pushed.length}/${C.repos.length} repos pushed green to ${C.branch}`)
if (done.length < C.repos.length) log(`!! ${C.repos.length - done.length} worker(s) died — those repos are untouched`)

// ------------------------------------------------------ 3. the family join ----
// Repos without the branch fall back to main, so a half-finished wave still runs:
// it measures the fixes that exist against the released rest.
phase('Verify')
const verdict = pushed.length === 0
  ? { passed: false, report: 'nothing pushed — nothing to verify' }
  : await agent(`
Verify the family branch \`${C.branch}\` in the Crucible checkout. ${pushed.length} of ${C.repos.length}
corelibs pushed a green fix branch (${pushed.map(f => f.repo).join(', ')}); repos without the branch
fall back to main, which is fine — the run then measures the fixes that exist against the released rest.

1. In the Crucible repo, create/switch to a branch named exactly \`${C.branch}\` (bootstrap.sh reads
   FAMILY_BRANCH from the current branch), then run scripts/bootstrap.sh. Confirm from its stderr which
   repos it took at ${C.branch} and which fell back to main — quote that list in your report.
2. CORPUS=findings/${C.finding} scripts/run.sh   — the cluster's isolates AND its controls.
3. CORPUS=corpus/regression scripts/run.sh       — the standing gate.
4. scripts/sweep.sh                              — the conformance/limit suites.
Never call oracle/comparator.py directly on drivers/*/build — go through run.sh.

The wave passes only if BOTH hold:
 - the split this cluster is about is closed: all 13 drivers agree, with the verdict the clause requires;
 - every control still holds: ${JSON.stringify(contract.mustNotRegress)}
   ${C.control}

Report per-driver verdicts for each isolate, the regression-gate result, and — if it failed — which
driver and which vector, precisely enough to hand back to that repo's worker. Do not merge anything,
do not take PRs out of draft, do not edit results/ or docs/.
`, { label: `verify:${key}`, schema: {
  type: 'object',
  required: ['passed', 'report'],
  properties: {
    passed: { type: 'boolean' },
    splitClosed: { type: 'boolean' },
    controlsHeld: { type: 'boolean' },
    regressionGate: { type: 'string' },
    familyRefs: { type: 'string', description: 'which repos were taken at the family branch vs main' },
    failures: { type: 'array', items: { type: 'string' } },
    report: { type: 'string' },
  },
} })

return {
  cluster: key,
  branch: C.branch,
  finding: C.finding,
  contract,
  fixes: done,
  verdict,
  nextSteps: verdict.passed
    ? 'PRs out of draft -> merge -> promote the isolates into corpus/regression -> update results/FINDINGS.md and docs/STATUS-LOG.md'
    : 'branch stays unmerged and the finding stays open — hand the failures back to the named repo worker',
}
