export const meta = {
  name: 'corelib-readme-tighten',
  description: 'Guard then tighten the README of each remaining corelib, one repo at a time',
  whenToUse:
    'After corelib-go#125 and corelib-cpp#122 established the recipe. Rolls the same guard-first-then-cut pass over the other ten corelibs. Strictly sequential: one repo in flight at any moment, because the agents build and test inside the shared vendor/ checkouts.',
  phases: [
    { title: 'Tighten', detail: 'one corelib per agent, strictly sequential' },
  ],
}

// ---------------------------------------------------------------- the roster --
//
// The ten ports corelib-go and corelib-cpp did not cover, ascending by README
// size so a flaw in the recipe surfaces on a cheap repo first. `note` carries
// what this repo specifically needs watching for.
const REPOS = [
  {
    repo: 'corelib-kotlin-mp',
    lines: 449,
    note:
      'Smallest README of the family — it may already be close to right. Adding the ' +
      'guard is still in scope; cutting is not mandatory. Two drivers, one corelib ' +
      '(crucible#167), so check whether the README explains both.',
  },
  {
    repo: 'corelib-java',
    lines: 452,
    note:
      'Carries a top-level "## Generated-code support layer" and "## Feature flags" ' +
      'that are NOT in §9\'s section list. Demote them to `###` subsections of the ' +
      'chapter they belong to rather than deleting their content — §9: "do not invent ' +
      'new top-level sections".',
  },
  {
    repo: 'corelib-dart',
    lines: 526,
    note:
      'Double-only float target: CORELIB_PLAN §6.5 obliges it to document the raw ' +
      'fp32-bytes path for signaling NaN. That fact must survive the cut.',
  },
  {
    repo: 'corelib-cs',
    lines: 590,
    note:
      'Unicode-string target (§6.4): strictness is mandatory and the SOFAB_STRICT_UTF8 ' +
      'option may legitimately be absent. Do not "restore" a knob the port does not have.',
  },
  {
    repo: 'corelib-py',
    lines: 622,
    note:
      'Two profiles (py-cython / py-pure). Check the README covers both, and that the ' +
      'guard does not assume one. Build artifacts inside src/ have shadowed fresh ' +
      'sources here before — never `git add` anything but the README and the guard.',
  },
  {
    repo: 'corelib-rs',
    lines: 673,
    note:
      'Ships a "### Choosing between the two Rust corelibs" subsection under Benchmarks, ' +
      'like corelib-cpp does. §9.8 requires it to stay a subsection of `## Benchmarks`.',
  },
  {
    repo: 'corelib-ts',
    lines: 693,
    note:
      'Double-only float target (§6.5 raw fp32 path, as dart). Also a JS/TS lossy-encoder ' +
      'hazard §6.4 calls out by name (TextEncoder replaces unpaired surrogates) — if the ' +
      'README documents that, keep it.',
  },
  {
    repo: 'corelib-zig',
    lines: 713,
    note:
      'Byte-container target where generated code materializes strings, so §6.4 requires ' +
      'the `utf8_valid` primitive to be documented. Zig 0.16 tooling is immature; if the ' +
      'test runner cannot be driven here, say so rather than claiming a green gate.',
  },
  {
    repo: 'corelib-rs-no-std',
    lines: 727,
    note:
      'Heap-free profile. §6 lets it bound the lazy-sequence hold-back depth and §5.1 lets ' +
      'it declare a non-1 MIN_OUTPUT_BUFFER — both MUST stay documented, they are the ' +
      'allowances that make its bytes differ from corelib-rs.',
  },
  {
    repo: 'corelib-c-cpp',
    lines: 818,
    note:
      'CROSS-REPO ANCHOR: corelib-cpp\'s README links to this one\'s ' +
      '"#what-the-speed-difference-actually-is" heading. Do not rename or remove that ' +
      'heading. It is also the source of truth for assets/test_vectors.json (§7.1/§8), so ' +
      'keep whatever the README says about that provenance.',
  },
]

// -------------------------------------------------------------- the recipe --
//
// What corelib-go#125 and corelib-cpp#122 actually did, written so an agent can
// repeat it without having read either PR.
const RECIPE = `
You are tightening ONE corelib README. Two reference PRs did this already and are
worth reading first if you can reach them:
  - https://github.com/sofa-buffers/corelib-go/pull/125
  - https://github.com/sofa-buffers/corelib-cpp/pull/122

Work inside /workspace/vendor/<repo>. Read /workspace/CLAUDE.md first: everything
you author is in English, and the doc single-source-of-truth rules there apply.
CORELIB_PLAN §9 (the README contract) is at
/workspace/vendor/documentation/CORELIB_PLAN.md — read §9 in full before editing,
plus §5.1, §6.4 and §9.6, which name facts a README must carry.

Do the steps in this order. Do not reorder them: the guard exists to make the cut
safe, so it has to be in place and proven BEFORE anything is removed.

== 1. GUARD FIRST ==

Find out whether the repo already has a README structure test (corelib-cpp had
test/test_readme_structure.sh; corelib-go had readme_shape_test.go). Extend it if
so, create one if not, following the repo's own test convention. Where the repo
has no convenient convention, a portable POSIX shell or Python script registered
in the repo's own test runner is right — it must run in CI, not just by hand.

The guard must check, at minimum:
  - §9   the \`## \` top-level sections are exactly the prescribed list, in order:
         "SofaBuffers <Language> library", "Why this design", "Usage",
         "Memory handling", "Build & test", "Benchmarks". No invented sections.
  - §9.1 the centered logo, the "# SofaBuffers" title, the tagline, the org link.
  - §9.2 a badge block carrying CI, coverage and Docs badges, in that order.
  - §9.4 no API-documentation section at any heading level.
  - §9.5 the Usage chapter still shows each example the plan lists.
  - §6.4 the port's strict-UTF-8 knob is documented — SKIP this check for a
         Unicode-string target that legitimately has no such option (§6.4 lets
         those omit it); say in the guard's comments which case this port is.
  - §9.6 MIN_OUTPUT_BUFFER is stated inside the "## Memory handling" chapter.
  - §6.1.1 no spelling outside the closed generated-object name set — reject
         marshal, unmarshal, serialize_to, to_bytes, from_bytes, decode_from,
         decode_into.
  - every in-document link "](#anchor)" resolves to a heading in the document.

Then prove the guard twice:
  a) run it against the README AS IT STANDS, unmodified. It MUST pass. If it
     fails, you have found a real defect — fix the README minimally for that one
     point, and report it as a finding.
  b) negative-test it on a scratch copy: rename a Usage subsection, move
     MIN_OUTPUT_BUFFER out of the memory chapter, break an anchor. Each must
     fail. A guard that cannot fail is not a guard.

Commit the guard as its own commit before touching the README.

== 2. THEN CUT ==

The rule, and it is the whole method:

  Shorten by removing ONLY justification, never facts. Every assertion, every
  runnable example and every table stays. What goes is text that explains WHY
  something is so, pre-empts an objection nobody raised, or retells the spec.
  Sections and their order do not change, and any per-symbol detail you remove
  must already exist in the port's API documentation — the thing the Docs badge
  points at, which §9.4 makes the single entry point for exactly this.

Concrete patterns that are safe to cut, all of them tells of machine-written docs:
  - a bold lead-in on every paragraph, used as rhythm
  - contrast couplets ("not X, but Y", "discarded is not unvalidated")
  - trailing justification clauses ("..., because ...", "that is why ...")
  - sentences answering objections nobody raised
  - §-clause citations in running prose (link the spec once instead)
  - CHANGELOG material: what a past version did, what was removed in 0.x, a
    benchmark figure measured against an implementation that no longer exists.
    A README states what IS. Check whether a test or a code comment already owns
    the fact before deleting it — usually one does.

The counterweight, so you do not cut too far:
  - keep every table (highest information per line, and readers use them)
  - keep every runnable example; if you rewrite one, you must be able to verify
    it compiles/runs, otherwise restore the original verbatim. Shipping wrong
    example code is worse than shipping long example code.
  - §9.7 wants Build & test brief ("the commands and a sentence each") and §9.6
    wants Memory handling to be ownership and lifetime, not an API listing —
    those two chapters are usually where the most fat is.

Do not cut toward a line target. If a README is already lean, say so and leave it.

== 3. AUDIT THE LOSS ==

Mechanically, not by feel. Diff the set of backticked identifiers in the old
README against the new one. For EVERY identifier that no longer appears, locate
where it still lives: the port's API docs (doc comments / doxygen / docstrings),
the CI workflow, the bench tooling, or the test that owns it. Also diff the URLs
and the numbers.

Report the ones that live NOWHERE — those are the real deletions, and the user
wants them named rather than discovered later.

== 4. VERIFY ==

Read .github/workflows/ and run EVERY gate the repo's CI runs, not just its
tests: formatters, linters, type checkers, every build configuration. CI does not
run on a plain branch push in these repos, so local is the only signal.

If a toolchain is genuinely unavailable in this workspace, say which gate you
could not run and why. Never report a gate as green that you did not execute.

== 5. SHIP ==

Branch name: docs/readme-tighten. Two commits (guard, then cut), messages in
English ending with:
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

Push and open a PR against main titled
"docs: guard the README's content, then tighten it"
with a body stating: what the guard checks and that it passed on the unmodified
README, the before/after numbers (total lines, prose words, example lines), what
went beyond trimming rationale, the loss audit result, and exactly which gates
you ran locally.

Then leave the checkout on main (git checkout main) so the vendor tree is clean
for the next Crucible run, and never git-add anything but the README and the
guard file — build artifacts in these trees have shadowed fresh sources before.
`

const RESULT = {
  type: 'object',
  additionalProperties: false,
  required: ['repo', 'guard', 'before', 'after', 'gatesRun', 'trulyLost', 'prUrl', 'notes'],
  properties: {
    repo: { type: 'string' },
    guard: {
      type: 'object',
      additionalProperties: false,
      required: ['action', 'file', 'passedOnUnmodifiedReadme', 'negativeTested'],
      properties: {
        action: { type: 'string', enum: ['created', 'extended', 'none'] },
        file: { type: 'string' },
        passedOnUnmodifiedReadme: { type: 'boolean' },
        negativeTested: { type: 'boolean' },
      },
    },
    before: {
      type: 'object',
      additionalProperties: false,
      required: ['lines', 'proseWords', 'codeLines'],
      properties: {
        lines: { type: 'integer' },
        proseWords: { type: 'integer' },
        codeLines: { type: 'integer' },
      },
    },
    after: {
      type: 'object',
      additionalProperties: false,
      required: ['lines', 'proseWords', 'codeLines'],
      properties: {
        lines: { type: 'integer' },
        proseWords: { type: 'integer' },
        codeLines: { type: 'integer' },
      },
    },
    gatesRun: { type: 'array', items: { type: 'string' } },
    gatesSkipped: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['gate', 'why'],
        properties: { gate: { type: 'string' }, why: { type: 'string' } },
      },
    },
    droppedIdentifiers: { type: 'integer' },
    trulyLost: {
      type: 'array',
      description: 'Identifiers/facts that now live nowhere. Empty is the good answer.',
      items: { type: 'string' },
    },
    defectsFound: {
      type: 'array',
      description: 'Real errors found in the README or repo while doing this (e.g. a wrong count, a dead link).',
      items: { type: 'string' },
    },
    prUrl: { type: ['string', 'null'] },
    notes: { type: 'string' },
  },
}

// ------------------------------------------------------------------- run it --
//
// STRICTLY SEQUENTIAL. One agent in flight at a time — no parallel(), no
// pipeline(). The agents build and test inside /workspace/vendor/, and two
// concurrent build jobs corrupt each other's checkouts even when they are my
// own; several of these repos also need the whole machine to compile.
//
// args: { only: ["corelib-rs", ...] } restricts the roster.
//        { dryRun: true }            does everything except push and open a PR.

phase('Tighten')

const only = args && Array.isArray(args.only) ? args.only : null
const dryRun = Boolean(args && args.dryRun)
const roster = only ? REPOS.filter((r) => only.includes(r.repo)) : REPOS

log(`${roster.length} corelib README(s), one at a time${dryRun ? ' — DRY RUN, no push, no PR' : ''}`)

const results = []
for (let i = 0; i < roster.length; i++) {
  const r = roster[i]
  log(`[${i + 1}/${roster.length}] ${r.repo} (README is ${r.lines} lines)`)

  const prompt = [
    `Repository: /workspace/vendor/${r.repo} (README.md is currently ${r.lines} lines).`,
    ``,
    `Specific to this port: ${r.note}`,
    ``,
    dryRun
      ? `DRY RUN: do every step including the local commits, but do NOT push and do NOT open a PR. Report the branch name instead of a URL, and set prUrl to null.`
      : `Push the branch and open the PR as described.`,
    ``,
    RECIPE,
  ].join('\n')

  let out = null
  try {
    out = await agent(prompt, {
      label: `readme:${r.repo}`,
      phase: 'Tighten',
      schema: RESULT,
    })
  } catch (e) {
    log(`${r.repo}: agent failed — ${e && e.message ? e.message : e}`)
  }

  if (!out) {
    results.push({ repo: r.repo, failed: true })
    log(`${r.repo}: no result recorded, continuing with the next repo`)
    continue
  }

  results.push(out)
  const delta =
    out.before && out.after
      ? `${out.before.lines}->${out.after.lines} lines, prose ${out.before.proseWords}->${out.after.proseWords} words`
      : 'no measurement returned'
  log(`${r.repo}: ${delta}; guard ${out.guard ? out.guard.action : '?'}; PR ${out.prUrl || '(none)'}`)
  if (out.trulyLost && out.trulyLost.length) {
    log(`${r.repo}: ${out.trulyLost.length} fact(s) now live nowhere — see the report`)
  }
}

const done = results.filter((x) => !x.failed)
log(`finished: ${done.length}/${roster.length} corelibs processed`)

return {
  dryRun,
  processed: done.length,
  attempted: roster.length,
  failed: results.filter((x) => x.failed).map((x) => x.repo),
  prs: done.map((x) => x.prUrl).filter(Boolean),
  guardsCreated: done.filter((x) => x.guard && x.guard.action === 'created').map((x) => x.repo),
  guardsUnproven: done
    .filter((x) => x.guard && !(x.guard.passedOnUnmodifiedReadme && x.guard.negativeTested))
    .map((x) => x.repo),
  factsLostAnywhere: done.flatMap((x) => (x.trulyLost || []).map((f) => `${x.repo}: ${f}`)),
  defects: done.flatMap((x) => (x.defectsFound || []).map((d) => `${x.repo}: ${d}`)),
  gatesSkipped: done.flatMap((x) => (x.gatesSkipped || []).map((g) => `${x.repo}: ${g.gate} — ${g.why}`)),
  results: done,
}
