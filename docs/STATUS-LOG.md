# Crucible — status log (chronological journal)

The **changelog + decision log**: dated, session-by-session history of what changed,
which decisions were taken and why, and where the build deviates from PLAN. This is
**history**, not the authoritative current state:

- The current as-built state is [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Per-finding truth (root cause, resolution, links) and codegen defects (G-00NN) are
  in [`../results/FINDINGS.md`](../results/FINDINGS.md).
- Root-cause clusters are in [`../results/CLUSTERS.md`](../results/CLUSTERS.md).

Entries below are append-only and may contain running totals that were later
superseded; trust `FINDINGS.md` for the current tally.

---

## Findings & tracking
Reproducers in `findings/<id>/`; catalog in `results/FINDINGS.md`; codegen-bug log
in `results/FINDINGS.md`. Fixes live in the **owning repos** (done in fresh contexts);
Crucible is the catalog + verifier.

**Nightly 32444261107 (2026-08-21) — one new camp, and it is a missed site of a class we
had already closed.** The run was otherwise unremarkable: ~11.1 M execs, 51 new inputs
harvested by the Go steering engine (which is reporting its harvest again since #166), no
crashes, no sanitizer hits, no `slow-unit-*`. It exited non-zero on a single five-byte
input, `ce 0c 22 e3 30`, where **py-cython and py-pure alone say `INCOMPLETE`** and the
other fifteen drivers reject it.

Triaged to **F-0062 / G-0039** ([generator#377](https://github.com/sofa-buffers/generator/issues/377)): generated Python checks a **blob wrapper-array element**'s
`maxlen` *after* `d.bytes()` rather than at the `fixlen_word`, so an element that is both
over-`maxlen` and truncated reaches end-of-input before the check runs. Write-up and the
five vectors are in `findings/F-0062-py-blob-array-element-maxlen-checked-after-payload/`.

**This is the F-0043 class at a site generator#267 never covered — not a regression of
it.** That ticket is scoped `[rust, rust-no-std, java, csharp, zig]`, and the control
`56 1a e3 30` proves Python's *plain*-field path is fixed. What survives is the blob
**wrapper element**, which is the one site of five in the generated `message.py` that does
not use `fixlen_len()`; the string wrapper element one field earlier does. Deciding this by
reading the emitter rather than by re-running the old reproducer is what kept it from being
filed as "F-0043 came back".

*Attribution — the generator, established not inferred.* `maxlen` is a schema fact, so
corelib-py cannot know it and `INCOMPLETE` is the only answer it can give for a declared
780-byte blob with no payload. Its `schema_bounded()` docstring hands the obligation to the
caller in as many words — declaring is "a **promise to enforce**" — and that call *is*
emitted here, so the generated code switches the receiver-side `max_blob_len` cap off and
then enforces nothing at the word. The wrong verdict is what the oracle sees; the removed
cap is why this is worth fixing promptly. Both Python profiles fail identically (so: not
the Cython path), and within one language `string_array` and `nested.bytes_field` are both
correct (so: one emitter site, not the wrapper machinery or the blob type).

*The controls are the deliverable, not the reproducer.* Four of them, each changing exactly
one thing; the load-bearing one is `ce 0c 22 23` — the same truncation with an in-bound
declared length, unanimously `INCOMPLETE` including Python. Without it, a "fix" that simply
dropped the bound would also turn the finding green. Filed with them for that reason.

**Decision — the camp goes into `results/known-clusters.txt` while the finding is open.**
The file's rule is that a camp belongs there once *explained*, not once *fixed*; leaving it
out would keep the nightly red on a catalogued finding, which is precisely the cry-wolf
failure the file exists to prevent. The row names the reason and carries the instruction to
delete it when the fix lands, so a return then reads as NEW. Verified: `2/2 camps accounted
for, no new camp`.

*Measurement.* CI's 10 969 inputs merged into the local corpus, 19 157 → **19 847** (union,
not minimized, per the 2026-08-03 policy). Clustered at the `main` family — corelibs at
their 2026-08-21 tips, sofabgen `0.0.0-20260821072613-fdb72c0ea113`: **9 127 agree, 10 720
diverge → 2 camps**, the benign java/kotlin-jvm `incomplete_value` row and this one. So
nothing else new surfaced in a corpus nearly twice the size of CI's.

*Two environment notes, neither a repo defect.* **`kotlin-native` was missing from this
workspace and has been installed.** The image predates `34c0702` (2026-08-18), the commit
that added both the Kotlin driver and the Dockerfile's Kotlin/Native stage — so
`KONAN_DATA_DIR=/opt/konan` was set but empty, `kotlinc` had no native front-end, and
`roster.sh build` aborted the whole gate rather than compare a subset (by design). Fixed by
running that Dockerfile stage's own steps against the live container: the
`kotlin-native-prebuilt-linux-x86_64-2.4.10` distribution plus the LLVM 21 / LLDB / libffi
dependencies it fetches lazily on first compile — 1.8 GB under `/opt/konan`. **The Dockerfile
needed no change**; a devcontainer rebuild would have sufficed. The first local measurement
therefore ran on 16 of 17 drivers and was **re-measured on all 17**: identical counts, with
`kotlin-native` rejecting `r0` exactly as CI reported.
Second: a **stale compiled `.so` survived the vendor checkout** again —
`vendor/corelib-py/build/lib.../_speedups*.so` — and was removed before measuring. That is
the same trap as 2026-08-18 on corelib-py#96, and it would have been measured against the
*old* Python corelib had it stood.

*The other two oracles were run over the same corpus, since the round-trip oracle is not
the whole net.* The **materialized** (element-access) pass is green — 111 × 16 drivers, 0
divergences, and 0/111 on the C-anchor conformance check, so no value defect hides behind
the agreeing verdicts. The **chunked** pass (`--modes chunk,scrub`) is green too: 16
chunk-capable drivers x 19 847 inputs x 7 chunkings, **0 chunk-invariance mismatches**,
`kotlin-native` included (39 min). `split` was deliberately omitted, as its per-`k` sweep is
~44 h over a fuzzed corpus (`docs/TODO.md`).

**The encode pass over the same corpus did NOT complete and is unexplained — open.** It
printed `differential comparison over 19847 input(s)` and then exited 1 with *no* summary
line, no divergence count and no traceback (stderr was captured, so a Python exception would
have been in the log). Silent death with a captured stderr points at the process being
killed rather than failing — OOM is the first hypothesis, since `run-encode.sh` was handed
34.5 MB across the full 17-driver roster — but that is a **hypothesis, not a diagnosis**;
nothing here has been established yet. Do not read the earlier "encode" line in this
session's report as green. Next step: re-run it alone with the roster trimmed, watching
`dmesg`/exit signal, and if it is OOM decide whether the pass needs batching.

*A note on that pass, because the first attempt looked like a finding and was not.* It first
died with a `TimeoutExpired` on the cpp driver, which reads exactly like a hang. It was the
fixed 120 s per-feed cap in `oracle/chunk_invariance.py` — a cap that file's own comment
documents as too small for a fuzzed corpus, and makes overridable via `CHUNK_FEED_TIMEOUT`.
One driver run gets the *whole* corpus, so the cap scales with corpus size: at 34.5 MB and
`SOFAB_CHUNK=1` that is 34.5 M single-byte feeds. Re-run at `CHUNK_FEED_TIMEOUT=2400` it
passes clean. The skill's step-6 command line does not mention the override; anyone running
that pass over a grown `corpus/interesting` needs it.


---

**The nightly's second steering engine has been throwing its whole harvest away since
2026-08-14 (found 2026-08-18, triaging run 32096008437).** The nightly's *own* verdict was
quiet — one camp, already accounted for, no crashes — but the run was red in a place nobody
has to look at: the Go step is `continue-on-error`, so its failure never coloured a run.
Five consecutive nightlies (2026-08-14 … 2026-08-18) end that step with the same three
lines and nothing else:

```
PASS
ok  	crucible/driver/go	452.244s
##[error]Process completed with exit code 1.
```

`PASS` means the fuzzing itself was fine. What is missing is everything `fuzz-go.sh` prints
*after* it — the harvest count, the crash scan, the corpus total. The step died between the
fuzzer stopping and its first report.

*Which line, established rather than guessed.* Exactly one command in that stretch had its
stderr discarded — `PKG=$(cd "$GODIR" && … go list … 2>/dev/null)` — and the script runs
under `set -e`, so a failing `go list` ends it instantly and silently. Replaying the old
script against a `go` shim whose `list` always fails reproduces the CI log exactly: `PASS`,
`ok`, exit 1, not one further word.

*Why it earns a session.* The C pacemaker is saturated on this schema. Over its full
30-minute budget in this run it moved `cov: 667 → 667`, `ft: 4731 → 4732`, `corp: 481 → 482`
— one new feature, one new unit, in ~7.7M executions, every other event a `REDUCE`. The Go
engine, on a quarter of that budget, reported **194 new interesting inputs** (its corpus
10493 → 10687) in 7m31s. Those are precisely the inputs a C-steered corpus does not reach,
which is the whole reason the second engine exists — and every one was dropped, five nights
running. `nightly.yml` caches only `corpus/interesting`, so nothing survived in `$GOCACHE`
either.

*The fix, and what it deliberately does not do.* `scripts/fuzz-go.sh` no longer lets cache
discovery fail the step: `go env GOCACHE` and `go list` are each guarded, their stderr is
**printed** rather than discarded, the import path falls back to the `module` line of
`drivers/go/go.mod` (the one line that `go list` call was after), and the cache directory
falls back to a search for the single `FuzzProbe` directory under `$GOCACHE/fuzz`. A harvest
that finds nothing now says so out loud. The step still exits with `go test`'s own status,
so a Go panic remains a crash finding rather than a harness error.

Verified both ways in a worktree: with `go list` working, 465 inputs harvested, exit 0; with
the shim making it fail, the warning and the underlying error are printed, the `go.mod`
fallback takes over, 483 inputs harvested, exit 0.

*And with the error finally visible, the cause took one run.* A dispatched nightly on the fix
(run 32126917676) printed what five nights had swallowed:

```
==> [go-fuzz] WARNING: 'go list' failed — falling back to go.mod:
    error obtaining VCS status: exit status 128
    	Use -buildvcs=false to disable VCS stamping.
==> [go-fuzz] 41 new input(s) harvested into interesting
==> [go-fuzz] corpus now 10319 input(s); go test exit 0
```

`go list` stamps VCS metadata, which shells out to git; in the CI container the checkout is
not owned by the build user, so git exits 128 and takes `go list` with it. `go build` and
`go test` never trip it, which is why only this one call died. The call now passes
`-buildvcs=false`, so the nightly stops relying on the fallback — the fallback stays, because
the lesson is that this step must not be able to die of a lookup. That run also carried the
whole fix end to end: **41 inputs harvested, step exit 0, no red step in the run.**

**The streaming gates' feed cap is sized for the hand-written corpora, not for a fuzzed one
(measured 2026-08-18).** Step 6 of a nightly triage points `run-chunked.sh` at
`corpus/interesting`. Over tonight's 10270-input corpus that died with
`subprocess.TimeoutExpired ... timed out after 120 seconds` on `cpp`, after `c`, `rust-std`
and `rust-nostd` had each passed 7 chunkings — which reads exactly like a hang in one driver.

It is arithmetic. `feed()` hands a driver the **whole corpus in one run**, so the cap scales
with corpus size rather than with an input, and `SOFAB_CHUNK=1` turns 12.5 MB into 12.5M
single-byte feeds. Measured on the `cpp` driver, quiet machine:

| inputs | whole-message | `SOFAB_CHUNK=1` |
|---|---|---|
| 500 | 0.13 s | 6.34 s |
| 1000 | 0.11 s | 12.69 s |
| 2000 | 0.17 s | 35.94 s |
| 4000 | 0.32 s | 79.08 s |

Linear, ~12500 inputs/s whole against ~50/s at one byte at a time; 10270 extrapolates to
~200 s against a 120 s cap. No input hangs — the same corpus completes whole in under a
second.

CI never meets this: `replay.yml` runs the chunked gate over `corpus/regression` and the
seeds, which are small. Only the manual step-6 pass over a fuzzed corpus does, and there the
fixed cap turned a legitimate long run into a traceback. `CHUNK_FEED_TIMEOUT` (and
`ENCODE_FEED_TIMEOUT` for the encode twin) now override it, default unchanged at 120.

*With the cap sized, the pass ran, and it is green:* **10270 inputs x 7 chunkings x 14
drivers, `TOTAL: 0 chunk-invariance mismatch(es)`** — the first time this gate has been run
over a fuzzed corpus. It took **1220 s**, not the "roughly two hours" this entry first
predicted: that extrapolated from `SOFAB_CHUNK=1` on the slowest driver, and the larger chunk
sizes are far cheaper than the one-byte cut. `py-cython` and `py-pure` report the scrub config
*not applicable* — their pull Decoder copies bytes on arrival, so no borrow is observable —
counted as neither pass nor fail.

**Nightly 32096008437 (2026-08-18) triaged — the camps are quiet.** CI's own clustering
reported `baseline: 1/1 camp(s) accounted for`: the benign `I:… | I:java` payload axis that
is the single live row in `known-clusters.txt`. The artifact carried **no crashes**. CI's
corpus 10148 → 10270; merged into the local union corpus **17870 → 19157** (+1287, the local
accumulation being the larger of the two). Nothing was filed and the baseline is unchanged.

*One camp had to be chased down before it could be dismissed, and the procedure is what sent
it.* A local re-cluster at `TIMEOUT=5` — the value the `check-nightly` skill prescribed —
reported a NEW camp: `TIMEOUT:py-pure`, 2 inputs of 19157. It is the spurious class
`results/CLUSTERS.md` already describes, and this session added two more measurements of it:

- the accused input decodes in **1 ms** through *both* Python profiles, rejecting like
  everyone else, and all 15 drivers agree on it at a longer budget;
- a **second pass at the same `TIMEOUT=5` accused a disjoint set** — two different inputs,
  the first no longer among them — while the machine's 15-minute load average sat at ~19.

*The other two nets over the same corpus.* The materialized-value oracle is **green**:
10270 inputs x 15 drivers, **0 divergences** (0 crash, 0 timeout). The encode gate reports a
single counted failure for `go`, and it is not an encoder defect — it is the gate saying the
string/blob **pass-through** permission was granted and never exercised (`0 handovers over
10270 input(s)`), because nothing in this corpus carries a payload above the port's
threshold. A configuration that asserts nothing is counted as a failure by design; the
corpus, not `corelib-go`, is what does not reach it.

Always `py-pure`, which is simply the slowest driver in the roster. The same corpus at
`TIMEOUT=30` — the nightly's own budget — reports **`1/1 camp(s) accounted for`, no new
camp**: the timeout camps disappear completely rather than moving. So the skill now
prescribes `TIMEOUT=30` (the nightly's own value, for the reason CLUSTERS.md records) and
says to replay an accused input on its own before believing a `TIMEOUT` camp. A tight budget
measures the machine, not the drivers.

**The chunk-boundary findings are now guarded against chunk boundaries (2026-08-18).**
F-0058, F-0060 and F-0061 were promoted into `corpus/regression` on 2026-08-16, and every
gate replaying that corpus feeds each record **whole** — so what stood guard was their
one-shot verdict, not the behaviour they were filed for. The write-ups and the corpus README
said so in as many words rather than implying a guard they did not have, which is why this
was a known gap and not a discovered one. `replay.yml` now runs the chunked gate over that
corpus as a second step.

*Measured before wiring, not after:* **239 inputs x 6 chunkings x 14 drivers, 0 mismatches**,
about ten seconds once the drivers are built — and they already are by that point in the
workflow, so the step is nearly free.

*`--modes chunk` only, and the reason is arithmetic.* The split sweep is O(maxlen) **per
driver**; over 239 inputs it does not fit the budget, which is the separate scaling item in
`TODO.md`. Fixed-size chunking still crosses every internal boundary at six different
offsets, which is what these three findings need.

*The guard was proven able to fail.* Appending one byte to a driver's output **only when
`SOFAB_CHUNK` is set** turned the new step red with **522 mismatches**, naming
`F0058_r2_realloc_rebases_first.bin` among them. That is the difference between a corpus a
step points at and a corpus a step actually re-feeds — worth establishing, because a green
gate over vectors it silently skipped would read exactly like a green gate that guards them.

**corelib-py#96 merged, verified — and the first verification was wrong (2026-08-18).**
The `SofaStateError` split filed yesterday landed upstream the same evening, in the shape
the write-up proposed: a deprecated alias of `SofaRangeError` for the caller-mistake half,
and the four type-mismatched reads now returning `None` and skipping the field per §7.3.
Re-measured here rather than taken from the merge — the rule that a closed upstream issue
is a reason to re-measure, never a substitute for it, which this repo has now learned three
times (generator#293 → #295, generator#300, and this).

*The first measurement said the fix had not worked.* All four reads still raised. The cause
was not the fix: a compiled `_speedups` artifact from **before** it was still sitting in
`vendor/corelib-py/src/`, where a `git checkout` does not remove it, and `sys.path` order
made it win over the freshly checked-out sources. Removing it and rebuilding gave the
correct answer on both engines. **The stale-build rule reaches further than the drivers'
own outputs** — a corelib's build products live inside the vendored checkout and survive
exactly the operation one performs to get new code.

*Crucible's own dead row went with it.* `drivers/python/driver.py` mapped `SofaStateError`
to the `usage` class; with the alias in place `type(e).__name__` can never spell it again,
and mapping it would now be wrong in the other direction — an alias of `SofaRangeError` is
§6.3's `InvalidArgument`, i.e. `argument`. **No source of `usage` remains in the roster.**
The per-line check added yesterday therefore guards a class nothing can emit, which is the
point of keeping it: it makes the state unreachable rather than merely absent, including
for a driver added later.

*One stale citation found while editing:* `canonical.md` still said the receiver-limit
"heap note is pending upstream (generator#102)". CORELIB_PLAN §6.2.1 closed that hole, and
`policy.yaml` was corrected yesterday while this copy was not — the same
description-in-two-places drift CLAUDE.md warns about, caught only because the paragraph
happened to be under the cursor.

**A forbidden reject class cannot be caught by comparing drivers (2026-08-17).**
The "finer reject-class taxonomy" item had been open since 2026-07-17 asking for a
two-tier grade to be *invented*. Re-read against the spec, the taxonomy turned out to be
already decided — CORELIB_PLAN §6.3 fixes it at five codes and **abolishes one category
outright**: *"a type-mismatched read is not an error at all […] there is no result code
for 'invalid usage'."* So the work was to enforce a decision, not to design one.

The mechanism is the part worth recording. `reject_class` has been a **hard** axis since
2026-08-16 and fires zero times — but it compares drivers, so it only ever fires on
**disagreement**. A class the spec says cannot exist is invisible to it: if every
implementation named the same forbidden class, the run would be unanimous, and unanimity
is what green looks like everywhere else. **Agreement is the wrong instrument for a
question about a single line.** The class of each line is therefore judged on its own,
whatever the others said.

Three groups, owned by `oracle/canonical.md`: `invalid_msg` / `limit_exceeded` expected;
`argument` / `buffer_full` / `other` legal but **reported** (§6.3 permits
language-specific conditions, yet on the decode path each means a generated layer erred
where the family cleanly rejects — the F-0003 / F-0008 shape); `usage` **forbidden**.

*Measured before the check existed, not after:* across `corpus/interesting` (6000 inputs),
`crashes`, `regression`, `conformance`, `seeds`, `union` and `structured`, over all fifteen
drivers, **every reject is `invalid_msg`**. The check starts green and exists to keep it
so. Proven able to fail with fake drivers rather than argued: unanimous `usage` exits 1,
mixed `usage` exits 1, `other` warns at exit 0, `invalid_msg` is silent.

*One live source — measured, then filed.* `corelib-py` still defines
`SofaStateError` ("API misuse, e.g. reading a value of the wrong type for the current
field") and `drivers/python/driver.py` maps it to `usage` — a code for precisely the case
§6.3 says is not an error at all. It never fires: the generated §7.3 guards skip a
mis-typed field before any read reaches it, which is what the spec says should happen. So
the fuzzer cannot reach the path at all — this came from reading the clause, not from a
failing run, and the first move was to build the reproducer the repo's own rule demands: 4
wire bytes, identical on both engines. **corelib-py#96** followed, splitting the seven throw
sites into three encoder ones that rename to `SofaRangeError` (already §6.3's
`InvalidArgument`) and four decoder ones that must not raise at all; `_take_scalar` guards
both conditions in one place and has to be split. corelib-cpp/-java/-cs removed the code
years-equivalent ago and skip per §7.3, so py is the last port carrying it.

**The pass-through axis, and what a one-port feature is worth testing (2026-08-17).**
The §5.1 permission found in the spec re-check below is now gated. The decision worth
recording is what to do when a survey says **one port of eleven** implements a feature.

The survey came first, by reading each corelib rather than guessing: only `corelib-go`
has it (`WithPassThrough(bool)`); eight ports say "no pass-through" in their own README,
and `cs`/`java` do not mention it because a UTF-16 port has nothing to hand over — its wire
bytes do not exist until the encoder transcodes them. That is now `meta`'s `pass_through`
key, asserted by `driver-audit.sh`: an absent declaration fails, `no` does not. **An absent
key is nobody having looked; `no` is somebody having checked.**

*Built it anyway, for a reason that is not "completeness".* The permission is
**wire-neutral** — §5.1 says the output is byte-identical either way — so both existing
oracles are structurally blind to it by construction, not by omission. That is the same
class as the chunk-lifetime question, which is what produced F-0058 and F-0060. A path
nothing can observe is exactly where a defect survives, and the axis costs one extra run.

*The half that makes it real.* Asserting only "the bytes match" would be vacuous: a port
that accepted the permission and quietly copied anyway satisfies it trivially. So the
driver reports `passthrough handovers=<n>` at EOF and **zero fails the gate**. Both failure
modes were provoked rather than assumed — corrupting one passed-through byte turned it red
on exactly the two vectors that hand a run over, and running it over a corpus with no
payload above the threshold turned it red with "0 handovers".

*Two measurements worth keeping.* corelib-go passes a **blob** run through once it exceeds
the output buffer but a **string** only past 4096 bytes, so at `probe`'s scale only blobs
reach the path — legal, since §5.1 lets a port ignore the permission entirely. And the
corpus triggered it **once in 110 vectors** until `ba_maxlen_full` (five maxlen-64 blob
elements) was added; the wire-order rule — buffered bytes drained before the passed-through
run — is now exercised five times per input rather than once.

*What is deliberately not covered, and said out loud on the gate's own output.* The
fourteen ports declaring `no` are not exercised: they do not recognise the variable and
would exit 0 having ignored it, which is indistinguishable from honouring it when the bytes
are identical either way. Their rows read "pass-through declared absent (not exercised)"
rather than implying coverage. Making the refusal assertable is per-driver work, filed in
`TODO.md` — until then `pass_through=no` is believed, not verified.

**Every open spec question re-read at the tip; three were stale and one clause is new
(2026-08-17).** Both spec documents were read in full at documentation `main@dd2866b`
(`MESSAGE_SPEC.md` at `4a517b5`, `CORELIB_PLAN.md` at `e34c78d`) rather than trusted from
notes, and the spec repo has **zero** open issues — every question Crucible ever filed is
answered. Four results, in the order they matter:

- **A finding was nearly filed against conformant behaviour.** Measuring WP-08(c) (an
  explicit `[]` against a non-empty declared array `default`) produced what looked like a
  defect: an empty wrapper frame at `def_arr` decoded to the declared `[7, 9]` on all ten
  heap drivers instead of `[]`. It is **MESSAGE_SPEC §7.3** — the field is a *compact*
  numeric array, so a `SEQ_BEG` frame is a wire-type mismatch, which MUST be skipped, MUST
  NOT be `INVALID`, and MUST NOT be decoded into the declared field. The explicit-empty
  spelling for that field is **§3's compact `M = 0`**, which every driver does preserve.
  Two clauses, both normative, both missed on the first pass. The vectors are committed and
  the two mis-typed ones kept deliberately, since a §2-shaped reading expects `[]` there.
- **`policy.yaml` carried a spec hole that had been closed.** Its `limit_exceeded` note read
  "not yet in MESSAGE_SPEC — SPEC HOLE to file upstream". **CORELIB_PLAN §6.2.1**
  ("Receiver-side technical limits", normative) names the three `max_dyn_*` caps, makes
  exceeding one a policy rejection distinct from `INVALID`, forbids reporting it as
  `InvalidMessage`, gives it the error code `LimitExceeded` (§6.3), and states that
  conformance testing compares implementations configured *identically* — a description of
  what limit mode already does. Two further citations in the same file were stale in the
  same direction: the lazy-hold-back clause is in `main`, not on the POC branch, and the
  embedded-NUL note was adopted — deliberately as **non-normative** interop text, which is
  as far as F-0018's carve-out will ever be blessed.
- **The two "unspecified streaming contracts" had been answered twelve days earlier**
  (documentation#36/#37, closed 2026-08-05), and neither answer was a compromise. Chunk
  lifetime went **against borrowing** (§6: a fed chunk is borrowed only for the duration of
  `feed`), which corelib-zig had already complied with via generator#296. The minimum caller
  buffer became a **declared constant** rather than a fixed floor: §5.1 explicitly *retires*
  the one-byte rule and requires `MIN_OUTPUT_BUFFER` (1, or the largest reserved run, capped
  at 20). Crucible's encode gate had already tracked that rewrite on 2026-08-11; the TODO
  entry describing the questions had not.
- **One clause is genuinely new and untested.** §5.1 gained *"Pass-through of a divisible
  run"* on 2026-08-08 — an encoder MAY hand a `string`/`blob` payload straight to the sink.
  The term appears **nowhere** in this repo. It is wire-neutral, so both oracles are
  structurally blind to it; what is assertable is the borrow lifetime (the encode-side twin
  of `SOFAB_CHUNK_SCRUB`) and its mutual exclusion with taking the buffer. Filed in
  `TODO.md`, first step static: find out which backends implement the permission at all.
  Related: §6.3 now states there is **no** result code for "invalid usage", while
  `oracle/canonical.md` still admits `usage` and `other` reject classes — states the spec
  says cannot occur, and a family-wide one would be unanimous and therefore green.

**Two of the three soft axes were legacy, and the union pass had never been promoted — both
measured, then fixed (2026-08-16, last).**
The deliberate leniencies were reviewed the same way the carve-outs were: by measuring whether the
reason still holds, not by re-reading it.

*Three comparison axes were soft because "the per-language error taxonomies are not aligned yet" —
a Phase-1 statement nobody had re-checked.* Counted across `corpus/interesting` (17870 inputs),
regression, structured, conformance, seeds and limit mode:

| axis | occurrences | verdict |
|---|---|---|
| `reject_class` | **0** | soft protected nothing → **hard** |
| `limit_class` | **0**, including in limit mode itself | **hard** |
| `incomplete_value` | **5471** | stays soft — and now for a measured reason |

Every one of the 5471 is the same thing: java hands back what it had already read when the stream
ended mid-field, where the other fourteen hand back nothing. The verdict is unanimous (`I`
everywhere); only the payload differs. Hardening it would mean 5471 red lines for one catalogued
behaviour. The other two were the opposite: leniency for a disagreement that no longer happens, and
which would have hidden the first real one — the same bytes cannot be broken for two different
reasons, so a split there means one side is wrong.

*The union pass was report-only, and the project's own rule says it should not have been.* Ground
rule 4: an axis is report-only **until it is green or every divergence it surfaces is catalogued**.
It has been green for weeks — `wiretype` 77 vectors, `reserved_subtype` 28, `truncation` 13,
`repeated_id` 8, `empty_frame` 6, `overbound` 4, `tolerance` 7, all zero — while `sweep.sh`'s own
comment called promotion "a follow-up". Three sibling axes were promoted the day they went green;
this one was forgotten, and a test that cannot fail is not a test. The `|| echo "REPORT-ONLY"` is
gone.

**Every gate re-run on the tightened policy: seeds, regression, conformance, the 17870-input corpus,
limit mode, and the sweep family including the now-blocking union pass — all green**, 0 divergences.
Which is the expected result and also the point: the tightening costs nothing today and catches the
first case tomorrow.

**The cluster baseline survives a roster change now — rows match on the drivers they name
(2026-08-16, last).**
The stamp shipped earlier the same day made the report honest; this makes the file keep working. A
baseline row and the current partition are both projected onto the drivers they have **in common**,
so a signature written before a driver existed still matches, and adding a driver no longer forces a
re-record. The `# roster:` line stays as context and is no longer a gate.

*The loosening is bounded on purpose, and the boundary is where the value is.* Two things still turn
a camp NEW: a driver the row **does** name landing on the other side of the split — real movement,
which is exactly what the baseline exists to catch — and a driver the row does **not** name sitting
**alone** in a camp, agreeing with nobody.

**The first cut got that second case wrong, and the test caught it.** Projection alone let a
brand-new driver alone in a camp match a row that had never heard of it, and the run announced that
it "joined an existing camp" — about a driver agreeing with no one. That is precisely the masking
the open item had warned about, produced within an hour of writing the code that was supposed to
avoid it. An unknown driver now counts as accounted for only where it shares a camp with a driver
the row names.

*Verified on four cases:* unchanged baseline → accounted; a baseline predating three drivers that
joined existing camps → accounted, with a per-camp note naming them; a driver moved between camps →
NEW; a driver alone in a new camp → NEW.

**The cluster baseline now says "roster changed" instead of inventing nine findings (2026-08-16,
earlier).**
Every signature in `results/known-clusters.txt` names every driver, so adding one invalidates all of
them at once. On 2026-08-05 that produced **"9 NEW CAMPS, 0/9 accounted for"** — six were the old
rows with two new names inside them, three were a driver changing camp for a catalogued reason, and
zero were new root causes. Maximum alarm from the mechanism that exists *because* nine genuinely
unexplained camps once accumulated unread; a cry-wolf failure on the one check whose whole job is to
be believed.

**Decision: record the roster, and check it before comparing anything.** The baseline carries a
`# roster:` line naming the drivers its signatures were recorded against. When that disagrees with
the drivers running, the run reports the difference and stops rather than listing every camp as new.
A baseline with no stamp is refused for the same reason: without it there is no way to tell which of
the two situations you are in.

*This does not make the baseline survive a roster change — nothing here does, and the file still has
to be re-recorded.* What changed is that the run now states the truth about itself. The useful half —
comparing camps modulo drivers absent from the baseline, so a driver *joining* a camp does not
invalidate the row and only a driver *moving* does — is in [`TODO.md`](TODO.md) at roughly four
hours, because it needs care not to mask real movement.

*The test found a bug in the test's own subject, which is the point of writing tests before
believing code.* The first parser accepted a wrapped roster line and swallowed every ordinary
comment containing a comma, inventing driver names out of prose — the run then reported a roster
change against a roster made of sentence fragments. Continuation support is gone: one line, no
wrapping.

**`results/FINDINGS.md` is generated from the write-ups now, and the checker that policed it shrank
by a quarter (2026-08-16, last).**
The index was maintained by hand beside the write-ups and carried **no fact of its own**: the id is
the folder name, the title the write-up's heading, the state its `**Status:**` line. Two copies of
the same facts drift, and on 2026-08-03 they had drifted 46 times. The answer then was a checker —
241 lines of Python parsing a markdown table to police a copy. Asked plainly whether a tool that
validates a markdown file is a sensible thing to own, the honest answer is no: it is a symptom of
keeping structured data in prose.

**Decision: remove the copy instead of automating its supervision.** `scripts/gen-findings.py`
renders the index from `findings/*/NOTES.md`. Two fields moved into the write-ups to make that
possible — `**Issue:**` (the upstream ticket, previously only in the index) and `**Codegen:**` (a
`G-00NN` that is the generator side of this finding). The codegen entry is *stored*, not derived:
11 of the 21 paired rows carry a ticket different from their finding's and 6 phrase their title
independently, so a derivation rule would have been a rule plus six exceptions.

*The migration was verified as a round-trip, not by reading the result.* Same **99** ids, same
pairings, same states, same ticket cells before and after. Only the title text changed, by
intention: the index now shows each write-up's heading instead of a separately maintained summary
that had been truncated by hand at anywhere between 219 and 229 characters.

**What this deletes rather than automates.** The index can no longer disagree with a write-up about
a state, a pairing or a ticket, because it no longer holds those facts. The tally line — wrong by
eight entries this morning, and the one number a reader sees first — is counted, not typed, so the
open item asking for it to be checked is closed by construction. `check-catalog.py` is down from 241
to 176 lines and asserts only what generation cannot: that the committed index is current
(regenerate-and-compare, the shape `materialize.sh` already uses for the schema table), that every
write-up declares a state, and the `**Guard:**` rule. Both failure paths were exercised on purpose —
edit a heading and the index reads stale; delete a `Guard:` line and that finding fails.

**The allow list is enforced, and the divergence it describes is now exercised instead of avoided
(2026-08-16, last).**
`oracle/policy.yaml` has always had two halves: five axes saying which kinds of difference fail a
run, and a list of specific inputs allowed to differ for a documented reason. Only the first half
was read. The second was a note.

*What that cost, concretely.* The list's one active entry covers F-0018: a text may contain a zero
byte, and every language that stores a length gives it back whole, while C ends a text **at** the
zero byte and returns the first part. That is what a C string is. But because nothing read the
entry, the input had to be kept out of every gate corpus — feeding it would have turned a gate red
next to a file explaining that the difference is legal. So the one finding whose behaviour is
understood best was the only one nobody could guard.

**Decision: keep the list and enforce it, rather than delete it.** A difference on the named axis
for the named input now prints `[allowed] <input> (<axis>) <id>` and does not fail the run.
Everything else about that input is still compared, so an entry legalises one known difference, not
the input.

*Matching is by the input's bytes, never by the path in `applies_to`.* A path-bound allowance would
stop applying the moment the file is promoted into a corpus — which is exactly what one wants to do
with a divergence known to be legal, and the file gets renamed on the way. The same mistake was
made and caught twice today, in the `Guard:` check an hour earlier. A path that no longer resolves
is now reported on stderr: a stale allowance legalises nothing and hides that it was meant to.

F-0018's reproducer is in `corpus/regression` (239 inputs, gate green: 0 divergences, 12 allowed),
and its `Guard:` line changed from `none` to the corpus. The dormant second entry stays as it is,
matching nothing on purpose — it exists so the first person to hit that case recognises it as legal
instead of hunting a bug that is not there.

**Every closed finding now declares what re-checks it, and 13 that declared nothing got a guard
(2026-08-16, last).**
The audit found 19 resolved findings whose reproducers were never promoted out of `findings/<id>/`,
so nothing replayed them. Closed, but unguarded.

*Why that step is the one that fails.* It is the third of three, and the only one without a
mechanism: minimizing happens at the find, filing happens the same day, and **promotion happens
weeks later, usually while several findings go green at once in a family bump** — precisely when
per-finding follow-through drops. Worse, it produces no visible result: adding a converged vector to
a green gate leaves it green, so doing it and forgetting it look identical afterwards. The
promotion step has been written in `corpus/regression/README.md` from the start and was skipped
anyway, 13 times. *I did it myself this morning* — F-0043 closed with every claim verified, its 17
reproducers left where they were.

**The repo had already learned this exact lesson once.** On 2026-08-03, 46 write-ups were found
contradicting the index, and the entry recording it is titled "the point at which intent was
replaced by a check". That produced `check-catalog.py`. The same disease, on a different artifact,
went unchecked for two more weeks.

**Decision: the guard is declared, and the declaration is verified.** Every finding that is not open
and carries reproducers now needs a `**Guard:**` line naming a gate corpus, a sweep axis or an
oracle — or `none — <reason>`. `check-catalog.py` asserts it, in the same driver-free blocking job.
A named corpus must hold **either those bytes or a vector named for the finding**: both promotion
styles are legitimate and neither test alone covers both — F-0027's bytes were promoted under a
descriptive name (content matches, name does not), while F-0003's guard is a cleaner isolate built
for the gate (name matches, content does not). What must never pass is neither.

*What the check found the moment it existed:* five findings that only looked unguarded (F-0027,
F-0030, F-0049, F-0057, F-0059 — already replayed, under names that say what they test), and 13
genuinely unguarded. **50 vectors promoted, `corpus/regression` 188 → 238 inputs, gate green** — 0
divergences across all fifteen drivers, which the 243-reproducer pass earlier the same day had
already predicted.

*Two honest limits, written into the artifacts rather than left implied.* F-0018 stays unguarded on
purpose: its divergence is by design, so promoting it would turn a gate red while `policy.yaml`'s
`allow:` block is unenforced — its `Guard:` line says exactly that. And F-0058/F-0060/F-0061 are
chunk-boundary findings whose vectors now sit in a corpus the **chunked** gate does not replay: the
promotion holds their one-shot verdict and no more. Both the write-ups and the corpus README label
that half a guard, and the follow-up is in `TODO.md`.

**Participation is now derived, the announcement is now checked, and every roster entry gets a
ledger (2026-08-16, last).**
Three changes aimed at one failure mode: the one that let `go` sit outside the encode gate for
eleven days without anything turning red.

*The gate rosters are derived, not typed.* `scripts/roster.sh` gained `caps {encode|chunked}`,
which reports the roster entries whose `drivers/<builder>/meta` declares the capability;
`run-encode.sh` and `run-chunked.sh` call it instead of carrying a hand-written list. **The derived
lists matched the hand-written ones exactly** — encode 15, chunked 14 with `go` absent by its own
`chunked_decode=none` — so this changed the mechanism without changing who runs. The point is what
it makes impossible: a driver can no longer be *forgotten* out of a gate, only *declared* out, in
the file that owns the declaration. Note the mapping is deliberately not one-to-one — the four
`cpp` rows share one `meta`, because the surfaces belong to the backend, not the build variant.

*The stderr announcement is asserted.* It was required by `CONTRACT.md` from the day the axes were
written, captured by both gates, and then thrown away — a mechanism that existed to prove a driver
honoured a variable, proving nothing. Both gates now fail when the line is missing. **It found a
real one on its first run:** the C driver announced nothing for `SOFAB_ENCODE=to`, because its
condition was "announce when not on my default" and `to` *is* its default (C has no allocating
encode). Indistinguishable from a driver ignoring the variable — exactly the hole the announcement
exists to close. Fixed by announcing whenever the variable is present, and `CONTRACT.md` now states
that rule: announce for any named surface, including one that is your own default. `new` stays
exempt, being the one case where honouring and ignoring are the same run.

*Every roster entry gets a ledger.* `scripts/driver-audit.sh` prints, per driver, what its `meta`
declares and which gates that places it in, and fails when a declaration is missing or malformed —
an absent `chunked_decode` is the dangerous state, while `none` is somebody having written down
that the backend cannot do it. It also fails a quarantine that names no finding. Static only, so it
runs in the `catalog` job in seconds, before anything is built. Verified by breaking a `meta` on
purpose and watching it exit 1: a check nobody has seen fail is not a check.

**`go` joins the encode gate — the whole roster is now on that axis, and no corelib change was
needed (2026-08-16, later still).**
`drivers/go/driver.go` called `m.Encode()` unconditionally and never read `SOFAB_ENCODE`, so the Go
driver sat outside `run-encode.sh` — the last roster entry missing from either streaming gate. The
expectation going in was a capability gap like the chunked one; it was not. corelib-go has all three
surfaces (`Encode`, `EncodeTo(w)`, and `Serialize` into a `NewEncoderSink`), exports
`MinOutputBuffer` (`2 × maxVarintLen` = 20), and `drivers/go/meta` already restated that as
`min_output_buffer=20`. **Everything was in place except the forty lines that read the variable** —
the backend had been prepared for this axis and then never wired to it.

Plumbed per `CONTRACT.md`: surface dispatch (`new` → allocating `Encode`, `to` → `EncodeTo(w)` where
the caller owns the destination, `stream` → `Serialize` into an encoder built with the `SOFAB_FLUSH`
window), the §5.1 floor **refused with exit 3** below the declaration, and the stderr announcement
without which honouring the variable is indistinguishable from ignoring it. Green on the first run:
**108 inputs × 5 configs, 0 mismatches**, and the gate now covers all fifteen drivers. Seeds and the
regression corpus re-run clean afterwards (188 inputs × 15 drivers, 0 divergences).

*One thing the run made visible, filed rather than fixed:* `flush_sizes()` offers the declaration
plus every standard size **above** it, so a port declaring 20 gets a sweep of exactly `{20}` while
every port declaring 1 gets six sizes. The thinnest coverage on the axis lands on the port with the
highest floor, which is backwards.

**Full-repo cleanup pass: every closed finding re-verified, three dead exceptions removed, five real
gaps filed (2026-08-16, later).**
A sweep of *everything that can hide work*: the catalog's upstream tickets, every special case in the
test code (active or not), the counts restated across the docs, and all eleven gates.

*The catalog is sound.* All **106** upstream tickets cited by `results/FINDINGS.md` are closed, and
every cited **PR is actually merged** (checked one by one via the API, not by reading states off the
rows); no issue was closed as `not_planned`. Then the stronger check: all **243 reproducers from
every finding folder**, fed through all fifteen drivers — **212 agree, 31 diverge, 2 camps**. One is
the benign baselined java `incomplete_value` row (verdict unanimous). The other is a single input:
**F-0018**, the C NUL-terminated-string projection, which is the one divergence in the whole catalog
that is by design. So no resolved finding regressed, and the 17 `G-*` folders without a `.bin` are
codegen defects whose reproducer is generated source, not a wire input — not a gap.

*Three questions that had been open for ten days answered by measuring them.* The two unattributed
cluster camps from nightly 31074707585 and F-0061's set-aside `r1` are all **0 divergences across
fifteen drivers** today; the camps were the verdict-timing shape F-0043 owned, and F-0043 closed
this morning. All three items are checked off in [`TODO.md`](TODO.md) with the measurement, not with
an argument.

*The dead exceptions.* `oracle/policy.yaml`'s entire `allow:` block **is not read by anything** —
`comparator.py:load_policy` parses the `comparison:` axes and stops. So the two documented tolerated
divergences grant nothing, and the input an entry names must be kept out of every gate corpus or the
gate goes red *despite* the entry — which is exactly why F-0018's reproducer is the one resolved
finding deliberately absent from `corpus/regression`. The block is now marked NOT ENFORCED at the
top, with the decision (teach the comparator to match by content hash, or delete it) in `TODO.md`.
Two stale `[ ]` items whose bodies asserted things that were no longer true (the `cpp-c-cpp-dyn`
quarantine, `py-pure`'s absence from the encode gate) are closed.

*The counts had drifted everywhere.* "all 13" / "13 drivers" appeared in **36 places** across the
as-built docs and the sweep sources while the roster carried fifteen — README said 14 in one place,
`CI.md` said 12. Rewritten to roster-neutral wording ("all drivers", "every driver") rather than to
`15`, because the number belongs to `drivers/roster` and any restatement of it drifts again on the
next roster change. The one place a literal count is right — the sample `run.sh` output in the
README — now shows the real fifteen, `cpp-c-cpp-dyn` included.

*Newly filed, because they are real gaps rather than untidiness:* the unenforced `allow:` block;
**19 resolved findings with no standing regression guard** (their reproducers are fuzzer seeds, but
no gate replays them); `engine/structured/audit_canonical.py` wired to nothing (run by hand here —
`corpus/structured` and `corpus/structured-union` are clean, the other corpora light it up by
design, which is why it can only gate the canonical ones); the two streaming gates keeping hand-written
driver lists beside the roster; and `go` being the last driver outside the encode gate while its
`meta` advertises three encode surfaces its driver never reads.

*All eleven gates green on this state* — seeds, regression, conformance via the sweep family, twelve
blocking sweep axes (`wiretype_sweep` 363 vectors, `truncation` 179, `repeated_id` 159, …), the
report-only union pass, cross-encode, limit mode, materialize, encode invariance. `CLUSTERS.md` got
the 72h corpus snapshot it was missing (it still led with 2026-08-03: 8512 inputs, 17 camps).

**F-0043 closed — the catalog has no open finding left (2026-08-16).**
[generator#267](https://github.com/sofa-buffers/generator/issues/267) closed upstream on 2026-08-11
with the fixlen-header hook F-0043's attribution addendum asked for: the five push/visitor corelibs
now expose the length at the *word*, and the backends consume it, so a schema-bound violation is
`INVALID` at the word instead of only once payload bytes arrive. **Verified here by deleting the
carve-out, not by reading the upstream diff** — `engine/structured/sweep_malform_truncate.py` grows
**43 → 96 vectors** (the exact growth that surfaced the finding on 2026-08-01) and comes back
`0 divergence(s), 0 conformance failure(s)` across all 15 drivers, one soft hit on
`incomplete_value`/`reject_class`. The scope caveat in the addendum — the wrapper-element rows whose
camp differed, go and dart on the wrong side — is *discharged*: those are vectors of this same axis
and they are green, so they never needed the separate analysis the note reserved for them.

*The three F-0043 rows are deleted from `results/known-clusters.txt`, not relabelled*, per that
file's own rule: a repaired camp must read as NEW if it returns, and this family has been caught
regressing before (F-0054, twice). Independent corroboration that they are gone: none of the three
appeared in any of four full clustering passes over the 17870-input corpus from the 08-11 72h run.

**Tally: 99 entries — 97 resolved, 0 open, 2 by-design/withdrawn**, and `check-catalog.py` agrees
with every write-up. The index's summary line had drifted (it read "91 entries — 87 resolved" while
99 rows existed) — the checker asserts each row's state token against its NOTES but never the
totals, so the one number nobody verifies is the one people read first. Refreshed here; making it
checked is worth a follow-up.

**Two sweep carve-outs outlived the findings that justified them; both lifted, both axes green
(2026-08-16).**
An inventory of every exception in the suite — `policy.yaml`'s soft axes and `allow` entries,
`known-clusters.txt`, the roster's quarantine tag, the per-cell carve-outs in the sweeps, and the
non-blocking CI steps — turned up three entries that no longer had a basis.

*Two were live carve-outs suppressing vectors on BLOCKING axes.* `sweep_overbound.py` still held
back the element-width vectors for F-0052 (generator#279), and `sweep_repeated_id.py` still skipped
the `struct_array` element position `(202,)` for F-0035 (G-0020) — both findings closed (generator
PR #281, sofabgen 0.21.0), and in the F-0035 case the sibling axis `sweep_empty_frame.py` had
already rejoined the same position while this one did not. **Decision: both removed.** Verified by
running each axis against the pre-change state as a control, because a green run proves nothing on
its own — it is equally consistent with a flag that no longer gates anything. The counts show the
vectors were really suppressed: `sweep_overbound` **49 → 67** vectors, `sweep_repeated_id`
**158 → 159** (`merge=3 → merge=4`), and both report 0 divergences and 0 conformance failures
across all 15 drivers.

*The third was documentation drift.* `ARCHITECTURE.md` claimed in two places that `cpp-c-cpp-dyn`
was quarantined for F-0057; the quarantine was lifted when corelib-c-cpp#132 closed it and
`drivers/roster` has carried `blocking` on all fifteen rows since. Corrected — an as-built document
that describes a gate roster it no longer has is worse than none.

*The pattern worth keeping:* a carve-out names the condition for its own removal, but nothing
re-reads that condition when the upstream issue closes. Both of these were removable for days. The
cheap check is to walk the carve-outs whenever a finding flips to ✅, not to wait for someone to
audit the suite.

**A 72h fuzz run doubled the corpus and found nothing — but the clustering step's own timeout
manufactured two phantom camps per run (2026-08-16).**
The C pacemaker ran 2026-08-11 20:27 → 08-14 20:27 UTC (`FUZZ_TIME=259200 FUZZ_JOBS=3`, 3 parallel
workers, ~10–14k exec/s) against `main`: corelib-c-cpp at `e93e4cd`, sofabgen `0.0.0-20260811165755`.
`corpus/interesting` grew **9502 → 17870** inputs (+88 %). **No new crash artifacts** (the 6 in
`corpus/crashes` are the pre-existing ones) and **no new divergence camp** — the round-trip oracle
reports the single baselined java camp, and the materialized oracle over the same 17870 inputs is
`0 divergence(s)` across all 15 drivers with `0/108` conformance mismatches against the C anchor. Its
5463 warnings are all `incomplete_value`, which `oracle/policy.yaml:29` declares soft (partial-value
materialization on a truncated stream is not aligned across languages in Phase 2).

*The interesting part is the alarm that was not real.* The closing clustering pass came back **red**
with two unexplained `TIMEOUT` camps (`py-pure` ×2 inputs, `cpp` ×1). They did not survive triage:
replaying those exact inputs in isolation produced no timeout at all — not at the 5s budget, and not
at 1s — and a second full-corpus pass produced two *different* phantom camps on two *different*
inputs. Three passes, three disjoint sets of accused inputs, and at `TIMEOUT=30` the effect vanishes
completely (`rc=0`, 1/1 camps). Swap was never involved (0 B configured). So these are sporadic
multi-second scheduling stalls on a 6-core box, not hangs, and **the accused driver is an artifact of
which input the stall lands on** — attribution to any corelib or to the generator would have been
wrong in all three cases.

**Decision: `nightly.yml`'s clustering step moves from `TIMEOUT=5` to `TIMEOUT=30`.** 30 is the floor
`scripts/run.sh` already documents for its own default (`max(30, 0.25 × corpus size)`); the explicit
`5` undercut it sixfold and made a non-blocking step report one to three false camps per run. A step
that is routinely red for no reason stops meaning "something new broke" — the same reasoning that
justifies `results/known-clusters.txt` and the quarantine tag. A genuine hang still fails it.

*A second defect fell out of the same triage, and it is the more dangerous one.* `oracle/minimize.py`
is contracted to shrink an input "while its camp partition holds", but a `TIMEOUT` camp is not a
property of the bytes: the stall stops reproducing after the first deletion and the minimizer then
drifts onto whatever camp the residue still lands in. Both phantom reproducers (2534 B, 8461 B)
minimized to the *same* 1-byte input `06` — the representative of the long-known java camp. A
minimizer that silently returns an artifact for a *different* bug than the one it was given is worse
than one that fails; filed in [`TODO.md`](TODO.md) under engine & oracles.

**Full box against the 08-11 family: eleven gates green, two drivers repaired for upstream API breaks, the encode gate re-based on the rewritten §5.1, F-0061 down to one input (2026-08-11).**
Run against sofabgen `0.0.0-20260811122938-1a44ef44d5fe` (a main CI build, no release) with every
corelib at its main tip and the spec at `dd2866b`. **All eleven gates green**, warm-up pass green
too — so the second reading is not masking a stale-build artifact after the vendor reset.

*Most of the upstream movement was benchmarks, not wire code.* Eight of the eleven corelibs
advanced by a single BENCH_SPEC commit. Only three touched behaviour: corelib-rs made the
`OStream` installation precondition a status rather than a panic (#86), corelib-zig raised a
varint comptime branch quota (#64), corelib-c-cpp added a lazy-seq CMake option (#137). sofabgen
carried two fixes — array element declared-width latching for go/dart/python (#321, the #267
follow-through) and the matching Rust fallible-`OStream` install (#328).

*Two drivers did not build, and that is Crucible's own maintenance, not a finding.*
`drivers/rust/driver.rs` called `OStream::with_flush` as infallible and `drivers/dart/driver.dart`
passed the removed `bufferSize:` instead of a caller-supplied `buffer:`. Both now report a refused
buffer as exit 3 per CONTRACT.md rather than panicking. Worth recording as a pattern: the whole box
was red for a reason that was not a divergence at all, and the seed gate cannot distinguish "the
family disagrees" from "our driver no longer compiles" — the build log can.

**Decision: the encode gate now reads each port's declared `MIN_OUTPUT_BUFFER` instead of assuming
one byte.** documentation#45/#46/#48 rewrote CORELIB_PLAN §5.1 between 08-06 and 08-11: the
universal one-byte floor is gone, replaced by a per-port constant a corelib MUST expose — `1` if it
splits atomic units across a flush, otherwise the largest run it reserves as one piece, and never
above `20`. A port MAY now require atomic units to land contiguously, which is precisely what the
old rule forbade.

That left `oracle/encode_invariance.py` and `drivers/common/CONTRACT.md` enforcing a clause that no
longer existed — both written five days earlier, in the 08-06 entry below, and both quoting "down
to a single byte". The gate was still green only because every port in the encode roster declares
`1`; `corelib-go` declares `2 × maxVarintLen` = **20**, legally and documented against the new
text, and is not in that roster. So this was latent rather than red — and would have surfaced as a
false conformance failure the day go was added.

The rework gates **both** halves of the new clause, rather than simply relaxing the old one: sizes
at or above the declaration must work (the sweep is `{declaration} ∪ {1,2,3,5,8,16 above it}`, so
it always contains the declaration and can never be empty), and a size one byte below it must be
refused. That second half is what stops the declaration from being an escape hatch — a port cannot
declare 20 to dodge the hard sizes and still accept 1. `min_output_buffer` joins `meta` as the
third declarative key, and is required: defaulting it to 1 would reinstate the assumption being
removed. Coverage is unchanged for all fourteen encode drivers — 108 inputs × 9 configs, zero
inapplicable, zero mismatches.

*Note this is the fourth position §5.1 has occupied in a week*, after the three F-0054 went
through. The rule that keeps paying off is the one in `verify-clauses-at-tip-before-filing`:
re-read the clause at the documentation tip before acting on it, never from a write-up.

**Third pass: F-0061 resolved and generator#300 closed for real (2026-08-11, evening).**
`corelib-ts@57515ad` (#141, *"a fixlen subtype needs a complete word, not its first byte"*) with
sofabgen `0.0.0-20260811165755-e1655b562522`. The fix lands exactly on the `peekFixSub` half of
the attribution posted on the reopen, and the generated `count`-bound ordering was not touched —
with `peekFixSub` returning `-1` on an incomplete word the generated cursor takes its `c.skip`
branch and reaches `INCOMPLETE` correctly. Eleven gates green plus warm-up.

`corpus/interesting` goes **5 mismatches over 1 input → 0**, all three reproducers pass, and the
control holds: `r3` plus one byte completing the `fixlen_word` is still unanimously
`R invalid_msg`. That control is the reason this close is trustworthy where three previous ones
were not — a fix that had merely dropped the §7.1 bound would also have shown `r3` green, and
nothing in the axis alone distinguishes the two.

`typescript` returns to `scripts/run-chunked.sh`, verified before re-adding rather than on the
ticket; the gate is green with all fourteen. Its neighbouring comment still claimed `zig` was
held out for F-0058, which closed some time ago — corrected in the same change. **Nobody is held
out of the chunked gate any more**, the first time that has been true.

*The pattern this finding was really about is worth keeping.* Four closes, three of them
premature, each with a repaired reproducer and a red axis behind it. What broke the run was not
more scrutiny of the fixes but a cheap standing habit: re-measure on the corpus, and carry a
control that would fail if the fix were a relaxation rather than a repair.

**Second pass the same day, against sofabgen `0.0.0-20260811163628-a5ae20c7756a`** (CI run
31513295408; corelibs unchanged, `corelib-ts` still `699f01e`). Eleven gates green again. The
build carries generator#329, a breaking "the caller owns the encode buffer" change for
go/python/typescript/dart — it did not break the drivers, since they reach encode through the
generated API rather than constructing the buffer themselves.

*generator#300 was closed at 16:37 UTC and reopened here with the corpus measurement.* The
closing note asked for exactly that check ("a Crucible re-run is the authoritative confirmation
… reopen without hesitation if the corpus disagrees"), and it does: 5 mismatches over
`corpus/interesting`, all `r3`, against the build made one minute before the close. The
divergence from their result is explained rather than contested — they measured a different
direction-B vector (`c6 0c 2a c2`) and ran corelib-ts directly with an empty visitor, not
generated code.

**Decision: F-0061's direction-B mechanism is the reverse of what this log and the write-up
said this morning.** documentation#43 → #44 make `INCOMPLETE` correct, so TypeScript's *chunked*
path is right and its *whole-message* path invents an `INVALID` — the chunk-invariance flip is
the symptom, not the defect. Pinned with a control: `r3` splits 14-vs-1, and `r3` plus one byte
completing the `fixlen_word` is unanimous `R invalid_msg` across all fifteen, so the bound check
is correct everywhere and only its timing is wrong. Attribution is **both** — corelib-ts
`cursor.ts:490` `peekFixSub` reads a subtype out of an incomplete varint (wire mechanics, and the
likely root fix), while the generated `count` bound fires before the length word completes
(schema-only, so this repo's half). CORELIB_PLAN §4.1 names the case outright.

*Method note, twice earned today.* Two measurements had to be thrown away before this one held.
The vendored corelibs are **depth-1 clones**, so `git log OLD..HEAD` in `vendor/` reports one
commit per repo regardless of the real delta — the "mostly benchmark work" characterisation
earlier in this entry came from that and is not evidence; use the GitHub compare API instead. And
a control run against a driver binary snapshotted while `run-limits`/`sweep` were rebuilding
reported `I` where the same input had just given `R invalid_msg`. Neither was a behaviour change.
Both are the standing footgun: **rebuild through `run.sh` and re-measure before believing a
number**, which is the same rule that caught F-0054's two regressions.

*F-0061 / generator#300 stays open, on one input.* Re-measured over `corpus/interesting` (9502,
unchanged since 08-06, so the counts compare directly): **179 mismatches over 30 inputs → 5 over
1**. Direction A is at 0; direction B is at 5 and is exactly `r3`, confirmed by content against
`corpus/interesting/647f8d0d…` rather than by name. Direction A's disappearance is *not* news from
this build — the generator's TypeScript backend was last touched by `dec1e42` itself, the commit
the 08-06 table was measured against, and generator#300's own 08-07 comment already reported A
closed. The NOTES table was simply stale; it is corrected now, and the G-0038 row no longer names
the refuted `_str` hypothesis. The issue cannot be closed: direction B is bit-for-bit where it was.

**Full box against the fixed family: eleven gates green, F-0054 closed again, F-0043 down to its two addenda (2026-08-06, later).**
Run against sofabgen `0.0.0-20260806101130-dec1e42049cd` (a main CI build, no release) with every
corelib at its main tip and the spec at `bec1fa8`. Sixteen steps — the eleven replay gates, the
three open findings re-measured, and the cluster pass. **All eleven gates green**, including
`regression` and `sweep`, which had been red on F-0054 in two consecutive runs.

*F-0054 is resolved again* — corelib-java#67 (`9befe46`) reverts the Option A merge that
corelib-java#68 asked for, matching corelib-zig's revert the night before. Five `F0054_*` vectors
unanimous, tolerance axis green at all seven positions. Its two regression sections are kept in the
write-up deliberately: the cause was the same both times — 2026-08-03 Option-A branches that
outlived the rule — so the third occurrence, if it comes, should be recognised rather than
re-derived.

*F-0043 lost its whole body.* The fixlen header hook landed in all five push/visitor corelibs and
the backends now consume it, so **all five catalogued vectors are unanimous** and the finding's
corpus went 30 → 6 divergences. What remains is exactly the two addenda posted to generator#267 on
08-05, and they have **disjoint camps**: the declared-integer-width bound (dart, go, py×2,
typescript late) and the one-byte-finer offset (typescript alone correct). Neither is touched by
the hook — the width bound is not a fixlen length, and the finer offset is about reading a subtype
out of the first byte of an unfinished varint. The F-0042 shape held exactly as the 08-02
attribution addendum predicted.

*F-0061 is still red, and its two halves are now visibly different problems.* 305 → **179**
mismatches over 30 inputs; direction A fell 300 → 174 while **direction B did not move at all** —
still exactly `r3`'s five. Successive generator builds are eating one half and not the other.
Also worth recording: **`r3` lost the unanimous whole-message baseline it was promoted for.** The
family moved around it (it is now the whole-message camp of F-0043's finer-offset row, where
typescript is the correct one), so the "no spec latitude" argument posted to generator#300 on
08-05 is stale. The reproducer still demonstrates the intra-driver break; it no longer carries the
argument alone. Correction owed upstream.

*Baseline pruned rather than grown.* The cluster pass over 9502 inputs found **4 camps, all
accounted**, down from 9. Nine rows were **deleted** from `results/known-clusters.txt` — seven
F-0043 rows whose cause is repaired, the §6.4 mid-payload row (documentation#40 turned that `MAY`
into a `MUST NOT`, so its return would be a conformance bug rather than latitude), and the two
unattributed camps from nightly 31074707585, which no longer occur. **Decision: a fixed camp is
deleted, not kept**, and the file now says so at the top — a retained row would match a returning
regression and report it as "known", which is precisely how F-0054's return was caught twice
(its row had been removed when it closed). The baseline shrinks when the family improves.

**F-0054 regressed a second time, in a second repo — and the encode carve-out was retired (2026-08-06).**
Eight corelib issues closed overnight, so the box was re-run against the new tips (cs, java, rs,
rs-no-std, ts, zig all moved). `regression` and `sweep` are red again on the **same rule as
yesterday, one repo over**: corelib-java merged #66 (`1eb6f12`, "stop applying ID_MAX to a
sequence-end header") at 06:05, and java is now the lone accepter across the two regression
vectors and all seven tolerance positions. corelib-zig's revert landed correctly the night before,
so this is not a spread — it is the same stale branch resurfacing.

*What makes this one different from zig's, and worth recording as a mechanism.* zig's arrived
inside a PR whose body said "README only, no code". java's argues explicitly from the spec and
quotes §4.9 and §6.2 — but the quoted wording is `f52e51e` (documentation#34, Option A), removed
the same day it landed by `872d479`/`acd27a4`. The commit is authored 2026-08-03 15:37, before
Option B merged, and the PR says so itself: *"restores a commit that never got a PR and whose
branch was pruned from origin."* So the failure mode is not carelessness in either case — it is
that **the Option-A branches from 2026-08-03 are still reachable and still read as current**,
because the argument they carry is internally consistent against the spec revision they were
written for. Filed as corelib-java#68, which asks for the branch deletion alongside the revert;
a sweep of all eleven corelibs found no other such branch and no open PR touching it.

*The encode-oracle tightening landed*, the blocker having cleared: corelib-ts#94 closed, and the
flush sweep came back with **zero** inapplicable sizes across all 14 encode drivers, so making a
refused size a failure reddens nothing. `oracle/encode_invariance.py` no longer carries the exit-3
escape hatch for `SOFAB_FLUSH` (it keeps it for a missing *surface*, which is a genuine
backend difference), the two counters and their guard are deleted, and
`drivers/common/CONTRACT.md` states the §5.1 one-byte floor. **Decision: the hatch went rather
than being narrowed to `n=1`** — a per-size exception would have re-created the thing that hid
corelib-ts#94, namely a green line that had skipped most of its sweep.

*F-0043 is unmoved* — the fixlen header hook is now in all five push corelibs, but the camps are
byte-identical to 2026-08-05 and the count is still 30/17. The corelib blocker is gone; the
backends do not consume the hook yet, so generator#267 stays open on the codegen side alone.

**Full-box re-run on fresh tips: a resolved finding came back, and a closed one was not closed (2026-08-05).**
All eleven gates run against freshly bootstrapped corelibs (three tips moved: go `08f196e`, ts
`792af26`, zig `26bab0c`; spec pulled separately to `bec1fa8`, since `bootstrap.sh` does not fetch
it) and sofabgen CI build `0.0.0-20260805161231-f5457b755f53`. Nine green; **`regression` and
`sweep` both red on one cause**, and the two open findings re-measured.

*The regression gate did exactly the job it was built for.* `F0054_r1`/`_r2` diverged, and the
sweep's tolerance axis lit up all seven `*_end_id_over_ID_MAX` positions — `zig` alone accepting.
corelib-zig had merged the **abandoned Option A** of F-0054, two days after the family settled on
Option B and after the issue asking for A was closed `not planned`. Evidence in the finding.

**Decision: F-0054 is reopened, not renumbered.** The precedent for a fix-induced regression in this
log is F-0011, which took a new number — but that was a *different* defect introduced alongside a
fix. This is the same rule, the same isolate, the same controls and literally the same `F0054_*`
vectors, with one implementation moving between the camps the finding already documents. Splitting
it would put one rule in two write-ups, which is the shape `CLAUDE.md` forbids and the reason the
catalog was restructured on 2026-08-03. The write-up carries a dated regression section; the
resolution trail for go/py/ts is left standing, because it is still true.

*Worth naming separately from the finding:* the change arrived inside a PR whose body reads
"Changes (README only, no code)" while its first commit rewrites 61 lines of `src/istream.zig` and
adds a test pinning the wrong behaviour. No review of that repo's diff would have been prompted to
look. That is an upstream process observation, not a Crucible one — but it is why the gate, not a
human, caught it.

*F-0061 re-measured, and the measurement axis was swapped mid-run.* The first attempt used
`run-chunked.sh`'s default `split` mode, which sweeps every byte offset — after 63 minutes it had
covered 3511 of 9038 inputs and was projecting ~100 more, on an axis the finding's numbers do not
come from. Killed and re-run with `--modes chunk` (the six fixed chunk sizes the write-up used),
which finished in minutes and is directly comparable: **609 → 305 mismatches**. Both filed
reproducers now pass and direction B collapsed 182 → 5, so the fix is real; the class is not gone.
A new 11-byte isolate (`r3`) was promoted from the fuzz corpus — unanimous `R invalid_msg` whole,
`I` under every chunking, and it accounts for all five remaining direction-B cases, so the half
that previously had only an entangled reproducer now has a clean one. F-0061 stays 🔴.

*F-0043's verdict count is unchanged* — 30 divergences over its 17 vectors — but its **camps
converged**: py-cython/py-pure were fixed on the blob rows, go/dart on the wrapper rows, and all
four fixlen/wrapper rows now show the same five push/visitor implementations. That discharges the
scope note left open on 2026-08-02, which had asked whether the element-id half needed its own
analysis: it does not. Both held-back addenda (the declared-integer-width bound, and the
one-byte-finer truncation offset where only typescript is correct) were posted to generator#267,
the review having settled.

**Upstream filed the same day:** corelib-zig#38 (the F-0054 regression), generator#300 **reopened**
rather than succeeded by a new issue — the reported path is repaired but the defect the issue names
still stands — and the two addenda onto generator#267.

*One measurement lesson, worth more than the numbers.* Comparing zig's blob-row behaviour across
tips meant `git checkout` inside `vendor/corelib-zig`, and the run immediately after reported
java, rust-std and rust-nostd — whose corelibs had not moved — in the *correct* camp where the
clean run has them late. Chasing that as a possible corpus-composition dependency (a driver
contract violation, and the kind of thing that would invalidate every camp table in the catalog)
cost most of an hour before three identical runs settled and reproduced the baseline exactly. The
cause is prosaic: a vendor checkout perturbs the mtimes the per-driver incremental builds key on,
so the **first** run after one is not trustworthy. Run any vendor-checkout comparison twice and
read the second. Recorded here because the false alarm was indistinguishable from a real and much
worse finding right up to the moment it wasn't.

**All fourteen drivers are wired, and the encode axis found a defect nobody was looking for (2026-08-04).**
Python was the last, and the only **pull-shaped** backend: there is no push `feed`, so the driver
expresses chunking by handing the `Decoder` a reader that returns **short reads**. That is faithful
rather than a workaround — the Decoder's `_need` loop treats a short read as "more to come" and only
an empty return as end-of-input, which is exactly the distinction the axis is about.

*And the encode side turned up **F-0059** (corelib-py#61), which is a different kind of find from the
rest.* It is not a divergence between languages: it is a split **inside one corelib**, between its
two engines. `Encoder._put` caches the buffer view before the loop that may drain; `_drain()` calls
the sink, the sink calls `buffer_set()` and replaces `self._fixed`, and `_put` keeps writing through
the stale `mv` — the old, already-drained buffer. Everything past the first flush lands in an
orphaned buffer and the fresh one is emitted zeroed. The Cython accelerator implements `_put`
separately and is correct.

*The reproducer is nine lines of corelib-py with no codegen, no generated message and no harness*,
which is worth noting because the finding arrived through a 108-input differential and left as a
unit test. `u8 = 1` encodes to `0001` in memory and `0000` over a 1-byte caller buffer.

*What makes this the axis's own catch:* every other gate in this repo re-encodes with one call into
an unbounded buffer, so no flush ever happens mid-message. corelib-py's own parity tests appear to
exercise `over_buffer` only where the message fits. `py-pure` is held out of the encode gate while
it is open, `py-cython` stays in — the split between them is the finding.

**The two unspecified contracts now have counted camps, not estimated ones.** With all fourteen
wired: **zig alone borrows** a whole-chunk payload (ten copy; python cannot alias at all, so
`SOFAB_CHUNK_SCRUB` is inapplicable there for the opposite reason — and the driver says which).
**corelib-ts alone** cannot encode through a buffer below its largest contiguous write; every other
backend streams the same 108 values through **one byte**. Both are ready to go to `documentation`.

**The chunked axis found its first defect, in the backend crucible#132 predicted (2026-08-04).**
Twelve of the fourteen drivers are wired for both streaming axes. Eleven are chunk-invariant over
every cut the oracle applies; **zig is not**, and the mechanism is worth recording because it is
the exact shape a differential oracle cannot see.

`_reassemble` in the **generated** `message.zig` keeps one `ArrayListUnmanaged(u8)` on the visitor
and returns `self.acc.items` — a slice into it — which `setElem` stores as the array element.
Deliberately, because the neighbouring *borrow* branch depends on storing a slice as-is. So the
next split payload calls `clearRetainingCapacity()`, appends over the same memory, and every
element stored earlier is looking at the new content. Eleven bytes are enough:
`string_array = ["ab","cd"]` decodes to `["cd","cd"]` when fed one byte at a time, and
`blob_array` does the same through the same helper.

*Two things make it worse than a wrong value.* A slice stored when the buffer held 60 bytes keeps
length 60 after a 2-byte payload replaces it, so reading it walks past the live content — visible
in the seed corpus as a 5-byte string read out of the 4-byte `five`, with one byte of adjacent
memory. And a payload larger than any before it **reallocates**, rebasing the earlier slices; under
an arena the old block stays mapped and the read is merely stale, but under a freeing allocator the
same pattern is a use-after-free. That last step is reasoned from the code, not observed — the
driver uses an arena by design.

*The control is what pins it:* a message with a **single** split element decodes correctly. The
defect needs two or more, which is why byte-at-a-time feeding finds it immediately and a two-way
split usually does not — and why the oracle implements both cuts rather than only the sweep.

Filed as generator#293 (F-0058 / G-0036), attributed to **generated code**: `_reassemble` and the
`setElem` call are both emitted, the corelib delivers `(total, offset, chunk)` faithfully, and
whether an element's destination needs its own copy is a storage question only the generated side
can answer. `zig` is kept out of `run-chunked.sh`'s opt-in roster meanwhile — same reasoning as the
F-0057 quarantine, and recorded in TODO.md so it goes back when the finding closes.

**Two unspecified contracts also surfaced, and neither is a wire question.** The differential oracle
is structurally blind to both, because they are differences in what the *API* promises rather than
in what the bytes mean. corelib-zig **borrows** a payload that arrives whole in one chunk and
documents that a fed chunk must outlive the message; the other ten copy. corelib-ts's `OStream`
cannot encode through a buffer smaller than its largest contiguous write (`SOFAB_FLUSH` 1–8 all
inapplicable, 16 works); the other ten stream the same 108 values through **one byte**. Both stand
at 10-to-1, both are recorded in TODO.md, and both wait for the last two backends before becoming
a `documentation` question — the camp sizes should be counted, not guessed.

**Both streaming oracles exist before any driver does, and that ordering is the point (2026-08-04).**
`chunk_invariance.py` gained the two cuts the contract specifies beyond its original two-chunk
sweep — `SOFAB_CHUNK=n` (fixed size; `n=1` splits every varint, length word and payload, so it
cannot straddle the boundary that breaks) and `SOFAB_CHUNK_SCRUB=1` (a *lifetime* check, not a
boundary one: a decoder that borrows from a fed chunk reads back scrubbed bytes). The
encode-side twin, `encode_invariance.py` + `scripts/run-encode.sh`, is new: the family is
byte-canonical, so one implementation's three encode surfaces must emit identical bytes for the
same value, and an `n`-byte `OStream` buffer must not change them either.

*Both are wired into `replay.yml` now, with no driver implementing either.* That looks
premature and is not: the gates skip **loudly** while their opt-in roster is empty, so landing
the first driver turns the gate on with no CI edit, and the interval between "oracle exists" and
"driver exists" cannot be mistaken for coverage. The alternative — wire it when the first driver
lands — is how a gate ends up quietly never being added.

*Two design decisions worth recording.* The encode oracle's baseline is the driver's **own
default path**, not `SOFAB_ENCODE=new`: comparing the surfaces only against each other would
pass a driver that read the variable and wired all three to the same call. And it asserts the
contract's hard-fail — asking for a surface the backend lacks must exit non-zero — because a
silent fallback reports a mode as passing that never ran, which is the exact failure the gate
exists to prevent, so it is checked rather than trusted.

*What running it today proves, and what it does not.* `typescript` fails the hard-fail
assertion, correctly: its `meta` declares only `stream`, and the untaught driver exits 0 when
asked for `new`. `cpp` reports **0 mismatches — a vacuous pass**, because it declares all three
surfaces, ignores the variables, and therefore agrees with itself everywhere. That is the whole
argument for the opt-in roster in one line: the assertion catches a driver that lacks a surface,
and nothing but an explicit roster catches one that has them all and drives none.

**The C++ matrix went from two configurations to four, and found a bug on the first run (2026-08-04).**
`allow_dynamic` used to be a `corelib: c-cpp` knob; generator#289 extended it to `corelib: cpp`,
and corelib-cpp#70 made `readString`/`readBlob`/`StringSeq`/`BlobSeq` storage-agnostic so the
heap-free containers work there too. crucible#129 asked for the resulting matrix to be covered
once the generator side landed. It had landed — the issue was filed the day before the merge —
so the four configurations are now `cpp` / `cpp-fixed` / `cpp-c-cpp` / `cpp-c-cpp-dyn`.

*It cost almost nothing to add*, which is worth recording because it was not obvious in advance:
`driver.cpp` and `materialize_gen.py` needed **no change at all**. Both had been written against
only the member API the two storage flavours share, a discipline adopted when the c-cpp variant
was first added, and it paid off exactly here. `build.sh` grew two cases; nothing else differs.

*The point of running them side by side is that the wire format is byte-identical across all
four*, so a divergence between them is a bug by construction rather than a question of
interpretation. That is not a theoretical argument: **F-0057** turned up on `cpp-c-cpp-dyn`'s
first run. Every zero-length array aborts an asserts-enabled build — `IStreamImpl::readArray`
resizes the growable destination to 0 and then hands `std::span{value}.data()`, which is
`nullptr` for an empty `std::vector`, to a C core that asserts `var != NULL`. Five bytes
(`a6 06 03 00 07`), a valid message, accepted by the other fourteen. The sibling that differs in
exactly one setting is what pinned it: `cpp-c-cpp` uses `InlineVector`, whose `data()` always
points at inline storage, so it never sees the null. Filed as corelib-c-cpp#131 — corelib, not
codegen: generated code passed the right count and the right bound, and every link in the chain
is corelib code.

*Decision: quarantine rather than a red gate, and a mechanism rather than an exception.* A
crashing driver takes its process down and poisons every subsequent record in the batch, so
`sweep_empty_frame` would have stayed red until upstream fixed it — and a permanently red gate
stops meaning "something new broke", which is the same reasoning `results/known-clusters.txt`
was built on. `drivers/roster` therefore carries a `blocking` tag: a driver without it is still
built and still runs under `ROSTER_TAG=` (the full roster), but stays out of the gates that
block. A quarantine entry **must name the finding**, so it is removable the moment that finding
closes and cannot decay into a silent exclusion.

*A refactor fell out of it that was overdue on its own.* The roster had been copied into five
places (`run.sh`, `materialize.sh`, `run-limits.sh`, `sweep_run.py`, `chunk_invariance.py`), so
adding two drivers meant editing six lists — and the streaming-encode oracle would have created
a seventh. It is now one file, `drivers/roster`, read by `scripts/roster.sh` on the shell side
and `oracle/roster.py` on the Python side. The limit-mode subset became a tag rather than a
hand-maintained second list, and reproduces the previous ten drivers exactly. One consequence
worth noting: `materialize.sh` broke on the first run of the refactor because its C-anchor step
still referenced a variable the old loop had set. That is the failure mode a five-way copy
hides — the sixth consumer nobody remembered.

**The generated API was realigned, and the hole that exposed got a contract (2026-08-04).**
sofabgen `cfe5250b` (generator#290/#291/#292) renamed `marshal`/`unmarshal` out of existence
and gave nearly every backend a chunked decoder. Rebuilding the whole roster against it cost
**one line** — `drivers/ts/driver.ts` was the only caller of a name that did not survive; every
other driver already spelled `encode` / `try_decode` / `tryDecode` / `decode`. All seven gates
are green on the new generator with no other edit.

*The interesting part is not the rename, it is what the rename made visible.* Each driver makes
exactly two calls into the generated code — one one-shot decode, one one-shot `encode()`. The
API now has a streaming surface on **both** sides of that, and the replay protocol can reach
neither: it hands every record over whole and re-encodes with a single call. So chunked decode
is untested in every implementation, and of the three encode surfaces (`encode()`,
`encodeTo()`, `serialize(os)`) the round-trip oracle exercises one. crucible#132 reports three
TypeScript bugs found while building its chunked decoder — a visitor callback that was simply
not implemented (an unimplemented optional callback is a **no-op** in TS, so the field silently
vanished), a Zig decoder that dropped every payload piece after the first *and* borrowed the
chunk, and 64-bit arrays the chunked visitor could not write. None crashed, none failed to
compile, and the conformance suite was green through all three.

*Decision: write the contract before writing any driver.* Eleven backends implementing a
streaming axis from eleven readings of "feed it in pieces" would produce eleven dialects, and
the resulting divergences would be harness artifacts rather than findings. `CONTRACT.md` now
specifies all five variables — `SOFAB_SPLIT`, `SOFAB_CHUNK`, `SOFAB_CHUNK_SCRUB` on the decode
side, `SOFAB_ENCODE`, `SOFAB_FLUSH` on the encode side — with the parts that would otherwise
drift made normative:

- **The verdict comes from the decoder's `status`, never from `finish()`.** Most backends throw
  there when the stream ended mid-field; Dart returns null instead. Routing the verdict through
  `finish()` would bake that difference into the canonical line and read as a family divergence.
- **Never synthesize an empty chunk** (`k<=0`, `k>=len`, `n>=len` all mean one whole chunk), and
  a zero-length record is still not fed at all — corelib-c-cpp asserts `datalen>0`.
- **A driver asked for an encode surface its backend lacks exits non-zero**, rather than falling
  back to another surface and reporting a mode as passing that never ran.

*Two mechanisms for declaring support, because one cannot cover both cases.* A driver that has
never heard of a variable emits byte-identical output and would pass vacuously — that is what the
gate's explicit roster (`SOFAB_SPLIT_DRIVERS`, `SOFAB_ENCODE_DRIVERS`) is for. A driver that knows
the variable but cannot honour it is a different failure, and hard-fails itself. `meta` records
the same facts declaratively in two new keys: `chunked_decode=push|pull|none` and
`encode_surfaces`. The notable entries are **go: none** — corelib-go has no resumable push decoder
at all, so it must be declared absent rather than silently skipped — and **python: pull**, whose
`deserialize(Decoder(reader))` needs the driver to wrap its chunks in a reader.

**The tolerance axis reached the union, and a false green was caught on the way (2026-08-03).**
`sweep_tolerance` gained an `emit_union` and joined the union pass. A union is an ordinary
sequence on the wire, so §4.9 binds its closing marker exactly as it binds a struct's — but it
lives in `schema/probe-union.sofab.yaml`, which the probe pass cannot reach. That is the same
product cell F-0044, F-0048, F-0053 and F-0054 all came out of: two axes each correct, the place
they meet untested.

*The first run of it was green for the wrong reason.* Invoking the axis directly leaves the
drivers built against `probe`, where the union id is simply unknown and every vector is skipped —
green, and meaningless. Only `scripts/sweep.sh` rebuilds the roster against `probe-union`, which
is what the runner's own banner says and what the re-run used.

*That prompted a guard the axis should have had from the start.* A `same:<twin>` vector now fails
if the twin re-encodes to the **empty** message: "same payload" is otherwise satisfied by any
driver that also produces nothing, proving no normalization whatsoever. That is precisely the
blind spot F-0054's isolate had, and an axis built to close it must not be able to reintroduce it
silently. Both passes stay green with the guard in place, so the twins carry real values.

**The tolerance axis, and an oracle that can see something the others cannot (2026-08-03).**
`sweep_tolerance` (CORELIB_PLAN §7.2 class **5b**) is blocking: 49 vectors over all 7 sequence
positions, green on all 13 drivers.

*Why it needed a new kind of assertion.* Every existing axis asks "do they agree?" and then
"is the verdict right?". Neither question can catch a family that is **uniformly** too strict,
because 13 rejects is unanimous and unanimity is what green looks like. It also cannot catch a
family that accepts a non-canonical form and echoes it straight back. So the runner gained
`expect="same:<twin>"` — accept **and** re-encode to the same bytes as the named canonical
vector. That is the contract change; the axis is its first user, and `sweep_varint`'s
non-minimal vectors are the obvious second.

*The axis was verified by breaking it.* A green new test that cannot fail is worth nothing, and
the first attempt at a negative test proved the point: putting an extra field id 7 inside the
`nested` struct changed nothing, because id 7 is undeclared there and §7.3-skipped — the test
was wrong, not the check. Making the canonical twin an empty frame instead produced **28
conformance failures**, four per position. The check fails when it should.

*Scope, deliberately.* Class 5b names two families; the non-minimal **varint** half is already
swept exhaustively by `sweep_varint` (WP-03) with the same `expect="accept"` reasoning, so it is
cross-referenced rather than duplicated — a second copy would only be a second place for the two
to disagree. This axis owns the sequence-end half, which is where F-0054 lived. Had all 13
implementations applied `ID_MAX` to wire type 7 — nine of them did — that finding would never
have surfaced at all.

**One finding, one folder, one write-up (2026-08-03).** The catalog was restructured rather than
patched again. Every entry — `F-00NN` **and** `G-00NN` — now has a folder under `findings/` whose
`NOTES.md` owns everything about it: the defect, the reproducer, the attribution and a
`## Resolution` chapter. `results/FINDINGS.md` is reduced to a single index table — link, upstream
ticket, state — and went from **917 lines to 113**.

*What moved.* The 60 kB of resolution prose that lived in the catalog's status column was migrated
into the write-ups as `## Resolution`, cut at the changelog marker where one had accreted (only
F-0010 genuinely had); the 19 `## G-00NN` detail sections became folders. Five codegen entries —
G-0014 through G-0018 — turned out to exist **only** as sections, in no table at all, which is its
own answer to how well two representations track each other. The "Phase 1 note" moved to this log,
where narrative belongs.

*Paired entries deliberately do not get a second folder.* Where a `G-00NN` is the generator side of
an `F-00NN`, its row points at that finding's folder. One defect, one write-up — creating
`findings/G-0027/` beside `findings/F-0043/` would have rebuilt the duplication this whole exercise
removed. The check enforces that their states agree instead.

Folders: **72** (55 findings + 17 standalone codegen defects). Index rows: **90**.

**F-0056 closed, and the harness gap it exposed written down (2026-08-03).** corelib-cpp#72
merged the same day; the fix names the mechanism more precisely than the finding did — a nested
`read()` that runs out of bytes returns *unconsumed*, exactly as a **declined** field does, and
the two were conflated. Verified against `48f06db`: all seven reproducers join the
12-implementation consensus, full suite green (nine gates, 1104 sweep vectors, materialize
0/108). Promoted to the regression gate (181 → **188**), camp signature deleted.

*The interesting part is what the fix deliberately left open.* Its author flagged that
`read(void *, size_t)` — the raw blob read — sets `error_` rather than `incomplete_`, and filed
it as [crucible#130](https://github.com/sofa-buffers/crucible/issues/130). I had probed that path
and reported "no split", which was **wrong**: my vectors declared a length of 20 against a
`maxlen` of 4, so they were over-bound and correctly `INVALID` rather than merely truncated. A
direct API probe against `48f06db` reproduces the issue's table line for line — `INVALID` then
unrecoverable, the buffered tail dropped, `blob=0 B` even after the rest arrives, while
`readBlob()` is correct in every row.

*Why this suite cannot see it, twice over.* Generated code calls `readBlob()`, so the broken
overload is never reached; and the replay driver feeds every record **whole**, while the defect
lives at a chunk boundary. The corpus can be as large as it likes and will never contain a
chunk boundary.

*So the gate was built and the drivers were not.* `oracle/chunk_invariance.py` +
`scripts/run-chunked.sh` implement both of #130's asks — sweeping every split point covers the
metadata/payload boundaries without the harness knowing where they are, and comparing the final
line against the whole-message line asserts that an `I` resumes. **No driver implements
`SOFAB_SPLIT` yet**, because every one of them decodes one-shot; the gate therefore skips
loudly rather than passing vacuously, which is the one thing it must not do — a driver ignoring
the variable produces byte-identical output. Landing one driver at a time is enough: alone among
these oracles, chunk invariance compares a driver *against itself*.

**The third strand, and the point at which intent was replaced by a check (2026-08-03).**
Reviewing the catalog from the outside — opening `findings/<id>/NOTES.md` the way a reader
arriving from an issue link does — showed the rot had a third strand, the largest of them:
**46 mismatches**. Four write-ups declared `**Status:** 🔴 OPEN` for findings the catalog had
marked resolved (F-0022, F-0027 through F-0034 among them), and **22 carried no status line at
all**, so every one of them read as unresolved to anyone who landed there directly.

*Two false alarms worth recording, because both would have caused damage if acted on.* The
F-0023 and F-0025 rows looked like broken markdown with unescaped pipes; they are correctly
escaped as `\|` and it was the *checker's* naive split that was wrong. And F-0018 has no
resolution because it is by-design — an allowed divergence, not an open item — so it now
carries a distinct ⚪ token rather than being forced into ✅ or 🔴.

*The fix is `scripts/check-catalog.py`, wired into `replay.yml` as a first, driver-free job.*
It asserts the **state token** agrees across the catalog row, `NOTES.md`, the `G-00NN` tracking
row and the `## G-00NN` section — and that every catalog row has a directory and vice versa. The
prose is not compared: it lives with exactly one owner per fact. Three strands of the same
duplication rotted in a single day while everyone involved intended to keep them current, which
is the argument for a gate rather than a resolution to be more careful. All 55 findings and 30
codegen entries now agree.

**The same rot on the other strand — the standalone codegen entries (2026-08-03).** Repairing the
paired `G-00NN` rows raised the obvious question about the twelve **standalone** ones, which carry
their state in a table row *and* a `## G-00NN` section. Checked rather than assumed, and three had
drifted the *opposite* way from the paired rows: **G-0011, G-0012 and G-0013** read `**Status:**
open` in their sections while their table rows said fixed — for generator#126 and #128, closed
2026-07-15, and #142/#149, closed 2026-07-17. Nearly three weeks stale. **G-0006** contradicted
itself on the release (section 0.15.2, row 0.15.1) and **G-0008** had no `**Status:**` line at all.

*The version question was settled rather than picked.* PR generator#90 merged 2026-07-08 20:22 UTC
and v0.15.1 was cut 21:43 the same day; `compare/v0.15.1...<merge sha>` confirms containment, so
the row was right and the section wrong.

*Ownership assigned the other way round from the paired case, and deliberately.* A standalone entry
has no finding row, so the **section** owns the detail and the table row shrinks to a state plus a
pointer. For G-0011/G-0012/G-0013 the table cell had grown to hold the entire write-up — several
hundred words duplicating the section beneath it — which is precisely why the two could disagree
for weeks without anyone noticing. The table header now states both directions of ownership.

**F-0055 closed 2026-08-03 — one open finding left.** generator#283 landed as `bd67d2b`
("stack only live scopes, so a deep skip can't lose") at 16:53, and its CI artifact arrived
shortly after. Verified on sofabgen `0.0.0-20260803165303-bd67d2b2f84c`, the **first build
carrying it**: an earlier sweep the same afternoon still showed the camp because the vendored
generator was 67 minutes older. The closed ticket was deliberately not taken as the resolution —
the isolate was.

*Read out per driver, because this finding is the reason that rule exists.* F-0055 was silent
**loss**: rust-no-std accepted a message and returned it empty. Had the fix gone the other way
and every implementation returned empty, the differential oracle would have reported the same
unanimous "0 divergences". It now re-encodes `5602200000c03f07` (`nested.f32 = 1.5`) like the
other twelve, with `r3_depth9_wrapper_lost` at `c60c020a4107`; both controls unchanged, and
`materialize.sh` 108 × 13 clean.

Reproducers promoted (`F0055_*`, gate 176 → **181**, green), camp deleted from
`known-clusters.txt`. **Tally: 53 resolved, 1 open** — F-0043 / generator#267, which still
produces seven clusters and is the last finding waiting on the generator.

**The tracking table had rotted, and that is a structural fault not a slip (2026-08-03).**
`results/FINDINGS.md` then carried two tables: the findings catalog and *"Tracking issues (generator
repo)"*. Nine of the ten `G-00NN` rows read **open** while their generator issues were closed —
G-0026, G-0028 through G-0035 — and in most cases the paired `F-00NN` row above had said
**resolved** for a day. Only G-0027 (generator#267) was genuinely open.

*The cause is duplicated ownership, not forgetfulness.* A paired entry stated its resolution
twice, in the F row and again in the G row, and closing a finding touched one of them. That is
the same failure CLAUDE.md's single-source rule describes, occurring **inside one file** rather
than across two — which is why it went unnoticed. Fixed by making the F row the owner: a paired
G row now carries the ticket and its state plus a pointer, and the table says so in a header
note.

*One row is deliberately amber rather than green.* G-0035 (= F-0055) — generator#283 is closed,
the fix `bd67d2b` landed at 16:53, but its generator CI run was still building, so no sofabgen
artifact carries it. Bootstrap correctly stayed on the last green build, F-0055 is therefore
**not** verifiable yet and stays open. A closed upstream ticket is not a resolution here; the
isolate is.

**Catalog swept 2026-08-03 — F-0052 and F-0053 closed, two findings left open.** After F-0054
landed, the four open findings were re-measured together against the current family: corelibs at
`main` and sofabgen refreshed to the CI build `0.0.0-20260803154628-1e4359a8a1c0` (the vendored
one was a day old, which matters when the finding *is* a codegen defect).

*Result: 33 reproducers, 8 clusters — and all eight belong to the two findings that are still
open upstream.* F-0043 (generator#267) accounts for seven, F-0055 (generator#283) for the eighth,
still the silent-loss form where rust-no-std alone returns the empty message. F-0052 and F-0053
produce **no cluster at all**.

*Closed, each verified by verdict rather than by agreement.* F-0052 — generator#279 armed the C++
backend's `readArray` element bound; `cpp` no longer masks 5208 to 88, and the `ctl_u8_array_inrange`
control still round-trips `c801`, so the bound was armed without over-tightening. F-0053 —
corelib-go#68 and corelib-ts#84 moved the element-varint check ahead of the count-vs-remaining
short-circuit; `r1_count11_overlong_elem` is `R invalid_msg` where those two said `I`, and count 11
with enough bytes still accepts. Both were checked on `materialize.sh` too (108 × 13, 0 divergences,
0/108 C-anchor mismatches), which for F-0052 is not ceremony: it is a *value* defect, and a masked
element that still round-trips is what the round-trip oracle can miss.

*Housekeeping in the same sweep.* Eleven reproducers promoted to `corpus/regression/` (165 → **176**,
gate green), and **three** camp signatures deleted from `known-clusters.txt` — F-0052 had two, its
accept form and its truncated-`I` second symptom. F-0010's status cell was normalized: it has been
resolved since 2026-08-02 but opened with the historical *"spec-RESOLVED, corelibs converging"*, so
it counted as open to anything parsing the catalog. Tally is now **50 resolved, 2 open**.

**F-0054 closed 2026-08-03 — fixed in all three repos the same day it was specified.**
corelib-go#70, corelib-py#60 and corelib-ts#86 landed within the hour: go deleted its
`t != TypeSequenceEnd` exception (a removal, and it reconciled go's two decode surfaces as a side
effect, so that sub-finding never needed filing), py bounded the id in both engines, ts on all
three surfaces. The five reproducers are in the green `corpus/regression/` gate as `F0054_*`,
**controls included**, and the camp signature is *deleted* from `known-clusters.txt` — a resolved
camp left in the baseline would match a regression as "known" and hide it.

*The verification is the part worth remembering.* `run.sh` reported `5 agree, 0 diverge`, and
that is exactly the signal Option C would have produced too: over-tighten everywhere and the
three controls flip to `R` **together**, so the oracle sees unanimity. The verdicts were
therefore read out per driver — isolate `R invalid_msg` ×13, controls `A` ×13 — confirming that
exactly one test point moved. This is the same class §7.2's new tolerance tests exist for, and
Crucible's own gap on it is still open in `docs/TODO.md`.

**F-0054 settled 2026-08-03 — documentation#35 merged as `acd27a4`, Option B is normative.** The
provisional wording is out of the catalog, the finding and `docs/TODO.md`; the `ID_MAX` ×
sequence-end sweep cell is pinned to **`reject`**, with the at-or-below-`ID_MAX` and
over-64-bit-varint cells pinned alongside it. Upstream is clean: the eight Option-A issues, their
eight draft PRs **and** their eight branches are gone, and F-0054 stands on three issues —
corelib-go#69, corelib-py#59, corelib-ts#85.

*The cost of getting this wrong twice, recorded plainly:* three positions on one clause in a day,
19 issues/PRs opened and 16 of them withdrawn, and three repos that received two contradictory
instructions each before the right one. What made it recoverable was that the isolate and its
three controls never moved — only the question of which camp they indicted. A finding whose
*evidence* is stable survives its own attribution being wrong.

**F-0054 turned back 2026-08-03 — Option B raised, and the spec inversion below is being
reverted.** Reading the eight draft PRs the re-filing produced made the cost of the merged
Option A concrete: each of the nine rejecters carries **one unconditional** `if (id > ID_MAX)`
between splitting the header and dispatching on the wire type, and A makes every one of them
grow a per-wire-type exception there — nine drivers, eight repos, several with two or three
decode surfaces apiece, in the header hot path.

*Decision: propose Option B — bound the id's value like every other header's, then discard it.*
The §4.1 objection that killed Option C does not reach B: C constrained the **spelling** (it
would have made `0x87 0x00`, a non-minimal id 0, `INVALID`), while B constrains the **value** and
leaves §4.1 untouched. Behavioural cost is identical to A — exactly one test point moves, the
isolate itself; only C would have moved three. And B is the only option that *removes* branching:
the nine stay untouched and `corelib-go` deletes the exception it already carries
(`cursor.go:272`). Filed as
[documentation#35](https://github.com/sofa-buffers/documentation/pull/35), which reverts #34 and
keeps its tolerance test class 5b.

*What the code archaeology showed, and it corrected the earlier write-up.* The three accepters do
**not** share one gap: `corelib-ts` never computes the id for an end marker, `corelib-py`
computes it and checks it after the seq-end branch, and `corelib-go` carries a written-out
`t != TypeSequenceEnd` exception — it had coded Option A before Option A existed. That is the
strongest evidence for A, and it is recorded in the finding rather than argued away. It also
turned up a separate defect: go's two decode surfaces **disagree** with each other
(`cursor.go:272` has the exception, `decoder.go:65` does not), which is a finding under either
option.

*Housekeeping.* F-0054's directory now carries an outcome-neutral slug — the attribution moved
twice in one day and the slug moved with it, which is churn the id already prevents. The eight
issues and their draft PRs are held, not closed, until #35 is decided; the finding records that
it reverts to the nine if #35 is rejected.

**F-0054 inverted 2026-08-03 — the spec settled the question against the way we filed it.** The
finding reported the four impls that *accept* an over-`ID_MAX` id on a sequence-end header. The
merged `CORELIB_PLAN.md` (`main@51c777d`) now says accepting is required: §4.9 — a decoder *"MUST
accept a sequence-end header (wire type `0b111`) carrying **any** id, discard that id, and
re-encode the marker as `0x07`"*, a non-zero id being *"**not** `INVALID`"* but normalized away as
a non-minimal varint is; §6.2 adds that `ID_MAX` bounds *"the id of a **value-bearing** field
header"* and not the end marker; §5.2/§6.3 never listed the case. So the divergence stands, the
attribution flips: the four accepters are conformant, the **nine rejecters** are the defect —
8 corelib repos, and the fix is a *removal* (drop the `ID_MAX` guard on wire type 7).

*Decision: the merged document is the only authority.* The three issues we filed were closed the
same day "resolved-by-decision" on a proposed rule — a seq-end id fixed at 0, non-zero `INVALID` —
that **never became normative**; the spec change they deferred to landed the opposite rule. That
comment also announced flipping the two `ctl_seqend_*` controls to `R`, which the merged text
contradicts. Neither an issue comment nor a PR's commit rationale is a clause: F-0054 was rewritten
from §4.9/§6.2/§5.2/§7.2 as merged, and the stale closures are recorded in the finding's *History*
so nobody re-derives the rule from them. Re-filing against the eight repos is still open.

*What it exposes about the harness.* §7.2 gained test class **5b, tolerance tests** — a decoder
must not be *stricter* than the format allows — and Crucible has no axis for it. An implementation
that is uniformly too strict yields **no divergence**, so the differential oracle is structurally
blind; F-0054 surfaced only because the family happened to split 4-vs-9. Sweep vectors carry an
absolute expectation, so the class is testable; two `docs/TODO.md` items now cover it (the
tolerance axis, and a vector for the normalization half — the present isolate closes a *skipped*
subtree, so the discarded id is unobservable and only the verdict is proven).

**F-0055 found 2026-08-03 — silent data loss in rust-no-std, and the first finding this week
reached by reading source rather than by probing.** Chasing the two large `rust-nostd`-only camps
refuted four hypotheses in a row (message size, large skipped payloads, the §6.4 mid-payload
`MAY`, repeated sequence re-opens). The fifth attempt read the generated visitor instead, and the
defect was one line:

    stack: heapless::Vec<_Loc, 8>,
    let _ = self.stack.push(self.cur);

`MAX_DEPTH` is **255** (§6.2), so nine levels is legal — and the discarded `Result` means that
past eight the push does nothing, the matching `pop` restores the wrong scope, and a field
written after the unwind **binds nowhere**. rust-no-std accepts the message and returns it empty:
no error, no rejection, a field the sender wrote simply gone. Of the three possible outcomes that
is the worst.

*Threshold exactly at the capacity*, 24-byte isolate, `rust-std` correct with the same schema and
generator (growable `Vec`) — so codegen, **G-0035**.

*Why the existing depth vectors could not see it.* Nesting **only** unknown sequences is
unaffected to depth 14: every scope is `Dead`, the dropped pushes are the deepest, and the
surplus pops return `unwrap_or(Root)` — accidentally the right answer. The corruption needs a
**real scope underneath the overflow**. F-0050's vectors nest 255/256 deep and set no field, so
they pass. Two correct-looking tests, and the cell between them empty — the same shape as F-0044,
F-0048, F-0053 and F-0054 before it.

*What it does not close.* The two camps that led here still show `rust-nostd` **rejecting**, and
F-0055's proven form is silent loss. The mechanism plausibly explains both — a desynchronised
scope can trip `inv` — but that is stated as unproven in `docs/TODO.md` rather than assumed. Four
refuted hypotheses in one session is a good reason not to accept the fifth on plausibility.

**Minimizer rebuilt batched 2026-08-03 — ~80× on the case that mattered.** Triaging the
nightly corpus stalled on two large representatives: the delta-minimizer ran for over half an
hour on a 1132-byte input at **~3 % CPU** and produced nothing.

*The profile explains it, and it is not computation.* Measured across the 13 drivers: a 1-input
corpus costs **1507 ms**, a 100-input corpus **10 ms per input**. Java alone is 441 ms of JVM
boot, python/csharp/typescript ~200 ms each. Checking a hundred candidates is therefore *cheaper*
than checking one, and the old minimizer paid the 1.5 s for **every** shrink attempt — spending
its entire run in process teardown while the CPU idled.

*Rebuilt to batch every candidate of a round into one corpus*, plus an optimistic step: deletions
that each hold alone are first tried together (back to front so indices stay valid), falling back
to one at a time only if the combination fails. Result on the same inputs — 25 B: 57 s → 16 s
with byte-identical output; **1132 B: >35 min with no result → 2 min 15 s, down to 150 B**.

*It replaced the old one rather than joining it*, and moved from a scratch directory into
`oracle/` beside `comparator.py` and `cluster.py`. It takes the driver roster as `--driver
name:path` the way `cluster.py` does and is reached via `MINIMIZE=<file> ./scripts/run.sh`, so
the roster stays defined in exactly one place instead of a fourth copy.

*What it unblocked.* `7f7060b8` — the 22-input camp where `rust-nostd` alone rejects — is now a
150-byte reproducer where no single-byte deletion holds the partition. That is a genuine minimum
for byte deletion and consistent with the accumulation signature the two-sided binary search
found earlier (shortest prefix 1132, latest start 0: nothing can be stripped from the front). The
case is analysable for the first time.

**Nightly-corpus triage 2026-08-03 — four of seven unknown camps explained, two new findings.**
The first review of CI's accumulated corpus (8512 inputs, 17 camps) produced **F-0053** (an array
count outrunning the input short-circuits to `INCOMPLETE` before the element varint is validated
— corelib-go, corelib-ts; threshold measured exactly at count 11) and **F-0054** (`ID_MAX` not
applied to a sequence-end header's id — corelib-go, -py, -ts), plus addenda to **F-0052** (second
symptom: masking degrades a truncated message to `I`) and **F-0043** (a finer truncation offset
that moves five impls out of its "correct" camp).

*Both new findings sit in the corelib, which is a shift.* Everything filed in the previous two
days was codegen. These are wire mechanics in a skip path, where no schema knowledge exists and
generated code is not consulted at all.

*Three camps are left open on purpose.* `c5d8b383` (cpp alone) and the pair `7f7060b8` /
`8e989f1f` (rust-nostd alone) resisted the cheap isolates. For the rust pair, message size, a
large *skipped* payload and the §6.4 mid-payload `MAY` are each ruled out by explicit controls —
which is worth more than a guess, because the `MAY` isolate splits **zig**, not rust-nostd, and
would have been an easy misattribution. They are on `docs/TODO.md` with what has been eliminated.

*Two refuted hypotheses were worth the time.* An overlong varint inside a skipped array, and an
over-`ID_MAX` id on a *data* header, both agree across all 13 — and each refutation narrowed the
next isolate. F-0054's final form is 6 bytes because the failed attempt established that the
ceiling *is* enforced on ordinary headers, leaving the end marker as the only candidate.

*A tooling footgun, recorded so it is not re-hit.* The minimizer spawns all 13 drivers per
candidate, and `run.sh` rebuilds them — `cargo` briefly unlinks the rust binary while relinking.
Running a minimization concurrently with any `run.sh` kills it with a `FileNotFoundError` that
looks like a timeout. Two runs were lost to this before the pattern was clear.

**Corpus policy reversed 2026-08-03 — CI's corpus strictly dominated ours, and we had been
throwing ours away.** Reviewing the first nightly to run the Go engine (it worked: 8700 seeds,
11.3 M execs, 180 new inputs, step green) surfaced something larger than the nightly's own
result: its clustering reported **17 camps on 8512 inputs**, against 8 on our local 547.

*Measured rather than assumed.* Downloading the nightly artifact and clustering it against our
own freshly built drivers reproduced all 17 exactly, so it is not a family-version artifact. The
two corpora overlap in **21 files — 3 %**; they are near-disjoint lineages. And clustering the
**union** (9038 inputs) yields **17** — the same as CI's alone. Our corpus contributes **zero**
divergence classes CI does not already have, after far more CPU: 577 M execs last night alone.

*Why: we minimized after every round and CI never did.* The rule adopted 2026-08-02 —
coverage-minimal ∪ hard-diverging — preserves the divergences measurable **at the moment of
minimizing**. An input that only starts diverging after the next corelib rewrite is discarded
first. The STATUS-LOG entry that introduced it said hard divergences are "preserved by
construction"; that holds for the instant it is run and not for the corpus's future, which is
the property that actually matters for a corpus.

*Policy now:* the corpus is the **union**, kept whole (9038). Minimization stays a tool for
speeding up an ad-hoc triage run, never maintenance of the canonical set. The ~10× slower full
cluster run is the price, and it is small next to nine unexamined divergence classes.

*And the nightly's clustering is now read by a machine.* It has clustered and uploaded since it
was written; nobody opened the artifact, and the unexplained camps accumulated unnoticed.
`oracle/cluster.py --baseline` now diffs every camp against `results/known-clusters.txt` — a
camp is listed there only once **explained** (a catalogued finding, a legal divergence, a benign
soft axis) — and exits non-zero otherwise, turning that step red inside an otherwise green run.
Ten camps are accounted for today; **seven are not**, and they are the triage queue. An unread
artifact is not a signal.

**4-hour pacemaker round 2026-08-03 — 577 M execs, one new cluster, which decomposed into two
defects.** Corpus 878 → **2609**, 0 ASan/UBSan hits, crashes unchanged at 6, all three jobs
converged on `cov: 666 ft: 4786`. Run at **3 jobs deliberately**: libFuzzer caps `-workers` at
`ncores/2` on this box, so a fourth would have queued and doubled the wall clock — the trap from
the 2026-08-02 round, now avoided rather than re-learned.

*Seven of the eight clusters are the known state.* The new one minimized to an `arrays.i8`
element of 5208 with the array truncated after it — and rebuilding it as a clean isolate with
controls showed it was **not one finding**:

- **F-0052 / G-0034** — on the *complete* form, cpp alone accepts and re-encodes the element as
  **88** (5208 mod 256). corelib-cpp shipped the check in #67, but as an **opt-in**
  (`readArray(…, ElemBound elem = {})` behind `if (elem.armed)`), and the C++ backend passes two
  arguments at all ten call sites — `grep -c ElemBound` on the generated header is 0. Codegen,
  the F-0042 shape: a corelib widens a hook and the fix completes only when the backend consumes
  it. Corroborated by `cpp-c-cpp` being correct: same backend, different corelib API.
- **F-0043, third bound** — on the *truncated* form, dart/go/py×2/typescript defer to array
  completion although they reject the complete form. Same rule as the finding's `maxlen` and
  element-id rows, now on documentation#32's declared-integer-width bound.

*The mistake this avoided.* Both defects put their impls in the same `I` camp on the truncated
vector, so the obvious reading was one finding with a seven-impl camp. cpp is there for the
**opposite** reason — it never detects the violation at all — and folding it in would have
overstated F-0043 by one impl and hidden a codegen bug behind a precedence one. The separating
control is an *in-range* element, the same shape that separated F-0047 from F-0051 the day
before. Twice in two days, a camp match was a hypothesis rather than an attribution.

*Coverage gap recorded.* The declared-width bound had vectors only at **scalar** positions
(F-0033's four). Nothing tested an over-width **array element** — which is why cpp's masking
survived F-0033's closure and needed 577 M execs to surface. That is the same scalar-only blind
spot F-0049 had for fp32 raw bits, in the same week; `docs/TODO.md` now carries it as a
`sweep_overbound` extension rather than a one-off vector.

**Verification bump 2026-08-02 (late) — three corelibs moved, nothing regressed.** Re-pulled
the whole family: corelib-dart `1b83161` (**perf/word-wise-varints**), corelib-zig `29ca282`
(**perf/swar-varint-codecs**) and corelib-go `c6e0952` (tests only — fp32 NaN-bit coverage, the
go-side counterpart of F-0031/F-0049). The other eight corelibs and sofabgen were already at
tip.

*Two of the three are varint codec rewrites*, which is the change class this suite exists for —
the varint reader is the hottest path in the format and carries F-0016's 64-bit overflow check
in the tenth byte. Result: **all 8 gates green, all 11 sweep axes green** (`sweep_varint` 25/25,
`wiretype_sweep` 363/363), both oracles green (`materialize.sh` 108 × 13, C anchor 0/108), and
re-clustering the 878-input corpus reproduces the previous state exactly — 7 clusters, same
representatives, same counts. No new divergence anywhere.

*F-0043 re-checked and unchanged.* Still open (generator#267, awaiting review), and its camps
are byte-for-byte the catalogued ones across all four clusters — the corelib work did not move
it. Nothing to re-attribute.

*Catalogue state: 51 findings, exactly one open.*

**F-0049 closed 2026-08-02 — and the upstream fix was only half of it.**
[generator#275](https://github.com/sofa-buffers/generator/issues/275) landed as
`fix(dart): the fp32 raw-bits companion must be consumer-visible`: the generated field is now
the public `int? f32Fp32Bits` instead of a library-private one. Ten of eleven findings are now
resolved; only F-0043 (generator#267) remains.

*The half that was ours.* Making the bits visible does not make anything read them.
`drivers/dart/materialize_gen.py` was still formatting the widened double, so the divergence
would have survived the fix — as **Crucible's** defect rather than dart's. The walker now reads
the companion (`_f32Scalar`), mirroring the `_f32Elem` array path added earlier the same day.
Worth stating plainly because it is a recurring shape: when a fix *exposes* a channel, the
consumer side is a second piece of work, and a green upstream issue does not imply a green
oracle.

*Verified on the oracle that can see it.* `materialize.sh` — 108 × 13, 0 divergences, C anchor
0/108. `run.sh` was green before and after and proves nothing about F-0049, which is exactly why
the finding was scoped to the materialized oracle when it was filed.

*`f32_snan` is back in `corpus/structured`* after being carved out since F-0031, so the scalar
signalling NaN now sits in a **blocking** gate rather than in a finding directory. That closes
the last carve-out of the F-0031 arc: of its three original stragglers, two turned out to be
Crucible's own drivers and the third a codegen visibility gap — and it produced no upstream
issue against a corelib, correctly.

*A timing note, the mirror of this morning's.* The fix merged at 19:25 but its generator CI run
was still in flight, and `bootstrap.sh` installs the newest **green** artifact — so a bootstrap
right after the merge silently reinstalled the *pre-fix* build and the generated dart still had
the private field. Verifying then would have reported "still broken". This morning the hazard
was bootstrapping too early relative to a merge; here it is the artifact lagging the merge.
Both come down to the same rule: check what the toolchain actually is before believing a
verification result.

**Family bump 2026-08-02 (evening) — eight of eleven findings fixed and verified the same day
they were filed.** Every corelib moved plus sofabgen twice. Upstream closed, in a few hours:
generator **#266, #268, #270, #271, #272, #273**, **corelib-c-cpp#126**, **corelib-cpp#65** —
i.e. F-0033, F-0044, F-0045, F-0046, F-0047, F-0048, F-0050, F-0051.

*Verified, not assumed.* All 43 vectors from the eight findings converge across 13 drivers (the
one residual cluster is the benign java soft axis, verdict unanimous). Where a fix has a
*direction*, the direction was checked rather than the agreement: F-0033's over-width vectors
are `R invalid_msg` with the in-range control still `A`; F-0050's depth boundary now measures
`255:A 256:R` on c, cpp-c-cpp and cpp alike; F-0051's reproducers accept and re-encode to the
**empty** message, i.e. the subtree is skipped rather than rejected. Agreement alone would have
been satisfied by a family-wide wrong answer.

*All three report-only probe axes went blocking.* `sweep_framing`, `sweep_unknown_seq` and
`sweep_repeated_elem` — built earlier the same day and each red on exactly one open finding —
are green and folded into the blocking call. **Every probe axis now blocks; only the union pass
is report-only.** That is the ground-rule-4 lifecycle running to completion inside one day:
axis built red → finding filed → fix landed → axis promoted.

*Reproducers promoted* into `corpus/regression/`, 117 → **160** inputs, gate green. A
regression now fails CI instead of waiting for someone to re-run a finding by hand.

*One process note worth keeping.* The first bootstrap of the evening ran a few minutes before
corelib-cpp#66/#67 merged, so F-0050 and F-0033 were verified against a family that was already
stale — harmless here, but it is why the re-bootstrap happened before touching F-0051. When
upstream is moving this fast, "bootstrap then verify" has to be one step, not two.

*What is left, and it is a clean picture.* Re-clustering the 878-input corpus against the fixed
family gives **7 clusters, down from 17**: one benign java soft split, one legal §6.4 `MAY`
(documentation#33), and **five that are all F-0043** ([generator#267](https://github.com/sofa-buffers/generator/issues/267),
still open — expected to take longer). Every remaining *hard* divergence in the corpus is that
one finding. **F-0049** (generator#275) is open too but structurally invisible to this
clustering: it lives only in the materialized oracle. generator#239 (reserved words) is not a
finding.

*The collapse is corroboration, not proof.* A family-wide wrong answer would also show as
agreement — each of the eight fixes was verified on its reproducers' verdict **direction**
first, and the cluster collapse read afterwards.

**`cpp`'s half of the Go-found cluster resolved 2026-08-02 — it is not F-0047, it is F-0051.**
The open question from the triage was whether cpp's inclusion was codegen (add it to
generator#272) or corelib-cpp. The answer turned out to be neither: **cpp is not affected by
F-0047 at all**, and adding it would have been a misfile against a real issue.

*The control that separates them.* Take F-0047's construct — a `string_array` element opened as
a mistyped sequence — and vary only the **child id**. With an in-range child (0), cpp emits the
**empty** message: it skips the element correctly, exactly like the six conformant impls, while
F-0047's six enter it and bind the child as `string_array[0]`. So cpp never enters the subtree,
and cannot be rejecting the over-index case because it "found an over-index element". Its defect
is the mirror image: the wrapper's `count` bound stays **armed while skipping**, so a child id ≥
the count trips §7.1 from inside a subtree that §7.3 says is not the array's at all.

*Not specific to §7.3.* Replacing the mistyped element with an **unknown field id** — a
different reason to skip, same shape — reproduces it identically, and a struct-scope control
(no `count`) is unanimous on all 13. So it is the wrapper's bound leaking into any skip.

*Attribution: corelib-cpp.* The generated code passes `count` in and publishes the element type
as `StringSeq::elemWire`; enforcement is entirely the corelib's. The sibling settles it —
**`cpp-c-cpp` is correct**, same C++ backend, different corelib, so the split follows the
corelib boundary (the F-0013 / F-0050 signature). corelib-cpp's own header documents the rule it
misses: a contradicting element *"is not this array's element at all … bound or no bound"* —
which it honours for the element and not for its children. Filed as [corelib-cpp#65](https://github.com/sofa-buffers/corelib-cpp/issues/65).

*The general lesson, worth more than the finding.* Two defects with **opposite mechanisms** —
enter-and-bind versus skip-but-still-enforce — produce **identical camps** on every vector where
the child id is over the bound. Only an in-range child tells them apart. A camp match is a
hypothesis, not an attribution; this one would have survived any amount of additional
over-index evidence.

**`sweep_framing` gained MAX_DEPTH boundary vectors 2026-08-02 — and the gap was two-fold, not
one.** F-0050 existed because the axis that *owns* the `MAX_DEPTH` rule tested only depth 300
(far over) and 8 (far under), never the boundary. Fixing that alone would not have caught it.

*The second half.* The old vector nested through `hdr(0, WT_SEQ_BEG)` — root id 0, a **scalar**
(`u8`) opened as a sequence, which §7.3 says to skip. So the entire chain sat inside a skipped
subtree and exercised the **skip path's** depth counter. Measured directly: depth 256 built that
way is unanimous across all 13, while depth 256 built through the declared `nested` (id 10)
splits. Two different counters, and only one of them is off by one. The axis now sweeps both
constructions at both depths, closed and truncated — 14 → 22 vectors — and fails on exactly the
two F-0050 vectors, nothing else.

*What was deliberately not added.* `FIXLEN_MAX` and `ARRAY_MAX` get no boundary vectors. §6.2
gives them as *"up to 2,147,483,647 (may be 65,535 on constrained profiles)"* — the ceiling is
**profile-dependent**, so no single at-the-boundary value exists that the whole family must
agree on: at 65,536 a constrained profile must reject and a heap profile must accept, and that
split is legal rather than a finding. The existing over-ceiling vectors use 2³¹ precisely
because it is over on *every* profile. Only fixed format-wide ceilings can be swept at their
boundary, which leaves `ID_MAX` (already covered, plausibly why nothing has surfaced there) and
`MAX_DEPTH`. The `docs/TODO.md` item had assumed all four were addable; that was wrong, and the
reason is recorded in the axis itself so it is not re-attempted.

**Both Go-found clusters triaged 2026-08-02 — and neither was what its camp suggested.**

*Cluster 14 → **F-0050**, a new corelib finding.* At 256 bytes it looked like the familiar
INVALID-vs-INCOMPLETE precedence class (11 reject, `c` + `cpp-c-cpp` say `I`). It is not. The
input is 256 nested sequence opens, and the deciding vector was one the fuzzer never produced:
the same depth **fully closed**, with no truncation anywhere — where c and cpp-c-cpp still
**accept** and re-encode to the empty message. Sweeping depth through `c` gives
`254:A 255:A 256:A 257:R`, so it is a clean **off-by-one** against `MAX_DEPTH = 255`, not a
precedence bug and not a missing check. Attribution is **corelib-c-cpp**: depth is wire
mechanics, and the affected set is exactly the two profiles sharing the C `istream` while
`cpp`, with its own corelib, rejects correctly. Filed as [corelib-c-cpp#126](https://github.com/sofa-buffers/corelib-c-cpp/issues/126) — the first corelib issue in days; everything else open sits with the generator.

*Cluster 15 → **F-0047's second symptom**, 374 B → 5 B.* `c6 0c 26 2a 02` — a `string_array`
element opened as a mistyped sequence with a child at id 5. Sweeping the child id breaks
**exactly at 5**, which is the schema `count`: the leaked child lands in the *wrapper's index
scope*, so an id at or above the count trips §7.1's over-index check and flips the verdict
instead of corrupting a value. An in-range control (id 4) and a struct-scope control (same id,
no `count`) are both unanimous, so it is the wrapper's bound and nothing else.

*That one looked like it widened an upstream issue — and the caution paid off.* The first
reading was that cpp had joined F-0047's enterers and generator#272's impl list was incomplete.
It was **deliberately not filed** pending a check of whether cpp's half was codegen or corelib.
That check (below) showed the reading was wrong outright: cpp is **not** on F-0047 at all. Had
it been filed on the spot, it would have been the F-0008 misfile — a real impl added to a real
issue that does not own its defect, which is harder to unpick than an obviously wrong report.

*A gate gap fell out of F-0050.* `sweep_framing` owns the `MAX_DEPTH` axis and still missed an
off-by-one, because it tests only depth **300** (far over) and **8** (far under) — the boundary
is never exercised. The same shape holds for `FIXLEN_MAX` and `ARRAY_MAX` (2³¹ vs 1); only
`ID_MAX` has an at-boundary control, which is plausibly why no off-by-one has surfaced there.
Two more could be sitting in the untested boundaries. On `docs/TODO.md` as its own item.

**Second steering engine 2026-08-02 — Go, and it found two new divergence classes in 60
seconds.** `docs/TODO.md` had carried "Multi-impl coverage" as *the biggest architectural gap*
since the start: only the C corelib steered the fuzzer, so the search was rewarded solely for
reaching paths that are complex **in C**. Every finding in another language came from the
differential over a C-grown corpus, or by hand — never from a fuzzer steering on that
language's own decoder.

*Built.* `scripts/fuzz-go.sh` + `drivers/go/gocorpus.py`. Go's native `go test -fuzz` needs no
external framework and the entry point (`drivers/go/fuzz_test.go`) already existed unwired; the
work was the plumbing. Go keeps its corpus — seed corpus *and* the coverage corpus under
`$GOCACHE` — in a text format, not raw bytes, so both seeding and harvesting need conversion.
`gocorpus.py` owns that format alone. It writes every byte as `\xNN` (always a valid Go
literal, so no byte needs special-casing), and reading handles the richer set Go emits,
including `\u`/`\U`, which name a **code point** and so contribute its multi-byte UTF-8
encoding — getting that wrong would silently mangle every non-ASCII vector. Verified in both
directions before use: 206 raw files round-tripped, and all 158 files Go itself had written
parsed.

*Result on the first run.* 60 s, 2.99 M execs, 299 new inputs, corpus 579 → 878. The
differential over the grown corpus went **15 → 17 clusters** — two divergence classes the C
pacemaker had never produced across ~370 M execs over the same schema. Both are §5.2
INVALID-vs-INCOMPLETE precedence splits with camps no catalogued finding has, and in both the
**C family is the lenient side**, which is unusual enough to be worth its own triage. Filed as
a TODO item, deliberately untriaged: a 256-byte input with a suggestive camp proves nothing
until it is minimized and controlled.

*Why this is the argument for the item and not just a nice result.* The pacemaker cannot be
rewarded for reaching a path that is only complex elsewhere — that is a property of
coverage-guided search, not a tuning problem, and no amount of additional C-steered budget
fixes it. One minute of Go-steered fuzzing beat two rounds of C-steered fuzzing on this axis
because it was measuring something the other engine is structurally blind to.

*Wired into `nightly.yml`* after the C pass at a quarter of its budget, non-blocking. Four
languages remain unwired (ts / java / csharp have entry points; **rust has none and is the
most valuable next**, since six of the eight open findings involve a rust backend).

**Pacemaker round 2026-08-02 — first fuzzing against the rewritten C dispatch; no new root
cause.** ~174 M execs under ASan+UBSan against corelib-c-cpp `17f9a8e`, whose
`perf(footprint)` commit churned 265 lines of `object.c`'s per-type dispatch plus
`istream.c`/`ostream.c`. **0 sanitizer hits, crashes unchanged at 6**, corpus 5306 → 5994
(+688). Re-clustering the grown corpus gives 15 clusters again, every one mapping onto a
catalogued finding at unchanged camps; of the +300 diverging inputs, 286 are the benign java
soft axis and the remaining 14 spread over three known findings. Details in
[`../results/CLUSTERS.md`](../results/CLUSTERS.md).

*Two operational facts worth not re-learning.* `-jobs=4` does **not** mean four concurrent
jobs: libFuzzer defaults `-workers` to `ncores/2`, so on this 6-core box three ran and the
fourth queued — a nominal "3 h, 4 jobs" is ~6 h of wall clock. And the per-job `fuzz-N.log`
files are **not** cleared between rounds: `fuzz-3.log` still held the 2026-08-01 round's
`DONE cov: 721 ft: 5215` while this round was running, which reads as a current result to
anything that just tails the logs. Both are recorded in the snapshot.

*Decision: stopped at 1 h 10 of the 3 h budget, by request.* Defensible on the evidence — all
three jobs had converged on `cov: 666 ft: 4785` to the last digit, which indicates saturation
rather than a run cut short. But stated plainly in the snapshot: "no new cluster" means *not
within this budget*, and 688 fresh coverage inputs say there was still structure to find. A
null result from 1 h 10 is weaker than one from 3 h and should not be quoted as if it were the
same.

*Corpus minimized afterwards — and the obvious method was wrong.* `corpus/interesting` had
never been minimized; `docs/TODO.md` proposed `libFuzzer -merge`. Done naively that is a
**signal-destroying** operation here: the merge gives 503 files and **6 clusters instead of
15**, silently discarding the corpus evidence for F-0045, F-0046, F-0047 and F-0048 among
others. The reason is structural — `-merge=1` minimizes by **C coverage**, while the oracle is
disagreement among **13** drivers, so two inputs indistinguishable to the C pacemaker can carry
entirely different divergences elsewhere. The coverage proxy simply does not track the thing
being minimized for.

*Rule adopted instead: coverage-minimal ∪ every hard-diverging input.* 503 ∪ 85 = **579 files,
all 15 clusters, every representative byte-identical**. Hard divergences are preserved **by
construction** rather than by trusting the proxy. Verified by clustering all three corpora and
comparing, not by assuming. Local only — the corpus is gitignored and CI gates on
`seeds`/`regression`/`conformance` — so the gain is triage speed (a full cluster run drops from
~10 min to under a minute) and the durable artifact is the rule, recorded in `CLUSTERS.md`.

*The finding that did not grow.* F-0048's cluster stayed at exactly 8 inputs. It needs a
repeated element id inside a wrapper — a shape the mutator does not stumble into. That is the
empirical argument for `sweep_repeated_elem`, added the same day: what the fuzzer cannot reach
has to be enumerated.

**Two sweep axes added 2026-08-02 — the cells F-0044 and F-0048 walked through.** Both
findings came from the fuzzer, and both sat in a cell the sweep suite structurally could not
reach. Each now has a dedicated axis, in `scripts/sweep.sh` as **report-only** (ground rule 4 —
a new axis blocks only once green, or once every divergence it surfaces is catalogued).

- **`sweep_unknown_seq`** (§5.2 / CORELIB_PLAN §4.9), 25 vectors over the root and every
  struct scope. `sweep_framing` places unknown ids only at scalar / fixlen / array wire types,
  so an unknown id opened as a **sequence with children** — the "skip the whole subtree" half
  of the rule — was never swept. 14/25 red on **F-0044** (generator#268), camp {rust-std,
  rust-nostd, java, csharp, zig}, exactly the catalogued one.
- **`sweep_repeated_elem`** (§7.4 × §5.1), 17 vectors over all three wrappers.
  `sweep_repeated_id` repeats *field* ids and re-opens wrappers, but never an **element id
  inside one wrapper opening** — §5.1 is explicit that an element id *is* a field id in the
  wrapper scope, so the gap was in the model, not the spec. 8/17 red on **F-0048**
  (generator#273), rust-nostd alone.

*Both axes discriminate, which is the point of building them rather than re-filing the
reproducers.* `sweep_repeated_elem`'s `empty_then_value` vector **passes** — an appending
decoder gets that one order right by accident, so a suite built only from F-0048's original
shape would have proved nothing — and `struct_array` (id 202) passes throughout, confining
F-0048 to the leaf-element wrappers. `sweep_unknown_seq`'s two collide-over-value vectors are
sharper than F-0044's own reproducer: by establishing the real field *before* the unknown
sequence, they show the leaked child **overwriting a live value** rather than landing in an
empty slot.

*Pattern worth naming.* Both gaps are of one kind: an axis existed for the rule, and the
position model did not reach the place the rule also applies. §7.4 was swept at field
positions but not element positions; unknown ids were swept at value wire types but not at
sequences. Neither needed a new normative reading — only a wider enumeration. That is the
cheapest class of coverage bug to fix and the most expensive to find by fuzzing, which is
exactly the trade these axes exist to change.

**F-0031 re-checked 2026-08-02 — the corelib fix was fine; two thirds of the finding was our
own measurement apparatus.** Asked to verify F-0031 against the corelibs before filing it. The
round-trip oracle is green on all 13 — the §6.5 raw-bytes path works family-wide — so the
finding lived entirely in the materialized oracle, where `go`, `typescript` and `dart` still
emitted `7fc00001` for an fp32 signaling NaN. Attribution in `FINDINGS.md` read "corelib-py +
corelib-ts + corelib-dart; corelib-only". It was wrong on all three counts.

*`go` — our driver.* `drivers/go/driver.go` read the leaf through `reflect.Value.Float()`,
which returns `float64`: reflect widens a `float32` field, and `fp32 → fp64` widening sets the
quiet bit. Isolated with a standalone Go program — `reflect .Float()` yields `7fc00001`,
`.Interface().(float32)` yields `7f800001`. corelib-go and the generated code hold the value in
a native `float32` end-to-end, which is precisely why the round-trip oracle never saw it. Go is
a native-`fp32` target and needs no raw channel at all (§6.5); we introduced the widening.

*`typescript` — our driver.* The walker repacked the widened double through `setFloat32` — the
one thing §6.5 names as forbidden — while the generated `Probe` already exposed the wire bytes
publicly as `f32Fp32Raw` and the round-trip path already re-encoded from them. Fixed by
threading the sibling raw field through the descriptor walk, scalar and array alike.

*`dart` — half ours, half real.* The **array** position was ours: a decoded fp32 array is a
`Float32List`, whose byte buffer holds the untouched wire bits, but the walker read elements
out as doubles. Fixed. The **scalar** position is not fixable from our side — the generated
bits sit in a library-private `int? _f32Fp32Bits` with no accessor, reachable only by the
type's own `marshal`. Split out as **F-0049 / G-0033** ([generator#275](https://github.com/sofa-buffers/generator/issues/275)) against the dart backend; the ts
backend, same language class and same corelib support, exposes the analogous field publicly.

*Result.* F-0031 is closed and produced **no upstream issue** — correctly. corelib-py, -ts and
-dart had all shipped their §6.5 work. **Filing it as catalogued would have been the F-0008
mistake three times over**, and the only reason it did not happen is that the attribution was
re-derived from source rather than trusted. The standing rule this reinforces: a divergence
seen through only *one* oracle deserves a check of whether the oracle itself is the defect,
before anything is filed.

*Coverage gap found on the way.* §6.5 requires bit-exactness "at **every** `fp32` position: a
**scalar** `fp32` (§4.6) **and** each element of an **`fp32` array** (§4.8)" — we had a vector
only for the scalar. `arr_fp32_nan_bits` now covers the array position (green on all 13,
including dart), which is also what pins F-0049 to the scalar field's *visibility* rather than
to Dart's float model.

**Doc audit 2026-08-02 — F-0010 and the §3/§5.1 trim/pad item were stale, not open.** Reviewing
the open-findings list surfaced a `docs/TODO.md` item asserting *"the family still ships
trim-on-encode / fill-on-decode"* with the §3/§5.1 gates *"expected red until the family
converges"*. Neither is true, and had not been for some time — the item was written when the
rollback was pending and never re-checked once it landed.

*What is actually the case.* `_trim_tail` / `_pad_to` are absent from every backend;
`corpus/conformance/b_array_*` are green. `[1,2,3,0,0]` re-encodes to
`a606 0305010203 0000 07` and `[1,2,3]` to `a606 0303010203 07`, each byte-identical to its
input — two distinct values, which is exactly documentation#31's capacity rule. The second half
of the item (corelib-c-cpp for F-0036) was equally stale: resolved in sofabgen 0.21.0 and
verified 2026-07-29, and `c` still round-trips all three F-0036 reproducers byte-identically.
Neither of the two upstream issues the item said were "still to file" is needed.

*Method worth keeping.* Both were verified on the **value**, by reading c / go / rust-nostd out
individually (C object API, heap profile, fixed-capacity profile), not on the differential's
0-divergences alone. Crucible's oracle is *disagreement*, so a family-wide wrong answer is
structurally invisible to it — "all 13 agree" is not evidence that the 13 are right. That
distinction is the whole reason a green gate did not settle this question either way.

*Third correction, the worst of the three.* `corpus/conformance/README.md` — which
`ARCHITECTURE.md` names as the owner of what those vectors assert — documented a file
`b_array_trailing_defaults_noncanonical.bin` that does not exist, and described the **old**
trim rule. The vector on disk is `b_array_trailing_defaults_kept.bin` and asserts the
**opposite**. The file was re-pointed at #31's rule on 2026-07-28 and its own README was never
updated, so the single source of truth for that gate stated the inverse of what the gate checks.

**Partial bump 2026-08-02 — corelib-c-cpp + corelib-rs-no-std refactors, and F-0038 closes.**
Only two corelibs had moved since the 2026-08-01 bump, both with footprint work: corelib-c-cpp
`d020545 → 17f9a8e` (*"collapse the repeated per-type dispatch in the object and stream paths"*,
265 lines churned in `object.c`, plus `ostream.c`/`istream.c`) and corelib-rs-no-std
`83626e4 → c2a733c` (*"shrink the decoder state to <=32 B"*, `istream.rs` rebuilt and `varint.rs`
largely absorbed). Both are green upstream, 30/30 checks each.

*Decision: bump the generator with them, not separately.* `bootstrap.sh` refuses to leave a
stale toolchain, so refreshing the two corelibs also moved sofabgen
`0.0.0-20260801075630-e8c784163810 → 0.0.0-20260801200345-619ec3c5c04b`. That is three moving
variables at once, which is normally worth avoiding — but the alternative (pinning the old
generator) would have compared corelibs from today against codegen from yesterday, and the
script's own header argues that mix produces divergences that are artifacts of the mix. Taken
deliberately, and the attribution below is unambiguous anyway because the corelib changes
produced *no* behavioral delta at all.

*Closed.* **F-0038** — the last one. Its dart residual (**G-0025**,
[generator#265](https://github.com/sofa-buffers/generator/issues/265), filed 2026-08-01) was
fixed the same day by [generator#269](https://github.com/sofa-buffers/generator/pull/269) and
rode in on the generator bump above; the issue auto-closed at 20:03 UTC. The fix is the shape
the issue asked for — the resolve-then-leave override emitted unconditionally, as
generator#258 already did for java/csharp — and it deliberately left corelib-dart's validating
`onStringBytes` default alone, which is the correct call: a hand-written visitor carries no
schema, so the id-decides knowledge exists only in generated code. That is the same
codegen-vs-corelib split CLAUDE.md's triage table encodes, and it held on the first try here.
All five vectors promoted into `corpus/regression/` (112 → 117, green). **G-0024 is now fully
resolved too** — F-0038 went six impls → one → none.

*The two corelib refactors changed no observable behavior.* All eight replay gates green
(1141 sweep vectors, 106-input materialized oracle at 0/106 anchor mismatches), no
ASan/UBSan/panic output anywhere, and a re-cluster of the unchanged 5306-input corpus gives
**17 → 15 clusters** with every survivor mapping one-to-one onto a catalogued finding at the
same camps and counts. The two clusters that vanished are exactly F-0038's; the 35 inputs of
the larger folded into the benign java soft-value cluster (1965 → 2000). For rewrites of this
size that is the intended result, but note what it does *not* cover: the footprint claims
themselves (host x86-64 instrumented builds are the opposite configuration), limit mode
(its roster excludes `c`, `cpp-c-cpp` and `rust-nostd`), and anything new — this was replay,
not search.

*Unmoved, informatively.* The `rust-nostd`-only `buffer_full` cluster (8 inputs, still the one
untriaged item from the 2026-08-01 round) survived a rewrite of the very state layout that was
the most plausible cause of a capacity bound shifting. That weakly favours reading it as a
deliberate fixed-capacity bound legal under CORELIB_PLAN §6 rather than a finding, but it is
still undecided.

**Triage 2026-08-02 (same day, later) — that cluster is F-0048, and the "unmoved" reading was
wrong.** Minimized 305 B → 11 B. It is not a capacity bound and never was: the no-std backend's
wrapper-array **element** sink appends where every sibling sink replaces (generated
`message.rs` 452 `string_array`, 475 `blob_array`, neither preceded by a `clear()`), so
MESSAGE_SPEC §7.4 last-wins is violated, and the capacity guard sitting on those lines —
`if _e.len() != _s.len()`, which presumes an empty destination — then misfires into
`Error::BufferFull` on **any** duplicate element id at **any** size. `r1` accumulates 4 bytes
into a `String<64>` and still rejects.

*Decision: codegen, filed as [generator#273](https://github.com/sofa-buffers/generator/issues/273) (G-0032), corelib untouched.* Two independent signals, both from
CLAUDE.md's triage rules: **rust-std gets the identical position right**
(`string_array[id] = _s`) — a split between two profiles of one language, which heuristic 3
says indicts the generated container — and the corelib is schema-agnostic, having delivered
every byte faithfully through `(id, total, offset, chunk)`. Chunk assembly is already done
upstream in `acc`, so each sink arm receives a complete value and appending is never right
there.

*Worth recording as a reasoning error, not just a result.* The earlier entry read "unchanged by
a rewrite of the state layout" as evidence for a deliberate bound. The inference was backwards:
the rewrite changed nothing because the defect was never in the corelib at all. A corelib-side
null result is evidence about the corelib, not about whether a finding exists — the same trap
F-0008 fell into when it was first filed against corelib-c-cpp#84.

*This closes the 2026-08-01 round.* All 17 clusters are attributed: 13 to catalogued findings,
one legal (documentation#33), one a product of two others, and this one new. A second §7.4
blind spot in the sweep suite is now on `docs/TODO.md` — F-0019 covers a repeated *sequence*
id and a repeated array *wrapper* id, but never a repeated **element** id inside a wrapper.

**Family bump 2026-08-01 — corelibs 0.10.0 + sofabgen 0.22.0: two findings closed, one
narrowed, one reshaped, one found.** Bootstrapped with the defaults on `main` (the stale POC
branches are gone, so branch-tracking no longer needs the `FAMILY_BRANCH=main` override the
2026-07-29 entry called for). All 11 corelibs land exactly on their `v0.10.0` tag; the
generator binary reports the CI pseudo-version `0.0.0-20260801075630-e8c784163810`, whose
commit is **byte-identical to the `v0.22.0` tag** — the artifact was built 16 min before the
tag was cut. All eight replay gates green, including both report-only passes.

*Closed.* **F-0039** (generator#254 + #259) and **F-0042** (all seven corelib issues + #259)
converge on all 13; their reproducers are promoted into `corpus/regression/` (103 → 112
inputs). Both had forced the same carve-out — the two `ARR_fp*`-vs-`ARR_fp*` cells in
`wiretype_sweep` — which is now retired (361 → 363 vectors, green).

*Two stale carve-outs retired with them.* F-0035/F-0036 (resolved in sofabgen 0.21.0) had
kept the whole `struct_array` **element** position out of `sweep_empty_frame`; it rejoins the
axis at 34 → 39 vectors, including two vectors for the canonical interior-gap and
trailing-default element forms that had existed only as comments.

*Narrowed.* **F-0038** is six impls down to one. The residual is `dart` and it is **codegen**:
corelib-dart shipped its half and documents (`lib/src/decoder.dart:55-60`) that generated code
must resolve the destination before validating, but the dart backend emits no `onStringBytes`
override for a **string-free scope**, so those visitors inherit the validating default at
`decoder.dart:77`. generator#258 fixed exactly this for java/csharp — `Probe.java:337` emits
`default: return;` before a byte is buffered — and was never applied to dart.

*Reshaped.* **F-0033** stopped being a spec hole: documentation#32 (`70f9123`) makes the
declared integer width a normative validity bound, so over-width is INVALID and generated
code must enforce it. The family split collapsed 3-way → 2-way (`c` + `cpp-c-cpp` correct,
11 accept) and the mask-vs-keep disagreement among the accepters closed — 33 divergences, all
`verdict`, zero `accept_value`. sofabgen 0.22.0 predates the clause, so no backend implements
it yet.

*Found — **F-0043**.* Re-enabling F-0032's carve-out (F-0032 itself is genuinely fixed) grew
`sweep_malform_truncate` 43 → 96 vectors and exposed the **boundary offset** the carve-out had
been hiding: a schema-bound violation is not decided at the length/element **word** but only
once payload bytes arrive, so a message truncated exactly at that word is `I` where §5.2
requires `R`. Two forms — an off-by-one (rust×2, java, csharp, zig; plus go/dart on the
wrapper rows) and python deferring a blob's `maxlen` to payload completion at every offset.
All 13 agree on the untruncated controls, which is what makes it an ordering defect rather
than a detection one. The carve-out stays, re-pointed from F-0032 to F-0043.

*Filed upstream, same day.* All three open findings attributable to codegen went to `generator`,
one issue each: **F-0038**'s dart residual → [#265](https://github.com/sofa-buffers/generator/issues/265)
(**G-0025**), **F-0033**'s width bound → [#266](https://github.com/sofa-buffers/generator/issues/266)
(**G-0026**), **F-0043**'s check ordering → [#267](https://github.com/sofa-buffers/generator/issues/267)
(**G-0027**). Each carries the per-backend split table, the isolate bytes, the controls that pin the
axis, and a `file:line` citation for the shape being asked for — for #265 that is the java backend's
own resolve-then-leave (`Probe.java:337`) against the five dart visitors that inherit the validating
default instead. F-0031 stays unfiled: it is corelib-side and its camp moved under us.

*Then re-validated against the spec at `70f9123`, and each issue carries the result as a comment.*
All citations held; two gained something. **#266**: §7.1's worked example turns out to be literally
our reproducer (*"a `u8` field whose value arrives as `16383`"*), and §1 also binds an `enum` by its
signed 32-bit range — which the issue's original "asked for" understated, so the enum destinations
were added (`bitfield` is deliberately not claimed). **#267**: §7.3's closing paragraph mandates
`INCOMPLETE`-not-`INVALID` for a truncation *between* a fixlen array's count and its `fixlen_word`
(CORELIB_PLAN §4.8) and reads as a counter-argument until one checks the vectors — none are in that
case, since `over_len_*` are scalar fixlen and the `*_array_over_id` rows are sequence-wrapped, not
the §4.8 count-prefixed form. Pre-empted in the issue rather than left for a maintainer to raise.
*Generalizes: re-read the clause at the tip **before** filing, not after — the spec had moved five
days earlier and the deciding sentence for the newest finding sat in a section none of us re-opened.*

*Decision: a finding is not closed until **both** oracles agree.* **F-0031** looked resolved —
`CORPUS=findings/F-0031 ./scripts/run.sh` is green on all 13, the sNaN bits survive
decode+re-encode. Putting `f32_snan` back into the structured green corpus then failed
`materialize.sh`: `c: f7f800001` vs **go, typescript, dart: `f7fc00001`**. Element access is
where the double conversion happens, so the round-trip oracle is blind to it, and the camp had
also changed under us (py-cython left, go joined). The vector stays out of `gen.py` and the
finding stays open, rescoped to the materialized oracle. Generalizes: for any value-shape
finding, re-verification means `run.sh` **and** `materialize.sh`.

**Parallel fix campaign 2026-07-29 — four clusters, two findings closed.** With the family on
`main`, the 12 real open corelib issues were six root causes, not twelve bugs, so they were worked
as clusters: one shared branch name per cluster in every affected repo, one worker per repo, and
`bootstrap.sh`'s `FAMILY_BRANCH` as the join — every fix in a cluster differentially tested
*together* before any of them merged.

*Closed.* **F-0040** (corelib-c-cpp#118) — the varint width guard now also fires on exit, so a
tenth continuation byte is INVALID instead of INCOMPLETE. **F-0041** (corelib-c-cpp#119 +
corelib-cpp#59) — the over-index reject is gated on the §7.3 wire-type test in both, via two
different edits for the two proximate causes. Both waves passed the join (split closed, controls
held, regression green) before merge; their isolates are promoted into `corpus/regression/`
(97 → 103 inputs).

*Blocked on codegen, deliberately.* **F-0038**'s corelib halves (corelib-go#59, corelib-dart#24)
and **F-0042**'s seven (go#60, java#54, cs#46, dart#25, rs#41, rs-no-std#61, zig#28) are complete
and green in their own suites, but neither closes its split alone — both are two-half changes, and
F-0042 is an outright ABI break (`ArrayKind.Fixlen` → `Fp32`/`Fp64`) that generated code cannot
even compile against until sofabgen matches. Filed as generator#257 (Class A merged as #258; the
go/dart backends remain) and **generator#259**. Every PR carries the measured evidence and a
"do not merge alone" note.

*The campaign's most valuable output was not a fix.* Four workers **stopped instead of fixing** and
proved that four of the six F-0038 issues filed that morning were misfiled: corelib-rs, -rs-no-std,
-java and -cs carry no UTF-8 code on the decode path at all — established statically *and* by
feeding the isolates through the bare corelib with a no-op visitor. That is the F-0008 misfiling
CLAUDE.md warns about, caught before a maintainer spent time on it. The four issues are closed and
redirected; `results/FINDINGS.md`'s "corelib-only" attribution is corrected. Two process rules came
out of it and are now in the runbook: the verify agent works in its own clone (it had switched the
live checkout's branch *and* `vendor/`), and a cluster argument must fail loudly rather than
default — a mistyped one silently re-ran C1 for a full wave.

**Family bump 2026-07-29 — first fully-merged sparse-array family, re-verified end to end.**
The POC branch landed everywhere: documentation `8087f1d` (PR #29 + #31), all 11 corelibs
merged to `main` and released **0.9.0**, generator `0c424ac` (#244) released **sofabgen
0.21.0**. Bootstrapped with `FAMILY_BRANCH=main SOFABGEN_VERSION=v0.21.0`; the stale
`poc/omit-all-default-sequences` branches still exist in every corelib repo (tree-identical
to `main`, 1 behind), so the default branch-tracking would have vendored refs that no longer
move — `FAMILY_BRANCH=main` is required until they are deleted.

*Decision — the materialized walkers read the length, never the capacity.* The materialize
gate opened at **1068 divergences** because four Crucible-side walkers iterated a `count: N`
array's capacity: `drivers/c/driver.c`, `drivers/go/driver.go`, and the generated walkers
from `drivers/{zig,dart}/materialize_gen.py`. MESSAGE_SPEC §3 settles it — *"a decoder
materializes exactly the M elements the wire carries … There is no fill-to-N"* — and the C
walker's wrapper branch additionally trimmed trailing defaults, which §2's last-element rule
forbids. Fixed on the spec's terms, not by matching the majority: the gate is green **and**
the C anchor now matches `engine/structured/materialize.py` 0/106, and that reference is
derived from the spec. Generated code was never at fault — every backend already exposes a
length (C's `ARRAY_SIZED` descriptor, Zig's `FixedArray(T,N).slice()`, native containers
elsewhere). `oracle/materialized.md`'s scope note was updated from "family has not converged"
to converged.

*Gates.* seeds / conformance / structured / regression / crashes / union / structured-union /
limits / materialize all green; 7 of 8 sweep axes green **including `sweep_empty_frame`** (the
§2 omission axis). `corpus/interesting` (1121 inputs) reduced from 70 clusters to **12**, no
new crash, and the previously dominant F-0012 class is gone.

*Findings.* **F-0035, F-0036, F-0037 resolved** — every reproducer agrees, generator#247/#248/
#249 closed. F-0036 was checked beyond agreement, since its direction had been inverted by
documentation#31: all three isolates round-trip byte-identically, i.e. the family converged on
the spec-correct side (the trailing empty frame is kept). **F-0031 is down to `typescript`
alone**; generator#235 stays open (PR #251 closed unmerged). Three new findings, all filed:
**F-0039** (java/cs resize a declared array from a §7.3-skipped header — generator#254,
G-0023), **F-0040** (corelib-c-cpp defers the overlong-varint verdict to INCOMPLETE —
corelib-c-cpp#116), **F-0041** (over-index reject ordered before the §7.3 skip —
corelib-c-cpp#117 + corelib-cpp#58). **F-0038 filed** at last against all six corelibs
(corelib-go#57, corelib-rs#39, corelib-rs-no-std#59, corelib-java#52, corelib-cs#44,
corelib-dart#22). F-0041 carries an explicit caveat into both issues: §7.3 argues its
precedence through the fixlen *count word*, so if the maintainers scope the clause there, the
fix belongs in `documentation` instead — the 11-vs-2 split is stated, not assumed.

*Decision — generator#232 closed as misfiled, re-filed as seven corelib issues.* It had sat in
the generator repo since 2026-07-25, first as an open spec question ("does the count bound or the
§7.3 subtype win for a fixlen array?") and then as an implementation gap. The question is settled
— CORELIB_PLAN §4.8 — and the answer makes the remaining work impossible to do in the generator:
seven array header hooks either fire before the `fixlen_word` or omit the element subtype, so no
generated guard can express the order. Assigned **F-0042** (it had never had a Crucible id, which
is why nothing in the catalog pointed at it), pinned all six vectors as reproducers, and filed
corelib-go#58, corelib-java#53, corelib-cs#45, corelib-dart#23, corelib-rs-no-std#60 (rows 2+4)
and corelib-rs#40, corelib-zig#27 (row 2 only — their hook already fires past the `fixlen_word`).
Its row 1 turned out to be the same defect as F-0039/generator#254, found independently the same
day from the other side; the two are cross-linked rather than merged, because one is codegen and
fixable today and the other is a corelib hook-signature change.

*Decision — the POC branch is not merged yet, and the sweep axis stays blocking.* With the
family bump verified, crucible#109's own failure is gone (the materialize gate is green in CI),
but `wiretype_sweep` is red on 30 of 332 vectors: F-0039, a defect of the released sofabgen
0.21.0, not of the branch. Three ways out were weighed — demote the axis to report-only, merge
red, or wait. **Waiting won.** A carve-out was explicitly rejected: `oracle/policy.yaml` records
divergences the spec *allows*, and this one it forbids, so parking it there would launder a bug
into a legal difference. Merging red would cost the "main is green" signal every later PR reads.
So the branch stays open until a sofabgen release carries generator#254; then re-run the sweep
and merge. Tracked in `docs/TODO.md`.

*Resolved the same day, and the hold was lifted.* generator#254 and #235 both merged to
generator `main` (`9c71fde`, 06:01). Measured against a source build of it: `wiretype_sweep`
**30 → 2**, and F-0031's fp32 sNaN now round-trips bit-exact on typescript, so that finding is
closed on the driver side too. The two survivors are an fp array meeting a declared fp array of
the other width — both `ArrayKind.FIXLEN`, and the array-header hook carries the kind but not the
subtype, so codegen cannot separate them. That is F-0042's root cause, not a new defect: the
codegen half went as far as codegen can.

*Decision — carve out the two cells, not the axis.* Earlier today a carve-out was rejected for
this same gate, and that judgement stands for what it was aimed at: `oracle/policy.yaml` records
divergences the spec **allows**, and putting a §7.3 violation there would launder a bug into a
legal difference. A sweep-cell exclusion is a different instrument — it asserts nothing about
legality, it names an open finding and carries its own deletion condition, and the repo already
used it for F-0034, F-0036 and F-0037. Restoring coverage made that concrete: the F-0036/F-0037
carve-outs this branch was carrying are now stale (both fixed in 0.21.0), so removing them took
`wiretype_sweep` from 332 to **363** vectors — all green. Net effect of the swap: 31 cells
gained, 2 cells parked with an issue reference. Every CI gate is green: seeds, conformance,
regression, structured, crashes, cross-encode, union, limits, materialize (106×13 → 0, C anchor
0/106) and all eight sweep axes including the union pass.

**Re-verification 2026-07-08** — after bumping **sofabgen → 0.15.1** and all 10
corelibs to latest `main`, drivers rebuilt clean and the seed corpus is green (0
divergences). Replaying the finding reproducers: **F-0002 and F-0005 are fixed**
(upstream PRs merged); **F-0003's crash is fixed but morphed** into a verdict
divergence, now tracked as generator#100 (see below); **F-0001 and F-0004 still
diverge** — expected,
they wait on the still-open epics generator#86 / #85 (the "2 issues still open").

**Toolchain + corelib bump 2026-07-15 — re-verified** — bumped
**sofabgen → 0.16.1** (`tools/sofabgen` rebuilt from generator `v0.16.1`, commit
`3bd1b37`; the vendored binary had been a stale 0.15.2) and re-cloned all 10
corelibs to their `origin/main` tips (real clones now replace the previously
broken vendor symlinks): c-cpp `4274ed6`, cpp `021902c`, cs `532c2f7`, go
`7e32c8c`, java `0a9ea4c`, py `e14e4ba`, rs `b46c1cd`, rs-no-std `84bc895`, ts
`09c1298`, zig `f5f40e6`. All **12 drivers rebuilt clean** on 0.16.1 (one snag: the
Python venv is cached across runs, so it had to be wiped — `rm -rf
drivers/python/build/venv` — to pick up the new corelib-py; the other drivers
regenerate every run). Full re-run results:

- **Seed corpus green** (12 drivers, 0 divergences); **limit mode green** all three
  dimensions.
- ✅ **generator#100 fixed** (commit `ca0fda7`; the F-0003 residual): a clean
  non-truncated over-count (8>5) scalar array now → **all 12 reject** (`R`);
  rust-std/nostd reject with the family (were the lone accepters). F-0003 **fully
  resolved**.
- ✅ **G-0009 / generator#112 fixed** (commit `7899c4b`): the C++ unbounded array is
  now `std::vector`; cpp matches the family on the arr limit vectors and on the old
  repro `03 03 07 08 09` → `[7,8,9]`. **cpp rejoins the `arr` dimension** —
  `scripts/run-limits.sh` updated (the `NO_CPP` hold-out removed) and re-run green.
- ✅ F-0001 still green (all `I`); F-0002 still clean (no left-shift UBSan).
- ⏳ F-0004 still 4-way (raw/empty/U+FFFD/reject) — expected, the
  `SOFAB_STRICT_UTF8` epic generator#85 is still open.
- 🆕 **F-0006 (new):** the corelib-py `main`@`e14e4ba` (un-eager array allocation)
  made corelib-py return `I` instead of `R` on a **truncated fixlen fp32/fp64 with a
  wrong declared length** (e.g. `56 0a 59`) — the sole `I`-vs-`R` outlier vs 10
  impls. Root-caused (fp width check deferred until payload read) and filed
  **[corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)**.
  (Also in the bump: generator#113/#103/#104 — no new divergence from those on the
  current corpus.)

**Second re-pull + re-run 2026-07-15 (newer `main` tips)** — pulled all corelibs
again; the tips advanced to: c-cpp `d01f109`, cpp `a3d0717`, cs `0c619e8`, go
`f28d2ee`, java `4f73558`, py `0e15785`, rs `03b44f6`, rs-no-std `67e1632`, ts
`8a6210c`, **zig `0f861e4`**. Re-ran the box (wiping the Python venv + Java jar to
pick up the moved corelibs):

- ✅ **F-0006 FIXED** — corelib-py `main` now validates fp32/fp64 fixed width at the
  FIXLEN header (decoder.py L338-341), before the payload read, so a truncated
  wrong-width fp is `R` (INVALID), not `I`. Re-verified: `56 0a 59` / `56 02 38` →
  **all drivers `R`**. **[corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)
  closed.** F-0007's py slice collapsed; the precedence family now narrows to the
  **C corelib only** (c + cpp-c-cpp still `I` on `56 0a 09` at small declared lengths).
- ✅ Seed differential green (11 drivers); limit mode green all dimensions (cpp in
  arr); F-0001 all `I`; generator#100 all `R`; F-0002 clean; F-0004 unchanged 4-way
  (#85).
- ⚠️ **zig held out — build broken.** corelib-zig `0f861e4` adopted the finish-less
  `decode → Error!Status` API (INCOMPLETE is a `Status`, not `error.Incomplete`).
  sofabgen 0.16.1's zig backend still generates `try sofab.decode(data,&v)` (discards
  the `Status`) and `drivers/zig/driver.zig` still switches on `error.Incomplete` →
  compile error. This is the **zig analogue of G-0008** (status surfacing): the
  corelib moved correctly to §7, the generator + Crucible driver must catch up.
  Tracked as **G-0010** ([generator#120](https://github.com/sofa-buffers/generator/issues/120)) + a driver TODO. Until fixed, `run.sh`
  aborts at the zig build; the box was run over the other 11 drivers.

**Third re-run 2026-07-15 — sofabgen 0.16.2, zig restored, full 12/12 green.**
Bumped **sofabgen 0.16.1 → 0.16.2** (`tools/sofabgen` rebuilt from generator
`v0.16.2` = commit `976e06e`; 0.16.2 is a focused release — **only** the zig fix
`26f1f4c` "zig: bind feed(chunk)→Status in generated decode()", closing G-0010 /
[generator#120](https://github.com/sofa-buffers/generator/issues/120), plus the
version bump). Corelib tips unchanged from the second re-run. The generated
`message.zig` `decode` now surfaces the terminal `Status`, mapping `.incomplete` →
`error.IncompleteMessage`; the Crucible **`drivers/zig/driver.zig`** was updated to
match (`error.Incomplete` → `error.IncompleteMessage`, two sites — the driver half
of G-0010). Full re-run:

- ✅ **zig builds and rejoins the box.** Seed differential **12/12 green**; limit
  mode green all dimensions (9 heap drivers incl zig, cpp in arr).
- ✅ **F-0001 all 12 `I`** (zig now emits `I` on `80`, confirming the finish-less
  §7 model end-to-end); **F-0006 all 12 `R`**; **generator#100 all 12 `R`**; G-0009
  holds. **F-0004** unchanged 4-way (#85). **F-0007** — `56 0a 09` (fp64) / `56 02 10`
  (fp32) → only **c + cpp-c-cpp** emit `I` (zig correctly `R`); the C corelib is the
  sole precedence outlier. **Root-caused and filed
  [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82)**: the
  C istream validates a fixlen fp's declared length against the destination buffer
  (`length > target_len`), not the exact width (4/8), so a wrong-width *truncated* fp
  is `I` not `R` — the direct analogue of the closed corelib-py#38.
- **G-0010 resolved** (generator side in 0.16.2 + the Crucible driver.zig fix).

**Fourth re-run 2026-07-15 — sofabgen 0.17.0, corelibs@main, full 12/12 green.**
Bumped **sofabgen 0.16.2 → 0.17.0** (`eef4d6a`; a cosmetic release — only #123
"render metadata as clean doc comments", no wire behavior) and re-pulled all
corelibs to their `main` tips. Wiped the Python venv + Java jar (corelib-java moved)
so the caches picked up the new corelibs. Results:

- **Seed 12/12 green**; **limit mode green** all dimensions.
- ✅ **F-0007 RESOLVED** — corelib-c-cpp `635966d` "reject wrong-width fixlen
  fp32/fp64 as INVALID (#82)(#83)"; `56 0a 09` / `56 02 10` → **all 12 `R`**;
  [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82)
  **closed**. The whole INVALID-vs-INCOMPLETE precedence family is now convergent
  (F-0006 + F-0007 both fixed).
- ✅ F-0001 all `I`; F-0002 clean; F-0006 all `R`; generator#100 all `R`; G-0009
  holds. ⏳ F-0004 unchanged 4-way (#85).
- 🆕 **F-0008 (new): a generated fixed-capacity C++ DoS hang** — a 4-byte input
  `c6 0c c6 07` (a nested `SEQUENCE_START` inside the `string_array` field) makes the
  generated `_FixedStrSeq` fill **loop forever**; `c`/`cpp`/`go`/`rust` all return `I`
  instantly. Found by the **structure-aware mutator** and localized by the new
  comparator **per-driver timeout** (the whole pipeline working end to end).
  **Correction:** first mis-filed against corelib-c-cpp (the differential symptom was
  `cpp-c-cpp`-only); the corelib maintainer showed `sofab_istream_feed` terminates
  ([corelib-c-cpp#84](https://github.com/sofa-buffers/corelib-c-cpp/issues/84) closed,
  [crucible#16](https://github.com/sofa-buffers/crucible/issues/16)). Tracing the
  generated code found the real bug: `_FixedStrSeq`/`_FixedBlobSeq` do
  `while (out->size() <= id) out->emplace_back()`, but the fixed-capacity
  `InlineVector::emplace_back` no-ops when full, so `id ≥ N` spins. Re-targeted to
  **codegen: [generator#126](https://github.com/sofa-buffers/generator/issues/126)**
  (G-0011).

Net open items: **F-0004** (spec §8 / gen#85) and **F-0008** (generator#126 / G-0011).

**Fifth re-run 2026-07-16 — sofabgen 0.17.1: F-0008 + F-0009 verified FIXED.**
Bumped `tools/sofabgen` to **0.17.1** (`fa909c7`), which lands both codegen fixes the
mutator + cross-encode oracle found this session: **generator#126** (F-0008, commit
`483c281` — bounded the fixed-capacity string/blob-seq fill loop) and **generator#128**
(F-0009, commit `25d5853` — sized blob descriptor). Rebuilt + re-ran the full box:
- ✅ **F-0008 fixed** — `c6 0c c6 07` → `I` (terminates, no hang) on `cpp-c-cpp`.
- ✅ **F-0009 fixed** — short blobs round-trip in `c`, matching the family; the
  sub-`maxlen` vectors rejoined the green cross-encode gate (`corpus/structured/`, now
  **52 inputs, 0 divergences**).
- ✅ Seed + limit-mode gates green. **crucible#16** (the F-0008 dispute) closed.

Net open now: **F-0004** only (spec §8 / gen#85). All Crucible-found codegen bugs
(G-0001…G-0012) are resolved.

**Sixth re-run 2026-07-16 — corelib bump (`main` tips), full box green, no regression.**
Pulled all 10 corelibs from origin/main; four advanced — **corelib-c-cpp** `635966d→98ab841`
(docs), **corelib-cpp** `9fd4f78→24ee297` (docs), **corelib-rs** `03b44f6→7b453d8` (docs),
**corelib-rs-no-std** `3e4a69f→29ddf42` (one real change: `perf(size)` varint push
outlining, #44). sofabgen unchanged (0.17.1). Full box:
- ✅ **Differential** (seeds) 6×12, **cross-encode** 69×12, **union** 11×12, **limit
  mode** (arr/str/blb) 9-driver roster — **all 0 divergences**.
- ✅ Resolved reproducers (F-0002/05/06/07/09) still all-agree.
- The two reproducer-level splits that appear — F-0003 `array_overflow` (rust `I` vs
  family `R`) and F-0008 `hang_min`/`hang_orig` (py `R usage` vs family `I`) — are the
  **INVALID-vs-INCOMPLETE precedence** spec-hole (documentation#15) on the *original*
  crash/hang reproducers, **not regressions**: proven by reverting corelib-rs/-rs-no-std
  to pre-pull commits (identical `I`), and corelib-py was untouched by the pull. Recorded
  as residual notes in the F-0003/F-0008 NOTES.
- F-0001/F-0004/F-0010 reproducers show their documented spec-hole behavior unchanged.

**Seventh re-run 2026-07-16 — sofabgen 0.17.2: F-0010 fixed for 11/12, NEW go regression (F-0011).**
Built sofabgen from generator `v0.17.2` (`d8d35c2`) and pulled corelibs — only
**corelib-c-cpp** advanced (`98ab841→390f237`, carries corelib-c-cpp#87, the C-path
half of the F-0010 fix). 0.17.2 lands **generator#136** (my F-0010 issue, PR #137):
- ✅ **F-0010 resolved for the trim/pad question, all 12 backends** — R1/R2 reproducers
  (`u32_count3`, `i16_count1`) now round-trip to the canonical **count 3 / count 1**; the
  systems camp trims the trailing default run (C via corelib-c-cpp#87).
- ✅ **Union** (11×12) and **limit mode** (dynamic arrays, 9-driver roster) **green**.
- ❌ **Seed gate (5/6) + entire cross-encode corpus RED — go only.** The same 0.17.2 go
  changeset (`684656d`) over-corrected: an **all-default `count:N` array field is emitted
  explicitly** (`<hdr> 00`) instead of omitted (§2). New finding **F-0011**, filed
  **[generator#139](https://github.com/sofa-buffers/generator/issues/139)**. go-only,
  `count:N`-array-specific (union + dynamic-array limit mode stay green; go's under-count
  *trim* is itself correct). **Staying on 0.17.2** (F-0010 value) with the gates red-on-go
  until generator#139 lands.

**Eighth re-run 2026-07-16 — sofabgen 0.17.3: F-0011 fixed, FULL BOX GREEN.**
Built sofabgen from generator `v0.17.3` (`0bc18e1`); corelibs unchanged (pure go codegen
fix). 0.17.3 lands **generator#139** (commit `0713b94`, "fix(go): omit an all-default
count:N array instead of emitting it"):
- ✅ **F-0011 resolved** — `empty_arrays` → all 12 omit the all-default arrays
  (`A 5607a606560707c60c07`); `undercount_siblings` → all 12 agree.
- ✅ **Full box green:** differential (seeds) 6×12, cross-encode 69×12, union 11×12, limit
  mode (arr/str/blb) 9-driver roster — **all 0 divergences**.
- ✅ **F-0010 stays canonical** (count 3 / count 1 on all 12); compliance spot-checks
  (Clause A fp-precedence, §7 over-count) all `R`.
The 0.17.2→0.17.3 round-trip (F-0010 fix → go regression → go fix) closed within the day.

**Fuzzer round 2026-07-16 (sofabgen 0.17.3) — 1 new finding, no crash.** Ran the C
pacemaker (`scripts/fuzz.sh`, `FUZZ_TIME=180`: 2.49M execs @ 13.7k/s, **no crashes**,
coverage saturated, +306 corpus units → 43.3k `corpus/interesting`). Clustered a 1-in-10
sample (4326 inputs → 70 clusters). Dominant class (~66%): **F-0012** — corelib-ts's
unknown-field **skip path** reports `INCOMPLETE` where the family reports `INVALID` for a
malformed fixlen word + truncation (§5.2 precedence), filed **[corelib-ts#49](https://github.com/sofa-buffers/corelib-ts/issues/49)**.
The rest is the precedence family (other impls' skip paths lenient/eager — the C family
shows the same gap in cluster 5, follow-up) + **F-0004** (UTF-8) + soft reject_class /
incomplete_value. Green gates unaffected (all malformed-input edge cases). See CLUSTERS.md.

**Ninth change 2026-07-16 — regression corpus committed + CI wired; F-0013 found while
building it.** Built `corpus/regression/` (the standing TODO): the reproducers of all
nine resolved findings, **18 inputs × 12 drivers, 0 divergences**, wired into
`replay.yml` on every push/PR — so a bump that reintroduces a fixed bug fails CI rather
than waiting to be spotted in a manual re-run (F-0011 was caught only because someone was
looking). Also wired the **union suite** into `replay.yml`.

- **The gate admits a reproducer only when it is green *for the reason the finding is
  about*.** F-0003's `array_overflow.bin` and F-0008's `hang_min.bin` are fixed but
  **contaminated** — each tests its own axis *and* truncation, so both still split the
  family on the open precedence hole (documentation#15). They stay in `findings/`; the
  gate gets **clean isolates** instead (`engine/structured/isolates.py`, built on
  `gen.py`'s primitives).
- 🆕 **F-0013 (new): an over-index `string_array` element is kept (heap) vs dropped
  (fixed-capacity)** — found by writing the *clean* F-0008 isolate (over-index **without**
  truncation), which the contaminated original could not express. `c6 0c c2 07 0a 78 07`
  (7 B, element index 120 ≥ the schema's `count: 5`): all 12 **accept**, but c /
  cpp-c-cpp / rust-nostd drop the element while the 9 heap profiles keep it — a pure
  value split, invisible to any accept/reject oracle. Root cause **codegen G-0013**: the
  heap backends emit an unbounded container + `while (len <= id) push(default)` fill, so
  the schema `count` is enforced nowhere. Same fill is a **memory-amplification DoS**:
  9 B at index 2,000,000 → cpp **226 MB** / go **122 MB** vs ~8 MB fixed. **The half of
  F-0008 that generator#126 left unfixed.** Filed [generator#142](https://github.com/sofa-buffers/generator/issues/142) (2026-07-17; spec target = reject per §7).
- Harness fix: `comparator.py`'s `read_corpus` now skips `*.md` + dotfiles, so a corpus
  dir can carry a README (previously *every* file was an input, incl. a `.gitkeep`).

**Tenth change 2026-07-17 — corelib bump: F-0012 (ts-skip) FIXED.** Pulled corelibs;
`corelib-ts` advanced to `0279378` ("fix(decode): validate fixlen word in the cursor skip
path (§5.2 precedence)") — the corelib-ts#49 fix for the fuzzer's F-0012. **Re-verified:**
`aa7e79` / `5df35d07` → TS now `R invalid_msg` (was `I`), aligned with the family; the
valid-skip controls stay `A`/`I`. (cs/go moved on docs/deps/test only.) PR #39 (the F-0012
write-up) had already merged; the overindex finding it collided with was renumbered
**F-0012 → F-0013**.

**Eleventh change 2026-07-17 — full box green; 1 h fuzzer round; F-0001 closed, F-0014 opened.**
Box (all 5 suites incl. the new regression gate) **green** on current tips. Ran the pacemaker
for **1 hour** (143 M execs @ 39.9k/s): **no new crash**, coverage saturated (cov 566, all
REDUCE), corpus → 44.1k. Results:
- ✅ **corelib-ts#49's effect measured:** the sample divergence rate fell **86% → 32%** and the
  dominant cluster (TS skip-path precedence, 66%) is **gone**.
- ✅ **F-0001 marked resolved** — its target ("every impl emits `I`") has been met since
  2026-07-13; re-verified. Its NOTES had been badly stale ("still diverging, 7 vs 5",
  2026-07-08). The residual java `incomplete_value` on `I` is the **soft** axis, not F-0001.
- ✅ **F-0004 config audit contributed upstream** ([gen#85 comment](https://github.com/sofa-buffers/generator/issues/85#issuecomment-5000859662)):
  **no corelib exposes the §6.4 opt-in toggle** — go+py validate unconditionally, the other 8
  never do, so 8 of 10 **cannot reach the conformance-ON configuration** §8 requires. That is
  the blocking half of that epic.
- 🆕 **F-0014 (new):** with #49's cluster gone, the residual precedence clusters (149 py / 97
  c-family / 94 ts) turned out to be **one class on the array path** — the `ARRAY_FIXLEN`
  element word isn't (fully) validated at the header. Three minimal isolates, each pinning one
  impl; filed **[corelib-c-cpp#89](https://github.com/sofa-buffers/corelib-c-cpp/issues/89)**,
  **[corelib-py#41](https://github.com/sofa-buffers/corelib-py/issues/41)**,
  **[corelib-ts#51](https://github.com/sofa-buffers/corelib-ts/issues/51)**. The array analogue
  of the fixed F-0006/F-0007/F-0012.
- **F-0013 did not surface** in fuzzing — as expected: it needs a *well-formed* over-index,
  which byte mutation practically never produces (it was found via a structured isolate).

**Twelfth change 2026-07-17 — F-0015 + spec Proposal 3 ADOPTED (ahead of the codegen bump).**
Preparing the regression for an announced sofabgen update reworking array/string/blob
`count`/`maxlen`, the audit asked which of those axes we actually cover — and found the
**`maxlen` axis untested and already divergent**:
- 🆕 **F-0015:** a `string`/`blob` over its schema `maxlen` splits **9-vs-2-vs-1** (9 heap
  profiles accept and keep the over-long value; c/cpp-c-cpp → `invalid_msg`; rust-nostd →
  `buffer_full`). Within `maxlen`: all 12 agree. The three "enforcers" enforce only because
  their fixed buffer cannot hold more — an artifact of the memory model, the F-0010/F-0013
  shape.
- **The spec never defined it.** §7's enforced-bounds enumeration listed only `M > N` and
  element id `≥ N`; MESSAGE_SPEC mentioned `maxlen` 5× but never normatively (§2 filed it
  next to docs/tooling hints; §5.1 used it as a pre-sizing hint "on heap-less profiles");
  CORELIB_PLAN mentioned it **0×**. Two adjacent holes rode along: the unbounded-field
  obligation, and the receiver-side `max_dyn_*` limits — which the generator ships
  (generator#102) and Crucible tests via the `L` verdict, while §6.2 listed only
  format-wide ceilings (`policy.yaml` has flagged that since Phase 1).
- ✅ **Proposal 3 filed *and* adopted the same day** — documentation#19 → **PR
  [documentation#20](https://github.com/sofa-buffers/documentation/pull/20) merged**
  (`49cdee9`; spec now at `85bb0be`). MESSAGE_SPEC §2/§7/**§7.1**/**§7.2** + CORELIB_PLAN
  §6.2/**§6.2.1**/§6.3 (+ the new `LimitExceeded` code). §7.1 is the crux: a declared
  `count`/`maxlen` binds **every target regardless of allocation strategy** — *"MUST NOT
  accept an over-bound value merely because its storage happens to be able to hold it"*.
  Writing the PR also surfaced that §6.3 had **no code** for a limit rejection, making the
  draft's "MUST NOT report as `InvalidMessage`" unimplementable; the PR adds
  `LimitExceeded` and raises (rather than decides) the API-shape question — fourth outcome
  vs error channel. **All three Crucible spec proposals are now adopted** (#15→#17,
  #16→#18, #19→#20).
- **Timing was the point:** the clause landed **before** the codegen bump, so the update
  implements a *defined* rule — the F-0010 order (hole → clause → adoption → codegen) that
  made that one land uniformly. F-0015's four vectors are the **pre-bump baseline**, so the
  update's effect is measurable rather than guessed.

**Thirteenth change 2026-07-17 — sofabgen 0.17.4 + 0.17.5 + corelib fixes: F-0014 & F-0015
RESOLVED, F-0013 half. Regression gate 18 → 25.** Box green throughout.
- ✅ **F-0015 fully resolved** — **0.17.5** (`b0b2832`, "reject over-maxlen strings/blobs as
  INVALID on decode (Option B)"). Measured against this morning's baseline: **9 accept / 2
  `invalid_msg` / 1 `buffer_full` → all 12 `R invalid_msg`**, on all three over-`maxlen`
  vectors; the within-`maxlen` control still accepts on all 12. Both halves landed — the 9
  heap backends enforce `maxlen`, *and* rust-nostd's `buffer_full` became `invalid_msg` (the
  class correction §7.1 implies). **The whole arc closed in one day:** hole found while
  preparing the regression → clause filed (documentation#19) → spec PR authored & merged
  (#20) → codegen (0.17.5) → verified against the baseline. Without the baseline, "fixed"
  and "never tested" would have been indistinguishable.
- ✅ **F-0014 resolved** — all three corelib issues fixed & closed the same day:
  corelib-c-cpp#89 (`ab062e3`), corelib-py#41 (`d4fe94f`), corelib-ts#51 (`7a9033f` —
  "validate fixlen element word *before truncation guard*", the exact ordering diagnosis).
  All three isolates → all 12 `R invalid_msg`.
- ⚠️ **F-0013 half fixed** — **0.17.4** (generator#142, now closed) killed the **DoS** (cpp
  **226 MB → 10 MB**) and made the 9 heap backends reject. But `c`/`cpp-c-cpp`/`rust-nostd`
  still **accept + silently drop**, so the split **flipped** from a value split to a verdict
  split (9 `R` vs 3 `A`). Traced: `b6da1ed`'s "never taken" holds for `_MsgSeq`, but
  string/blob over-index goes through `_FixedStrSeq`, still carrying #126's silent `return;`
  (c-cpp has **0** `invalidate()` calls vs cpp's **13**). Violates §7 + §7.1. Filed
  **[generator#149](https://github.com/sofa-buffers/generator/issues/149)**.
- **Regression gate 18 → 25 inputs**, still 0 divergences: promoted F-0014's 3 isolates +
  F-0015's 3 over-bound vectors + its within-bound **control** (which guards the
  counter-direction — that we don't start over-rejecting).
- ✅ No regression from `4e78b0a` (java array omit-default hoisted to a static) — F-0011's
  vectors stay green.

**Fourteenth change 2026-07-17 — sofabgen 0.17.6: F-0013 FULLY RESOLVED; regression gate 25→26.**
Installed via the reworked `bootstrap.sh` (latest release, sha256-verified). 0.17.6 lands
generator#149 → #151 (fixed-capacity C family) + #150 (rust no_std): the 3 profiles that were
still silently dropping an over-index element now **reject** it. Box green throughout.
- ✅ **F-0013 done** — `overindex_clean` + `overindex_amplify` → **all 12 `R invalid_msg`**;
  in-range elements still accepted by all 12; DoS gone. Closed over four releases in the
  right order: DoS + heap half first (0.17.4, security-critical), fixed-capacity verdict half
  last (0.17.6). Promoted `overindex_clean.bin` into the gate (now **26 inputs**).

Net open now: **F-0004** (§8 UTF-8, gen#85) — and the *unfiled* **F-0016** (overlong >64-bit
varint accepted by 8 impls, found in the 2nd 1 h fuzz round; corelib-side, not yet written up).
F-0001 + F-0010 + F-0011 + F-0012 + F-0013 + F-0014 + F-0015 resolved.

**Fifteenth change 2026-07-17 — F-0016 written up + RESOLVED; F-0017 opened; regression gate 26 → 29.**
- ✅ **F-0016 filed and resolved.** The overlong-varint divergence was written up and filed
  per-impl against the seven lenient corelibs (the varint reader caps the byte count at 10 but
  never checks the 10th byte's overflow bits): corelib-cpp#39, corelib-go#48, corelib-rs-no-std#45,
  corelib-py#43, corelib-ts#53, corelib-java#41, corelib-cs#37. All seven fixed & closed;
  **re-measured all 12 `R invalid_msg`** on both over-64-bit vectors (baseline 8A/4R), control
  still `A`. Promoted the two vectors + the control into the **regression gate (26 → 29 inputs)**.
  Also hardened `drivers/java/build.sh` to rebuild the corelib jar when the source is newer — a
  cached jar had masked this fix.
- 🆕 **F-0017 (new, open):** the generated **TypeScript** decode dispatches on the field id alone
  and calls the schema-typed reader **without checking the header wire type**, so a type-mismatched
  header desyncs it from the wire framing (isolate `05 00 01`: 11 → `R`, ts → `I`). Codegen defect
  **G-0014**, filed **generator#160** — distinct from (and upstream of) the resolved corelib-ts
  precedence family. Found by the 3 h fuzz on 0.17.7.

Net open now: **F-0004** (§8 UTF-8, gen#85) and **F-0017** (generator#160 / G-0014).

**Sixteenth change 2026-07-18 — sofabgen 0.18.0: F-0004 + F-0017 RESOLVED (crucible#55); F-0018
opened; regression gate 29 → 44; full box green.** Polled for the announced 0.18.0 release, then
integrated it via `SOFABGEN_VERSION=v0.18.0 ./scripts/bootstrap.sh` (sha256-verified) with the
corelibs at their `origin/main` tips. 0.18.0 lands two fixes Crucible had open:
- ✅ **F-0004 RESOLVED (issue #55) — strict UTF-8 ON family-wide.** 0.18.0 ships the codegen call
  sites for rust/java/cs/zig ([generator#162](https://github.com/sofa-buffers/generator/pull/162));
  c/cpp/go/py/ts enforce it corelib-internally; the Unicode-typed corelibs are always strict. Only
  the C corelib defaults OFF (footprint), so **`drivers/c/build.sh` + `drivers/cpp/build.sh` (c-cpp)
  opt in** with `-DSOFAB_ENABLE_STRICT_UTF8` and compile `corelib-c-cpp/src/utf8.c`; the **zig
  driver** now supplies the `build_options.strict_utf8=true` module its bare `zig build-exe` needs.
  New generator `engine/structured/utf8_seeds.py` embeds each malformed form (11 vectors from
  corelib-c-cpp's `invalid_utf8` group) as the `nested.str` of a valid `probe`, plus 3 valid
  controls. **Verified:** the old 4-way raw/U+FFFD/empty/reject split is gone — every malformed
  vector → **all 12 `R invalid_msg`**, every valid control → **all 12 `A`** and round-trips. 14
  seeds promoted into the gate.
- ✅ **F-0017 RESOLVED** — [generator#160](https://github.com/sofa-buffers/generator/issues/160)
  fixed in 0.18.0 ([PR #161](https://github.com/sofa-buffers/generator/pull/161), "frame each
  decoded field by header wire type"). Isolate `05 00 01` → **all 12 `R invalid_msg`** (ts was
  `I`); promoted `F0017_ts_wiretype_iso.bin` into the gate.
- 🆕 **F-0018 (new):** adding F-0004's embedded-U+0000 control surfaced that on `c` + `cpp-c-cpp`
  a `string` with an embedded NUL re-encodes `A\0B` → `A`, while the other 10 preserve it; all 12
  *accept*, so it is a pure **value** split. Initially filed as a codegen defect (G-0015);
  **reclassified same day as by-design — see the Seventeenth change below.**
- ✅ **Full box green on 0.18.0:** seeds 6×12, **regression 44×12**, cross-encode 69×12, union
  11×12, limit mode (arr/str/blb) 9-driver roster — **all 0 divergences** (3 expected soft
  `incomplete_value` warnings on the F-0001/F-0006 truncation reproducers).

Net open now: **F-0018** only.

**Seventeenth change 2026-07-18 — F-0018 reclassified: by-design, not a bug (allowed divergence).**
On review, F-0018 is **not** a codegen defect. The C object API deliberately models a `string` as a
NUL-terminated `char[]`, and a C string's length *is* `strlen` — `sofab_ostream_write_string`'s
`strlen` (`ostream.h:302`) is correct, not defective. The corelib *receives the value in full*
(istream copies all bytes + terminator, `istream.c:779`; the strict-UTF-8 check validates all of
them, `istream.c:886`); the projection to first-NUL happens only when the value is read back as a
C string. So embedded U+0000 is a **type-representation projection**, not a decode loss:
- **not INVALID** (rejecting a fully-received value would be wrong), **not a family-wide ban**
  (U+0000 is legal on the wire and the other 10 profiles preserve it), **not a codegen change**
  (that would de-idiomatize C strings for a pathological input);
- the **lossless path** is the byte/length (visitor) API, which hands the raw `{ptr,len}`.

Recorded as an **allowed divergence** in `oracle/policy.yaml` (axis `accept_value`, spec basis
MESSAGE_SPEC §8 — preservation of embedded U+0000 is implementation-defined for a NUL-terminated
profile). SOFABGEN **G-0015 withdrawn**. F-0018 stays in `findings/` as a documented by-design
record. **No open bug remains** — all 18 findings are resolved or by-design.

**Eighteenth change 2026-07-19 — sofabgen 0.18.0 → 0.19.2; corelibs re-pulled; full box green, no regression.**
Refreshed all corelibs to `origin/main` first, then polled for the announced 0.19.2 release and
integrated it via `SOFABGEN_VERSION=v0.19.2 ./scripts/bootstrap.sh` (sha256-verified). No Crucible
finding targeted this bump — installed to keep the toolchain current (the user's deliberate pin, was
0.18.0).
- **Corelib tips that advanced:** `corelib-c-cpp` 57dba4a → 56c88fa (`feat(cpp): expose delivered
  wire type on IStreamImpl`, §7.3), `corelib-cpp` bc0cb05 → 2be6fe2 (`build: --parallel job count`,
  build-only), `corelib-ts` 7bbc499 → e307a64 (`chore(devcontainer): drop CI=true`, env-only). The
  other seven corelibs + `documentation` were already at their `origin/main` tips, unchanged. Only
  the c-cpp change is wire-adjacent; py/java did not move, so their venv/jar caches needed no wipe.
- ✅ **Full box green on 0.19.2:** seeds 6×12, **regression 44×12**, cross-encode 69×12, union
  11×12, limit mode (arr/str/blb) 9-driver heap roster — **all 0 divergences** (3 expected soft
  `incomplete_value` warnings on the regression corpus). The c-cpp "delivered wire type" change did
  **not** perturb **F-0017** — its reproducer (`F0017_ts_wiretype_iso.bin`) is in the gate and stayed
  at 0 divergence.

Net open: still **F-0018** (by-design) only — no change.

**Nineteenth change 2026-07-19/20 — structural sweep framework + 8 h fuzz round; F-0019–F-0021 resolved (0.19.3), F-0022–F-0024 opened; regression gate 44 → 59.**
- **Structural sweep framework** landed (`engine/structured/sweep_*.py`, `scripts/sweep.sh`, CI gate
  in `replay.yml`): a shared schema-position model + a two-oracle runner (**agreement** — all 12 same
  line; **conformance** — accept-vs-reject matches spec, catching a family-wide-wrong answer that is
  agreement-green but conformance-red). The runner is **axis-aware** (hard verdict/accept_value splits
  vs soft incomplete_value/reject_class, per `policy.yaml`). **Six axes:** repeated-id (§7.4),
  over-bound (§7.1), reserved-subtype (§4.6), truncation (§7) — **blocking + green**; wiretype (§7.3)
  and malform×truncation (§5.2) — **report-only** (they carry the three open findings). Central lesson:
  **isolate-green ≠ axis-green** — a fixed vector can still leave the rule broken at a position it never
  tested.
- **F-0019 / F-0020 / F-0021 resolved in sofabgen 0.19.3** (2026-07-19/20): §7.4 duplicate-id
  (documentation#23 + generator#175), §7.3 mis-typed field skip (the struct-field and array-into-scalar
  positions). Verified all-12-agree, promoted into the gate.
- **F-0022 / F-0023 opened** by the wiretype sweep — the §7.3 guard still missing at the **array-fill
  arm** (F-0022, generator#188) and the **wrapper-element loop** (F-0023, generator#189). Both
  generator-only.
- **8 h C-pacemaker round** (2026-07-20, sofabgen 0.19.3): **2.24 G executions**, **0 sanitizer
  crashes, 0 timeouts, no memory leak**, seed suite green throughout. Three `slow-unit-*` artifacts
  investigated → **benign** (≤ 0.03 s isolated; transient timer flags under 3-worker load, not
  algorithmic DoS). The full differential over the divergence-enriched `corpus/interesting` surfaced one
  dominant class (63 % of sampled verdict-splits) → **F-0024** (generator#190 / G-0016): the generated
  Rust `try_decode` discards a detected INVALID (`v.inv`) via `?` when the input is also truncated,
  returning `I` where §5.2 requires `R`. Delta-debugged 146 B → 11 B; the malform×truncation sweep axis
  generalizes it (6 malformation kinds reproduce, reserved-subtype path stays green — separating the two
  malformation paths). Filed with a four-vector control set (crucible#66/#68).
- **Regression gate 44 → 59** (the §7.3 + §4.6 resolved isolates promoted); the three open findings kept
  **out** of the gate until their codegen fixes land.

Net open: **F-0022 / F-0023 / F-0024** — all **generator-only codegen**, filed generator#188/#189/#190;
each waits on a sofabgen release, then re-pull + verify its report-only sweep axis goes green + promote.
Plus **F-0018** (by-design).

**Twentieth change 2026-07-21 — sofabgen 0.19.3 → 0.19.4; corelibs re-pulled; F-0022 + F-0023 resolved; regression gate 59 → 69; full box green.**
Polled for the announced 0.19.4 release; it published as a **non-latest** asset (download live while
`/releases/latest` still pointed at 0.19.3), so integrated it via `SOFABGEN_VERSION=v0.19.4
./scripts/bootstrap.sh` (sha256-verified) rather than the plain `latest` path. Corelibs reset to
`origin/main` first: **corelib-go** 057354a → 8dd7ddb and **corelib-rs-no-std** a55d92c → 5ff6921
advanced; the other eight were already at their tips.
- ✅ **F-0022 resolved** ([generator#188](https://github.com/sofa-buffers/generator/issues/188)): the
  generated array-fill arm now carries the §7.3 guard (`if self.afill == 0 { return; }`, rust
  `message.rs:281`) and `array_begin` arms `afill` only at a real array position — a bare scalar at an
  array id falls through and is skipped, symmetric to the F-0021 `askip` fix; no corelib change. All 5
  isolates → 0 divergences across 12; **the array-field←scalar half of the wiretype sweep is now clean.**
- ✅ **F-0023 resolved** ([generator#189](https://github.com/sofa-buffers/generator/issues/189)): the
  `string_array` wrapper-element loop now emits the same §7.3 guard the struct-field dispatch had —
  TS `message.ts:372`, Py `message.py:446`, C++ `_StrSeq` — so a mis-typed element (blob / fp32 / signed
  / sequence) is skipped instead of read as the declared type. All 5 isolates → 0 divergences across 12.
- **Regression gate 59 → 69:** the F-0022 (3 mismatch + 2 control) and F-0023 (4 mismatch + 1 control)
  isolates promoted (`F0022_*` / `F0023_*`); `CORPUS=corpus/regression ./scripts/run.sh` → 69×12,
  0 divergences (3 expected soft `incomplete_value` warnings unchanged).
- ⚠️ **The wiretype (§7.3) sweep is NOT yet green — one residual remains.** After #188/#189 it drops from
  the fuller F-0022/F-0023 set to **exactly 2 vectors**: a **scalar fp field receiving an fp array**
  (`arrays.nested.fp32`/`fp64` declared `FIX_fp32`/`fp64`, fed an `ArrayFloat` of `[1.5]`). This is the
  **fp analogue of F-0021** (scalar←array), which generator#183 covered for **integers only** — the
  `askip` guard sits in `unsigned()`/`signed()` (rust `message.rs:275`/`:289`) but **not** in `fp32()`/
  `fp64()` (`:304`/`:311`), and `array_begin` arms `askip` only for `Unsigned`|`Signed` array kinds
  (`:368`), never `Float`. 7 backends skip; rust-std/rust-nostd/java/csharp/zig store the element into
  the scalar. **New finding, to be catalogued as F-0025** (generator-only, same fix shape as #183/#188).
  Kept **out** of the blocking set + the gate until it lands. `sweep.sh` comment updated to point at it
  instead of the now-resolved F-0022/F-0023.
- ✅ **Full box green on 0.19.4:** seeds 6×12, **regression 69×12**, cross-encode 69×12, union 11×12,
  limit mode (arr/str/blb) 9-driver heap roster, structural sweep blocking axes — **all 0 divergences**.

Net open: **F-0024** (generator-only, generator#190 / G-0016) + the newly-isolated **F-0025** (fp §7.3
scalar←array, pending write-up + generator issue). Plus **F-0018** (by-design). F-0022/F-0023 closed.

**Twenty-first change 2026-07-21 — F-0024 verified resolved on 0.19.4; malform×truncation sweep promoted to blocking; regression gate 69 → 73.**
Re-checking the open findings on the same 0.19.4 build (drivers already rebuilt) showed **F-0024 is
also fixed** — generator#190 landed in 0.19.4 alongside #188/#189.
- ✅ **F-0024 resolved** ([generator#190](https://github.com/sofa-buffers/generator/issues/190) /
  G-0016): the generated `try_decode` now captures `feed`'s result without `?`, reads `v.inv`, and
  returns `InvalidMsg` **before** surfacing the Incomplete — `fed = is.feed(data, &mut v); … if invalid
  { return Err(InvalidMsg); } fed?;` (rust `message.rs:235/242/246`). INVALID dominates a truncated
  tail per §5.2. 0.19.3 had `is.feed(data, &mut v)?;` (`:234`), whose `?` discarded `v.inv` under
  truncation — a pure ordering bug, now correctly ordered.
- **Verified three ways:** (1) code inspection (the exact generator#190 fix); (2) the 4 isolates → 0
  divergences across all 12; (3) the **malform×truncation sweep (§5.2)** — 20 vectors, 0 divergences,
  **0 conformance failures**, all 18 malformed×{complete,trunc} → `R` (the `_trunc` vectors that flipped
  rust to `I` on 0.19.3 are now `R`).
- **malform×truncation sweep promoted report-only → blocking** in `scripts/sweep.sh` — five blocking
  axes now, only wiretype (§7.3) remains report-only (residual F-0025). The 4 F-0024 vectors promoted
  into the gate (`F0024_*`, 69 → 73); `CORPUS=corpus/regression ./scripts/run.sh` → 73×12, 0 divergences
  (4 expected soft `incomplete_value` warnings).

Net open: only the newly-isolated **F-0025** (fp §7.3 scalar←array, pending write-up + generator issue).
Plus **F-0018** (by-design). **All 24 catalogued findings are now resolved or by-design.**

**Twenty-second change 2026-07-21 — F-0025 written up + filed (generator#193); catalog 24 → 25.**
Deep-verified the wiretype sweep's last residual before filing (the F-0022/23/24 lesson: don't trust
the label, check the build): confirmed the 2 divergences persist on the fresh 0.19.4 build, decoded
the reproducer to an ArrayFixlen at a scalar-Fixlen fp id (§7.3 mismatch → skip is correct), and traced
the identical **double gap** in all five storing backends — `arrayBegin` arms `askip` only for
`Unsigned`|`Signed` (never `Fixlen`/fp), **and** the `fp32()`/`fp64()` callbacks lack the `askip` guard
`unsigned()`/`signed()` carry. generator#183's own arrayBegin comment (*"an integer array…"*) is the
documentary proof the fp corner was out of its scope.
- **F-0025 catalogued** in `findings/F-0025-scalar-fp-field-receives-fp-array/` (NOTES + 2 reproducers +
  2 controls) and `results/FINDINGS.md`; the 4 isolates via `run.sh` → the 2 reproducers diverge
  (accept_value), the 2 controls agree.
- **Filed [generator#193](https://github.com/sofa-buffers/generator/issues/193)** (generator-only,
  rust-std/rust-nostd/csharp/java/zig; fix mirrors #183/#188 — arm `askip` for `Fixlen` in `arrayBegin`
  + add the guard to `fp32()`/`fp64()`). Kept **out** of the green gate; the wiretype sweep stays
  report-only until it lands. When it does: re-pull corelibs → sweep goes green → promote axis +
  isolates.

Net open: **F-0025** (generator-only, generator#193) + **F-0018** (by-design). **All other 23 findings
resolved.**

**Twenty-third change 2026-07-21 — blob_array added to `probe` (F-0013 blob-path follow-up); §7.1 blob path green; F-0026 opened; catalog 25 → 26.**
Added a `blob_array` (id 201, the blob analogue of `string_array` id 200) to `schema/probe.sofab.yaml` and
wired it through **all six sweep axes** (`sweep_positions.py` position + the overbound/wiretype/repeated-id
element handling), `engine/structured/gen.py` (6 value-rich blob vectors + the always-emitted wrapper), and
the truncation rich message. The 12 drivers rebuilt schema-agnostically under the round-trip canonical form —
**no driver change**. Two results:
- ✅ **The over-bound §7.1 blob path is GREEN** — blob-array over-index (id ≥ count) and over-maxlen elements
  → **all 12 reject**. This answers F-0013's long-open blob question: the 0.17.6 fixed-capacity fix hardened
  `_BlobSeq` too, not just the string path. The `docs/TODO.md` "F-0013 blob path" + "blob array schema" items
  are now done.
- 🆕 **F-0026 (new, open):** the §7.4 `blob_array` wrapper **re-open** (replace-whole) keeps a stale zeroed
  element on the **C object API** — `c` alone re-encodes `blob_array{id0=0000}` where the other 11 drop it.
  Minimal isolate `ce0c0213dead07ce0c07` (10 B). Root cause **corelib-c-cpp**, not codegen:
  `sofab_object_init` (`object.c:242-254`) zeros a sized blob's buffer via a generic `memset(offset,size)`
  but never its companion length at `offset - nested_idx` — the one function of four (`_field_is_default` /
  encode / decode all honour it) that omits the sized-blob branch, so the stale `len != 0` keeps the "cleared"
  element live. `string_array` (id 200) has no separate length → replaces correctly, so the split is
  blob-specific; `cpp-c-cpp` (C++ `FixedBytes` over the same corelib) agrees, confirming the pure-C
  `object.c` path only. Written up in `findings/F-0026-c-blob-wrapper-reopen-stale-element/` (NOTES +
  2 reproducers + 2 controls) + `results/FINDINGS.md`; filed [corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106). Carved out of the blocking
  repeated-id sweep axis (`sweep_repeated_id.py`, `elem == "blob"` skip) and kept **out** of the gate until
  the corelib fix lands — mirroring how F-0025 keeps the wiretype axis report-only.
- ✅ **Box green:** seeds 6×12, cross-encode **75×12** (incl. the 6 new blob vectors + the +2-byte trailing
  empty `blob_array` on the existing 69), regression 73×12, all five blocking sweep axes. wiretype stays
  report-only (F-0025); repeated-id blocking-green with the blob-reopen carve-out.

Net open: **F-0025** (generator#193) + **F-0026** (corelib-c-cpp#106). Plus **F-0018** (by-design).

**Twenty-fourth change 2026-07-21/22 — the materialized-value (element-access) oracle: a second canonical form, all 12 drivers, CI-gated, schema-agnostic. Merged to `main` (PR #75), `main` CI green.**
Added a **second canonical form** (`oracle/materialized.md`) beside the round-trip re-encode, targeting the
round-trip form's *recorded* blind spot (`oracle/canonical.md` §Tradeoff — two decoders that hold different
in-memory values but re-encode to the same sparse-canonical bytes are masked, F-0010's class). Under
`SOFAB_MATERIALIZE=1` each driver emits `A <dump(decode(input))>` — a full walk of the **decoded value** (every
field + array element explicit, floats as raw bit patterns, `len:hex` strings/blobs) — reusing the comparator's
`accept_value` axis unchanged; `scripts/materialize.sh` runs it over `corpus/structured`.
- **All 12 drivers** implement it: **75×12 → 0 divergences**, each matching the `engine/structured/materialize.py`
  reference (ground truth) byte-for-byte; the default round-trip path is unchanged.
- **Wired into CI** (`replay.yml`) as a standing gate — agreement (the 12-way differential) **+** conformance
  (the schema-agnostic C anchor vs the reference, so a *family-wide-wrong* dump — agreement-green — is caught).
- **Generated schema-type table** (`engine/structured/schema.py` → `oracle/materialized-schema.json`): the
  typed field tree (kinds/ids/counts/nesting) a value walk needs is derived from the schema, not hardcoded, and
  drives the reference (schema-agnostic ground truth); `cmp`-checked each run so it can't drift.
- **All 12 walkers are schema-agnostic:** C via sofabgen's object descriptor; go/ts/java/cs/python consume the
  descriptor at runtime (reflection); rust/cpp/zig **generate their walker source** from it at build time
  (`drivers/<lang>/materialize_gen.py`, unrolled straight-line — a compile-only stub for the non-`probe`
  union/limit schemas). A schema change reflows to every walker with **zero hand-editing**.
- **Measured design note:** numeric arrays are already materialized to N in memory family-wide, so this form's
  live signal is the **wrapper arrays** + **element-level fidelity** + **regression-proofing**, not F-0010's
  exact shape (resolved). The build broke the union/limit suites once (the static generators emitted a
  default-`probe` walker for a mismatched Probe); fixed with the per-schema stub, verified across the full
  `replay.yml` sequence before merge.

Net open unchanged: **F-0025** (generator#193) + **F-0026** (corelib-c-cpp#106); **F-0018** by-design.

**Twenty-fifth change 2026-07-22 — corelib-dart integrated into every suite; roster 12→13 drivers / 10→11 corelibs (branch `dart-integration`).**
Wired sofabgen's 10th language target (crucible#77 / generator#211) into the whole harness on the
latest green sofabgen CI build (`0.0.0-20260722065611-f61a29b31c01`). New `drivers/dart/`
(`driver.dart` + `build.sh` + `meta` + `materialize_gen.py` + `fuzz.dart`), **AOT** end-to-end
(`dart compile exe`, native ELF — never `dart run`/JIT). Registered in `run.sh` (seeds/regression/
cross-encode/union), `run-limits.sh` (heap roster), `sweep_run.py` (structural sweep), `materialize.sh`
(element-access). The generated `Probe.tryDecode → DecodeStatus` maps 1:1 to `A`/`I`/`R`/`L` (sticky
`_Dec.inv` folds schema-bound violations into INVALID, the Rust/Zig model), so the schema-agnostic
round-trip form needed **zero per-field Dart code**.
- ✅ **Every suite green with 13 drivers:** seeds 6×13, regression 73×13, cross-encode 75×13, union
  11×13, limit mode (arr/str/blb) 10-heap-driver roster, structural sweep (5 blocking axes),
  materialized 75×13 + C-anchor conformance 0/75. Dart is byte-identical to Go on every seed.
- **Dart-specific care (all verified):** u64 printed unsigned via `BigInt` (`02_full` → `u18446744073709551615`,
  matches C), fp32 repacked to the 32-bit pattern, fp64 as two uint32 halves; heap profile → bakes
  `max_dyn_*` into `DecoderLimits` and emits `L` on over-cap (`over_arr → L`); §7.3/§7.4 dispatch-by-type
  skip matches the family (no desync). No Dart-attributable finding.
- 🐞 One **Crucible-side** walker bug found + fixed in Stage 4 (the `u`/`s` materialize leaves lacked
  their type-tag prefix — `0:0` vs C's `0:u0`), caught by the C-anchor conformance gate. Not a
  corelib/generator finding.
- 🔎 **Side-result (toolchain, not Dart): F-0025 is resolved on this CI build.** The wiretype (§7.3)
  sweep axis went **green** (was report-only); both F-0025 reproducers now show all 13 drivers agreeing
  (the fp array at a scalar-fp id is skipped, including the formerly-storing rust/java/csharp/zig) —
  generator#193 landed in the CI build post-0.19.4. **Promoted in the Twenty-sixth change below** (this
  branch includes the F-0025 cleanup): the wiretype axis is now blocking, F-0025 is marked resolved, and
  its isolates are in `corpus/regression/`.
- **CI:** the gates invoke the scripts (which now carry Dart), so no per-gate edit; the CI image's
  Dockerfile already installs the Dart SDK — it needs the standing one-time `image.yml` rebuild.
**Twenty-sixth change 2026-07-22 — F-0025 verified resolved; wiretype (§7.3) sweep promoted report-only → blocking; regression gate 73 → 77 (branch `f0025-cleanup`, rebased on `dart-integration`).**
Re-checking the open findings on the latest green sofabgen CI build
(`0.0.0-20260722065611-f61a29b31c01`, which carries generator#193 post-0.19.4) showed **F-0025
is fixed** — [generator#193](https://github.com/sofa-buffers/generator/issues/193) closed.
- ✅ **F-0025 resolved:** the generated `arrayBegin` now arms the discard counter (`askip`) for the
  **fp** array kinds (not only `Unsigned`/`Signed`), and the `fp32()`/`fp64()` callbacks carry the same
  `askip` guard `unsigned()`/`signed()` had — so a scalar fp field fed an fp fixlen array **skips** it
  per §7.3 instead of storing the element. Generator-only, no corelib change (mirrors #183/#188).
- **Verified two ways:** (1) the 2 reproducers → **all 13 skip** (re-encode to `5607a606560707c60c07ce0c07`),
  the 2 controls agree; (2) the **wiretype (§7.3) sweep is green** — 319 vectors, 0 divergences,
  0 conformance failures.
- **Sweep axis promoted report-only → blocking** in `scripts/sweep.sh` — **all six axes now blocking**;
  no report-only residual remains (F-0026 stays carved out of the repeated-id axis until its corelib fix).
- **Regression gate 73 → 77:** the 2 F-0025 reproducers + 2 controls promoted (`F0025_*`);
  `CORPUS=corpus/regression ./scripts/run.sh` → 77×13, 0 divergences.

Net open: only **F-0026** (corelib-c-cpp#106). Plus **F-0018** (by-design). **All 25 other catalogued
findings are resolved or by-design.**

**Twenty-seventh change 2026-07-22 — F-0026 verified resolved; last sweep carve-out dropped; regression gate 77 → 81 (branch `f0026-cleanup`). Zero open findings.**
Verifying "F-0026 is the only open finding" surfaced that it, too, is **already fixed**:
[corelib-c-cpp#106](https://github.com/sofa-buffers/corelib-c-cpp/issues/106) is closed and its fix
(`2416a2b`, "reset sized-blob used-length in `sofab_object_init` (§7.4 re-open)") has been on
`origin/main` — so it landed silently during the Dart session, masked because F-0026's sweep axis was
carved out and its reproducer kept out of the gate.
- ✅ **F-0026 resolved:** the C object API's `sofab_object_init` now resets a sized blob's companion
  length on a §7.4 wrapper replace-init, so a re-opened `blob_array` no longer keeps a stale zeroed
  element. Corelib-only, no codegen change.
- **Verified two ways:** (1) all 4 isolates (`blob_reopen_empty`, `blob_reopen_two` + 2 controls) →
  **all 13 drivers agree** (`c` now drops the re-opened element); (2) the `elem=="blob"` carve-out was
  removed from `sweep_repeated_id.py` and the **repeated-id (§7.4) sweep is green with the blob wrapper
  included** — 16 vectors, 0 divergences.
- **Last carve-out gone:** all six sweep axes are now blocking **with no exclusions**.
- **Regression gate 77 → 81:** the 2 F-0026 reproducers + 2 controls promoted (`F0026_*`);
  `CORPUS=corpus/regression ./scripts/run.sh` → 81×13, 0 divergences.

Net open: **none.** Plus **F-0018** (by-design). **All 25 catalogued findings are resolved; 1 by-design.**

| finding | what | tracked in / status |
|---|---|---|
| F-0001 | truncated input: lenient (C/C++/Rust/Java/C#) vs strict (Go/Py/TS/Zig) | spec §7 (finish-less); all 10 corelibs + all 12 drivers implement `I`. **✅ verified green 2026-07-13** — every driver emits `I` on the F-0001 seeds (0 divergences). Was 7-accept/5-reject. |
| F-0004 | invalid UTF-8 in a string: 4 behaviors, driven by the string type | spec §8 → epic **generator#85** — ✅ **RESOLVED 2026-07-18** (sofabgen 0.18.0 / crucible#55): strict UTF-8 ON family-wide, all 12 `R invalid_msg` on malformed, all 12 `A` on valid; 14 seeds in the regression gate |
| F-0002 | corelib-c-cpp encoder left-shifts a negative value (UB) | **corelib-c-cpp#70** merged — ✅ **resolved** |
| F-0003 | Rust array-fill OOB → panic (crash/DoS) | ✅ **fully resolved.** Crash fixed by **generator#87**; the residual over-count *accept* divergence (**generator#100**) is fixed in **sofabgen 0.16.1** (commit `ca0fda7`, "reject over-count scalar arrays in every backend"). **Re-verified 2026-07-15** with a *clean non-truncated* over-count(8>5) array (`a6 06 03 08 01..08 07`): **all 12 drivers reject** (`R`) — rust-std/nostd now reject with the family. (The old 145-byte reproducer is contaminated — over-count *and* truncated — so rust/zig report `I` there; the clean isolate is the correct test.) |
| F-0005 | corelib-cpp accepts malformed msgs the family rejects | **corelib-cpp#22** closed — ✅ **resolved** |
| G-0001,3,4,5,6 | codegen weaknesses (infallible Rust/C++ decode, no-std string handling, Go bytes import) | **all fixed in sofabgen 0.15.1** (PRs #88/#92/#93/#89/#90) — see results/FINDINGS.md |
| G-0002 | Rust std vs no_std UTF-8 (intra-Rust) | generator#80/#91 — ✅ **fixed** (both empty on invalid); family-wide UTF-8 is F-0004 / #85 |
| G-0008 | generated one-shot decode discards the INCOMPLETE status (C#, Java) | ✅ **fixed** — sofabgen 0.15.3 ([generator#106](https://github.com/sofa-buffers/generator/pull/106) closes #105): status-surfacing `TryDecode`/`tryDecode`. Crucible C#/Java drivers now **single-pass** on it — two-pass workaround **removed** (crucible#10, 0.16.0 bump). See results/FINDINGS.md |
| G-0009 | generated C++ emits a schema-*unbounded* array as `std::array<T, 0>` (not `std::vector<T>`) | ✅ **fixed in sofabgen 0.16.1** ([generator#112](https://github.com/sofa-buffers/generator/issues/112), commit `7899c4b` → `std::vector`). **Re-verified 2026-07-15:** repro `03 03 07 08 09` → cpp now decodes `[7,8,9]` (was `[]`), matching the family; cpp agrees on the arr limit vectors (under/at/over-cap → `L`). **cpp rejoined the `arr` dimension** of limit mode (`scripts/run-limits.sh`, `NO_CPP` hold-out removed); limit mode green with cpp in all three dimensions. See results/FINDINGS.md |

**New divergences surfaced 2026-07-13 while wiring the `I` verdict — ✅ both fixed (pre-existing corelib leniency, unrelated to truncation):**
- **corelib-cpp** classified an unterminated over-long varint (>64 bits) as `I` (INCOMPLETE) where the rest say `R` (INVALID) — the measure phase treated the over-long-but-unterminated varint as a truncated tail. **Fixed** (corelib-cpp#29, in PR #28): getVarint/skipVarint report the >64-bit overflow so the measure phase rejects it.
- **corelib-ts** accepted a top-level stray sequence-end (`0x07`) as `A`, and also accepted a truncated *known* nested sequence as `A` (COMPLETE) — the pull/Cursor decoder tracked no depth. **Fixed** (corelib-ts#42, in PR #41): a `depth` counter → stray end at root = `R` (INVALID), unclosed sequence at EOF = `I` (INCOMPLETE), matching the fast path.

Both verified: full differential over the two reproducers + the F-0001 seeds across all 12 drivers = **0 divergences**.

**Twenty-eighth change 2026-07-22 — WP-01: union under the structural sweeps; F-0027 opened; catalog 26 → 27, open 0 → 1.**
`docs/improvements.md` WP-01 (the biggest untested-feature gap): the `union` wire feature lived entirely
outside the generated sweep pipeline (`engine/structured/schema.py` raised `ValueError` on `union`), so
none of the six axes, cross-encode, or the materialized oracle ever saw it — union coverage was 11 static
seeds run as a plain differential with zero conformance assertions.
- **Schema pipeline learned `union`:** `schema.py` now emits a `union` descriptor node (`default_id` +
  typed `options`, string/blob options carrying `maxlen`); `descriptor('probe-union')` succeeds. The
  `probe` descriptor and committed `oracle/materialized-schema.json` are **byte-identical** (union branch
  only fires on a union field).
- **Schema-derived union position model:** `sweep_positions.UNION_POSITIONS` is *derived from the
  descriptor* (not a hand-maintained parallel literal — the drift `sweep_positions` exists to prevent):
  7 positions (tag, the `choice` union sequence, its 4 members, trailer). A union is a sequence carrying
  at most one child (§4.2); members are ordinary positions inside the union scope, `seq_union` marks the
  sequence itself.
- **Five axes gained a union pass** (`emit_union`): wiretype §7.3, repeated-id §7.4 (last-wins, merge,
  seq re-open, and the §7.4 "a §7.3-skipped occurrence doesn't count" cross vector), over-bound §7.1
  (as_text maxlen16 / as_blob maxlen8), reserved-subtype §4.6, truncation §7. Driven by
  `sweep_run.py --union`; **130 vectors**.
- **Report-only in `scripts/sweep.sh`** (ground rule 4 — a new axis is report-only until green or every
  divergence is catalogued): a labeled pass rebuilds the 13 drivers to `probe-union`, runs the union axes
  (non-blocking `|| echo`), then **rebuilds back to `probe`** so binaries are never left mixed
  (ground rule 3).
- **Result:** repeated-id, over-bound, reserved-subtype, truncation → **green across all 13**. The
  **wiretype** union pass surfaced **F-0027** (35 vectors): `rust-nostd` rejects a §7.3-skippable array
  or fp64 field that `probe-union` never declares. Root cause established (not inferred): sofabgen emits
  the no-std corelib's cargo features from the schema's *used* wire types (`["fixlen","sequence"]` vs
  `probe`'s `["array","fixlen","fp64","sequence","value64"]`), and corelib-rs-no-std gates wire-type
  *parsing/skip* — not just field storage — behind those features. Minimal isolate `0300` (2 B). The
  probe wiretype axis stays green (319×13), and `rust-std` (same generated code) agrees with the family —
  the two-way sibling split pinning it to the feature config, i.e. codegen. **Generator-primary → G-0017**,
  corelib-rs-no-std implicated (F-0010 "occasionally both"). Filed `results/FINDINGS.md` F-0027 +
  `results/FINDINGS.md` G-0017 with reproducers under `findings/F-0027-*`.
- **Not yet promoted / not in the gate** until the fix lands — per the F-0025/F-0026 arc.

**Twenty-ninth change 2026-07-23 — WP-11: harness hygiene (one position model, schema-derived bounds); no finding.**
(`docs/improvements.md` WP-11 — parallel ordinal, reconcile at merge.) Removes three silent-desync risks
in the sweep harness before WP-05's schema growth lands:
- **One position model.** `wiretype_sweep.py`'s private 29-entry position list (which uniquely carried the
  wrapper-**element** positions) is gone; the wrapper elements (`welem_str`/`welem_blob`) now live in
  `sweep_positions.POSITIONS` (27→29) and `wiretype_sweep` consumes it via a new `CAT_TO_CONSTRUCT` map.
  **Gap closed:** reserved-subtype (§4.6) now sweeps the wrapper elements too — 110→**118** vectors; all
  +8 reject uniformly (green). wiretype stays 319; every other axis unchanged — **no count dropped** (the
  WP-11 hard-fail guard).
- **Schema-derived bounds.** `count`/`maxlen` come from `schema/probe.sofab.yaml` (`_BOUNDS`), not literals
  `5`/`64`/`32`/`4`; `materialize.py`'s `ARR_COUNT` is derived from the descriptor + a uniform-count
  assertion. Committed `oracle/materialized-schema.json` unchanged.
- **`STRUCT_CHILDREN`** for id 100 now lists all eight arrays (was two); the §7.4 merge test still samples
  the first two (documented as sufficient). Doc drift "all 12"→"all 13" swept across `engine/structured/*.py`.
- **Verified:** all six blocking axes green; derived bounds byte-match the old literals; materialize
  reference byte-identical (ARR_COUNT still 5). Pure hygiene — no behavior change beyond the one gap closed.

**Thirtieth change 2026-07-22 — WP-03: non-minimal varint axis added (blocking, agreement-only); documentation#24 filed.**
(`docs/improvements.md` WP-03. Ordinal parallel to the WP-01 branch's own "Twenty-eighth" — reconcile at merge.)
A varint admits **non-minimal** forms — redundant `0x80` continuation bytes that add only zero high bits
(`5` = `05` = `85 00` = `85 80 00` …). `gen.varint` only emits minimal encodings, so no corpus contained
one; F-0016 covered only the **>64-bit overflow**. Whether the 13 decoders agree on a non-minimal-but-
≤64-bit varint was untested — a classic silent-divergence class.
- **New axis `engine/structured/sweep_varint.py`** places a non-minimal varint at every varint **role** —
  field-id header, fixlen length word, array element-count, array element value, and inside a skipped
  (unknown-id) field — padded +1/+3 bytes and up to the 10-byte ≤64-bit maximum, with minimal-accept
  controls and an 11-byte >64-bit overflow-reject contrast. 23 vectors. `gen.varint` left untouched (it is
  the canonical reference encoder).
- **Result: green — all 13 accept every non-minimal varint and re-encode to the identical minimal
  canonical form** (the round-trip normalizes it), and all 13 reject the overflow. Zero divergences.
- **Spec is silent** (CORELIB_PLAN §4.1 guards only overflow; MESSAGE_SPEC §2 constrains the encoder, not
  the decoder), so per ground rule 6 the axis is **blocking but agreement-only**: the 18 non-minimal
  vectors carry `expect="agree"` (only agreement + round-trip normalization asserted, not accept-vs-reject
  conformance) until the clause lands. Filed **[documentation#24](https://github.com/sofa-buffers/documentation/issues/24)**
  proposing the observed consensus as the rule; on adoption the
  vectors tighten to `expect="accept"`. **No finding** (green). Promoted to blocking + wired into
  `replay.yml` (via `sweep.sh`); the sweep gate is now **seven axes**.

**Thirty-first change 2026-07-23 — WP-04: framing & format-ceiling axis added (report-only); F-0028 + F-0029 opened.**
(`docs/improvements.md` WP-04. Ordinal parallel to the WP-01/WP-03 branches — reconcile at merge; finding
numbers skip F-0027, reserved by the WP-01 PR.) Two malformation classes had **no dedicated coverage**:
stray/unbalanced `sequence-end` (§5.2 — `sweep_truncation` only ever produces *open* sequences) and the
format-wide ceilings ID_MAX / FIXLEN_MAX / ARRAY_MAX / MAX_DEPTH (§6.2, reachable only by fuzzer luck).
- **New axis `engine/structured/sweep_framing.py`** (14 vectors): stray end at top level / after a scalar /
  as a surplus close / inside a wrapper; field id at ID_MAX (accept control) and over (reject); fixlen
  length over FIXLEN_MAX and array count over ARRAY_MAX at **unknown ids** (so the *format* ceiling is
  tested, not the schema `count`/`maxlen` nor the open documentation#15 over-schema-count corner), with
  **huge declared size but no payload** (a conformant decoder rejects at the word and never allocates —
  the F-0013 amplification guard); nesting past MAX_DEPTH. Report-only in `scripts/sweep.sh`.
- **Green:** stray-end (all forms), FIXLEN_MAX, ARRAY_MAX → all 13 reject; controls accept. **Two
  divergences → findings:**
  - **F-0028** — `cpp` + `dart` **accept** a field id > ID_MAX (skip it as unknown) where 11 reject.
    Both check ID_MAX only on **encode** (`corelib-cpp sofab.hpp:475`; `corelib-dart encoder.dart:140`);
    their **decoders** (`sofab.hpp:1410`; `decoder.dart:221`) omit it. corelib-c-cpp checks it in the
    decoder (`istream.c:485`), so `cpp-c-cpp` rejects — pinning it to the two pure decoders. Corelib, not
    codegen (ID_MAX is a format constant). → [corelib-cpp#47](https://github.com/sofa-buffers/corelib-cpp/issues/47)
    + [corelib-dart#14](https://github.com/sofa-buffers/corelib-dart/issues/14).
  - **F-0029** — `typescript` reports `I` for nesting past MAX_DEPTH where 12 reject. The `cursor` decode
    path tracks `depth` only for balancing; `fast.ts`/`state.ts` enforce MAX_DEPTH but `cursor.ts` does
    not — an internal inconsistency. → [corelib-ts#65](https://github.com/sofa-buffers/corelib-ts/issues/65).
- Both are **corelib** (wire/format checks, schema-independent), reproducers under `findings/F-0028-*`,
  `findings/F-0029-*`. Axis kept report-only; promote + gate on resolution (F-0025/F-0026 arc).

**Thirty-second change 2026-07-23 — WP-02 Part A: union cross-encode (green); Part B (materialized) scoped.**
(`docs/improvements.md` WP-02.) The union value space was never cross-encoded. `gen.py` gained
`encode_union` + `union_vectors` (18 value-rich vectors: each member at boundary values, default_id, and
tag+member+trailer combos) → `corpus/structured-union/` via `gen.py --union`; `scripts/cross-encode.sh`
runs a second **union pass** (rebuild → probe-union → differential → restore probe). **18 × 13 → 0
divergences** — the union value space round-trips identically. Blocking, gated by `replay.yml`. **Part B**
(the materialized/element-access dimension for unions) is a scoped follow-up: the C anchor materializes a
union out-of-the-box (target form `{opt_id:value}` for every member), but the other 12 walkers (6 runtime
+ 6 generated) don't yet handle the `union` descriptor node — a ~12-walker sub-project across 10 languages
+ a `materialize.py` union reference. No finding.

**Thirty-third change 2026-07-23 — WP-06: float specials + integer gaps in the cross-encode/materialized corpus; F-0031 opened.**
(`docs/improvements.md` WP-06.) `gen.py` covered only min-*normal* floats and one quiet NaN; the value
space missed subnormals, the signaling/payload/negative NaN variants, and unsigned mid values. Added (with
raw-byte fp support so exact bit patterns survive Python's float canonicalization): min/max subnormal
f32+f64, quiet-payload NaN, negative NaN, fp64 sNaN, explicit +0.0, and unsigned mid values; `materialize.py`
gained raw-bytes fp handling (element-access compares raw bits). `gen.py` now also **clears stale corpus
files** before regenerating (vector indices shift when the set grows). Corpus 75 → **90** vectors.
- **Green:** subnormals / qNaN-payload / negative-NaN / fp64-sNaN / +0.0 / int-mid all round-trip **and**
  materialize identically across 13 (cross-encode 90×13, materialized 90×13, 0 divergences).
- **F-0031** (the one split): an fp32 **signaling** NaN (`0x7F800001`) is **quieted** to `0x7FC00001` by
  `py-cython`, `typescript`, `dart` (double-backed fp32) where the other 10 — incl. `py-pure` — preserve
  it, violating §4.6 (bit-for-bit, no normalization). Corelib; →
  [corelib-py#49](https://github.com/sofa-buffers/corelib-py/issues/49) +
  [corelib-ts#66](https://github.com/sofa-buffers/corelib-ts/issues/66) +
  [corelib-dart#15](https://github.com/sofa-buffers/corelib-dart/issues/15). The `f32_snan` vector is
  carved out of the green gate (reproducer `findings/F-0031-*`) until fixed; the quiet-payload/negative/f64
  NaN variants stay in the gate (all preserve).

**Thirty-fourth change 2026-07-23 — WP-07: over-bound magnitude (mid + large) added to the §7.1 sweep.**
(`docs/improvements.md` WP-07.) `sweep_overbound` tested only bound+1 / id==count. Added per bounded
position a **mid** over (2×bound) and a **large** over-INDEX (element id 100_000 — declared, well-formed,
small input): F-0013's memory-amplification bug is the large-index class, and a decoder must reject at the
header word without sizing a container to the index. Axis **30 → 46 vectors, green, sub-second** (no
allocation/DoS). The large *over-maxlen* case (declared-huge length + short payload) is inherently
over-maxlen AND truncated — the §5.2 over-length-vs-INCOMPLETE precedence corner (it split R-vs-I in
testing) — so it is deferred to the malform×truncation axis (WP-09), not this clean-magnitude axis. No
finding.

**Thirty-fifth change 2026-07-23 — WP-08: §2/§3 canonicality conformance seeds (a)+(b); (c) blocked on WP-05.**
(`docs/improvements.md` WP-08.) New `corpus/conformance/` gate (wired into `replay.yml`) pinning two §2/§3
rules that were only incidentally covered: (a) §2:77-86 — an all-default nested struct is still framed as
an empty sequence, never dropped; (b) §3:185-195 — a decoder accepts a non-canonical trailing-default
array run and re-encodes it canonically (trailing run trimmed, the F-0010 rule). 3 seeds × 13 → green;
(b) verified re-encodes to count 3 `[1,2,3]` = the canonical control. **(c)** (explicit `[]` overrides a
non-empty field default, §2:112-121) is **blocked on WP-05** — no `probe` field has a non-zero `default:`
yet; lands when `struct_array` folds in (corelib-c-cpp#109). No finding.

**Thirty-sixth change 2026-07-23 — WP-09: broadened malform×truncation; F-0032 opened (§5.2 schema-bound precedence).**
(`docs/improvements.md` WP-09.) `sweep_malform_truncate` sampled 9 malformations × one tail byte. Added
malformations (blob_array over-id, array fixlen element-word/F-0014, reserved-subtype in each wrapper) and
broadened truncation to **every offset from each malformation's INVALID-point**. **Structural**
malformations (reserved subtype, bad array element-word — INVALID at the word) → all 13 `R` at every
truncation (blocking, green). **Schema-bound** malformations (over-maxlen/count/index) checked after
reading → **F-0032**: go/cpp/ts/dart (and more, varying by bound) report `I` where §5.2 requires `R`
(documentation#15 adopted; the F-0024 class still open for schema-bound checks). Codegen →
[generator#216](https://github.com/sofa-buffers/generator/issues/216) / **G-0018**. Their into-payload
truncations are carved out (the axis `STRUCTURAL` set); `_complete` controls + structural truncations stay
blocking (axis 20 → 43 vectors, green). Finding count 31 → 32, open 5 → 6.

**Thirty-seventh change 2026-07-23 — WP-10: UTF-8 at more positions (Part A); STRICT_UTF8=OFF audit (phase 1); phase 2 deferred.**
(`docs/improvements.md` WP-10.) **Part A:** `utf8_seeds.py` now emits each malformed-UTF-8 vector at BOTH
`nested.str` (id 2) and a `string_array` element (id 200.0) via a shared `_probe(...)` framer — the strict
reject is now proven at the wrapper element too; also fixed stale framing (the old framer predated
`blob_array`, so its gen.encode self-check would fail). 28 F0004 seeds (14×2), regression gate green
(95×13). **Part B phase-1 audit:** the byte-container profiles (c, cpp-c-cpp, cpp, zig) have explicit
strict flags → OFF reachable (raw bytes); the Unicode-string profiles validate inside corelib/codegen
(OFF-reachability unclear). Table in `docs/improvements.md` WP-10. **Phase 2** (opt-in strict-OFF suite)
**deferred** — a substantial env-gated build variant + per-profile-class policy for a non-default config,
needing the gen#85 Unicode audit first; the ON path is fully covered (F-0004 / Part A). No finding.

**Thirty-eighth change 2026-07-23 — C pacemaker fuzzing round (34 M execs); F-0033 opened (scalar over-width, spec hole).**
First fuzzing round this session (`scripts/fuzz.sh`, FUZZ_TIME=1500, ~22.6k exec/s, **0 ASan/UBSan hits** —
the C corelib stays clean). Corpus grew 388 → 439; the differential replay + `oracle/cluster.py` reduced
294 diverging inputs to 13 root-cause clusters. 12 mapped to **known** classes (java `incomplete_value`
soft; F-0028/F-0029; the F-0032 §5.2 schema-bound-vs-truncation family — incl. an old 2026-07-08
`crash-java-array-oom` artifact, now non-crashing = the F-0032 over-count facet; the 2 other old crash
artifacts no longer crash). **One new:** **F-0033** — a scalar wire value exceeding its declared width
(u8 > 255) splits 3 ways (reject / mask-to-width / keep-full-value); the spec is silent (§1 "storage hint,
wire carries the integer regardless"; §7 "value-range outside the wire clause"; §7.1 omits scalar
over-width). Spec hole → [documentation#26](https://github.com/sofa-buffers/documentation/issues/26). The
hand-built value corpus never emits an over-width scalar — only fuzzing reached it.

**Thirty-ninth change 2026-07-23 — toolchain + corelib bump re-verified; F-0034 opened (dart fixlen `maxlen`
guard ignores subtype, codegen).** Re-bootstrapped: sofabgen → CI build `0.0.0-20260723154129-241dc8f44efb`;
6 corelibs advanced to `origin/main` (c-cpp `aaba509`, cpp `3cee07f`, dart `f9e64ec`, go `05fe6c2`, py
`a20a96a`, ts `92a6e21`), 5 unchanged. Full re-run: **seeds green** (0 div), **regression green** (95, 0 div,
4 known `incomplete_value` soft), all blocking sweep axes green **except one new wiretype (§7.3) divergence**.
**F-0034 / G-0019** — the corelib-dart bump (`f9e64ec`, "INVALID dominates INCOMPLETE via header callbacks")
added `onFixlenHeader(id, subtype, length)`; the generated dart `ProbeNested.onFixlenHeader` enforces the
blob field's `maxlen 4` against an fp64 mismatch's 8-byte payload **without gating on subtype**, so it
rejects a §7.3-skippable field (12 skip → `A`, dart → `R`). **Attribution: codegen** (subtype/maxlen are
schema facts; corelib faithfully reports the header and is not implicated). Filed
[generator#224](https://github.com/sofa-buffers/generator/issues/224). **Decision:** carved the one divergent
cell (`10_id3_FIX_fp64`) out of the blocking wiretype axis via `KNOWN_OPEN` in `wiretype_sweep.py` (the
F-0032 `STRUCTURAL` carve-out precedent) — axis green-except-known (318 vectors) until fixed; isolate +
control kept **out** of the green `corpus/regression/` gate while open. (The `interesting` fuzz corpus, 439,
shows its usual raw divergences — exploration fodder, not a gate; unchanged.)

**F-0034 RESOLVED 2026-07-24** — [generator#224](https://github.com/sofa-buffers/generator/issues/224) fixed
overnight (sofabgen CI build `ff2a55e5`, commit "fix(dart,go): gate the maxlen header guard on subtype").
Re-verified against the new build: the isolate → all 13 skip → `A` (dart was the lone `R`). The `KNOWN_OPEN`
carve-out was **dropped** from `wiretype_sweep.py` (the cell is green again), and the isolate + control
**promoted** into the `corpus/regression/` gate (`F0034_*`). The same build closed **F-0032/go** (the
`(dart,go)` commit); the F-0032/cpp residual was separately fixed in the Crucible driver (PR #107).

**Fortieth change 2026-07-25 — bootstrap + full test: five more findings resolved, family converging.**
Re-bootstrapped: corelib-cpp `3cee07f → 80ec210` ("gate the measure-phase maxlen check on the declared fixlen
subtype", = generator#229), corelib-ts `92a6e21 → a6f31d6` ("preserve fp32 sNaN on the cursor pull path",
adds `Cursor.readFp32Raw`), sofabgen → `a2a88d0e` (2026-07-25). **Full suite green:** structural sweep (7
blocking axes incl. wiretype §7.3, 319 vectors), framing (report-only), union pass, limit mode, regression
(97, incl. promoted `F0034_*`), seeds — all **0 divergences**. **Newly RESOLVED (re-verified against the
fresh build):** **F-0028** (id>ID_MAX decode — framing green), **F-0029** (ts MAX_DEPTH skip path — framing
green), **F-0031/dart** (fp32 sNaN — dart no longer quiets), **F-0032/cpp** (the cpp measure-schema now gates
the maxlen check on subtype, so `try_decode` skips a mismatched fixlen correctly — crucible#107's §7.3
regression is fixed upstream, **no revert needed**). **Still open:** **F-0031/ts** — corelib-ts fixed its raw
channel but the **generated** ts still decodes via `readFp32()`/stores a JS `number`/re-emits `writeFp32`, so
it quiets → codegen residual, filed **generator#235** (ts analogue of dart's generator#226); **F-0033**
(scalar over-width, spec hole documentation#26); **F-0030** (struct_array, not in-tree reproducible until it
lands in `probe`). FINDINGS.md table rows + G-0018 updated to resolved.

**Also this session — F-0027 / G-0017 RESOLVED by the same bump.** [generator#215](https://github.com/sofa-buffers/generator/issues/215)
(no-std Cargo features derived from the schema's used wire types → decoder can't §7.3-skip an array/fp64
field) was **closed 2026-07-23**; the CI build `0.0.0-20260723154129-241dc8f44efb` carries the fix (sofabgen
now provisions the full wire-type decoder feature set regardless of schema). **Re-verified in Crucible:** the
wiretype (§7.3) **union** pass — 13 drivers built against `probe-union`, the schema that omits the
array/fp64 features — is now **green (77 vectors, 0 divergences)** across two sweep runs, where rust-nostd
previously rejected. FINDINGS.md F-0027/G-0017 moved to resolved.

**One-hour fuzz round (C pacemaker, post-bump) — 0 new signal.** 38.55 M execs, ~10.7k exec/s, **0 ASan/UBSan
hits**, no new crash artifact (`corpus/crashes/` unchanged — its files pre-date this run). Corpus grew
439 → 546 (coverage only). Differential + `oracle/cluster.py` over 546 inputs → 12 root-cause clusters, the
**same set as before the round** (matching representative inputs), all mapping to catalogued classes (the
F-0032 §5.2 family, F-0033 scalar over-width, F-0029 ts MAX_DEPTH, java `incomplete_value` soft) — **no new
finding**. Confirms the corelib bump introduced nothing beyond F-0034; the well-formed-wrong-subtype needle
F-0034 sits on is reached by the structured sweep, not byte-mutation fuzzing (wiretype_sweep.py docstring).

**Forty-first change 2026-07-26 — bootstrap + full test: two corelib API removals absorbed, suite green.**
Re-bootstrapped across three upstream tips in one session: corelib-c-cpp `aaba509 → 705fe95 → b49c353`,
corelib-cpp `80ec210 → d14b8ca → 733c107`, sofabgen `a2a88d0e → b898ab4e → 42a45893`; the other nine corelibs
unchanged. **Crucible adaptation — two driver edits**, both forced by an enum constant that no longer exists:
`drivers/c/driver.c` dropped `case SOFAB_RET_E_USAGE` (removed in corelib-c-cpp#111) and
`drivers/cpp/driver.cpp` dropped `case sofab::Error::UsageError` (removed in corelib-cpp#54). Both arms fell
through to the pre-existing `default: "other"`, so nothing else moved: the canonical `usage` reject class
**stays** in `oracle/canonical.md`, because rust, cs, java, zig and python still surface it. `policy.yaml`
grades `reject_class` soft, so even a driver whose class shifted could not redden a gate on that axis alone.

**The intermediate corelib-cpp tip `d14b8ca` broke the `cpp` driver outright, and it was upstream's break,
not codegen's.** That commit ("OStreamView, a sticky write-failure flag") also moved `Wire`/`Fix` from
namespace `sofab` into `sofab::detail` (private class aliases, explicitly commented "without re-exporting the
names") and deleted `namespace sofab::schema` (`FieldBound`, `SeqNode`) — all three named by
sofabgen-generated code, which stopped compiling. The API surface was left incoherent in passing:
`IStreamImpl::wire()`/`fixType()` stayed public and `[[nodiscard]]` while no external caller could name their
return type. Attribution was settled by bisect rather than inspection, per the CLAUDE.md rule: sofabgen
`b898ab4e` + corelib-cpp `80ec210` had run the full suite green an hour earlier, and the same sofabgen against
`d14b8ca` failed to compile — corelib-cpp was the only variable, so this was never a G-00NN. **No Crucible
change was warranted and none was made**; the next sofabgen CI build (`42a45893`) resolved it by emitting the
corelib's own `sofab::StringSeq`/`BlobSeq` helpers instead of the hand-rolled `_StrSeq`/`_BlobSeq` structs
that had carried their own guards. The §7.3 wire-type/subtype guard (generator#189, the F-0034/G-0019 family)
therefore **moved from generated code into the corelib** — which is precisely what let `Wire`/`Fix` become
internal — while the schema-only facts it needs (element cap, maxlen) are still passed in by the generated
call site (`sofab::StringSeq _r0{string_array, 5, 64}`). Recorded because the same shape will recur: a
corelib may absorb a guard that generated code used to own, and during the window between the two tips the
break looks exactly like a codegen defect.

**Full suite green — all eight gates, 13/13 drivers**, numbers identical to the 2026-07-25 run: seeds (6),
regression (97, 4 known soft `incomplete_value` warnings), conformance (3), cross-encode (90 probe + 18
union), union (11), limit mode (arr 3 / str 2 / blb 2 across the heap-only 10), structural sweep (744 vectors
over 7 blocking axes incl. wiretype §7.3 at 319), materialize (90 + 0/90 C-anchor mismatches) — **0
divergences** throughout; report-only framing (14) and the union pass (130 over 5 axes) likewise clean.
**Open findings unchanged:** **F-0031/ts** still quiets fp32 sNaN (generator#235 not in `42a45893`),
**F-0033** still splits the family three ways on scalar over-width (documentation#26), **F-0030** still not
in-tree reproducible.

**corelib-c-cpp#111 read properly — the §7.3 change is covered, a §7.3 × §7.4 product was not.** An earlier
draft of this entry claimed the change might be untested here. That was written off the commit *subject* and
is **wrong**: "a contradicting field is skipped, not an error" replaces a `SOFAB_RET_E_USAGE` abort with the
§7.3 skip, which is exactly what `wiretype_sweep` enumerates over 319 vectors — the green axis is a real
convergence result for `c`, not an absence of evidence. Reading the commit body did surface a genuine gap, and
upstream names it themselves: the same PR fixed a second bug where a wrapper sequence, which resets its slots
on open (§7.4 replace-whole), was **emptied by a contradicting occurrence it should have skipped** (`["A"]` →
`[]`), plus the same shape on a sized blob via `used_len` — "caught by the generator's C conformance run, **not
by this suite**".

**Gap closed — `sweep_repeated_id` gains the §7.3 × §7.4 product (16 → 136 vectors; sweep 744 → 864).** The
two rules were each swept alone and never together: this axis repeated only *validly typed* fields, and
`wiretype_sweep` mistypes only a *lone* field, so no vector ever gave a position a value and then re-sent its
id with a contradicting wire type. The new family does exactly that, in both orders, over the positions whose
destination is touched **before** the read is bound (`_PRE_BIND_CATS`: wrapper sequences, sized/`welem`
strings and blobs) — a scalar is bound and nothing more, so the istream can unbind it after the fact with no
trace, which is the same reasoning `object.c`'s own comments give for guarding these two branches and not the
others. Constructs come from `wiretype_sweep.CONSTRUCTS` rather than a second literal list, per WP-11's
one-model rule; the runner learned the `skip` expectation label (accept-equivalent, like `merge`/`replace`).

**Validated by mutation, not by a green light.** A new test that passes proves nothing when the bug it targets
is already fixed, so both guards in `vendor/corelib-c-cpp/src/object.c` were disabled in turn and the c driver
rebuilt: the sequence guard yields **20 divergences** (`c` alone against the other 12 — `c` re-encodes the
wrapper as `c6 0c 07`, empty, where the family keeps `c6 0c 02 …`), and the sized-blob guard another **20** at
`10_id3`, with the `used_len` corruption visible in the re-encoding (`561a23dead0000…`). Only the
`valid_then_skip` order fires, which is the discriminating result: with the valid occurrence last the clobber
is overwritten and invisible. Both mutations reverted, corelib clean, full sweep green.

**Second bump wave, same session — the whole family drops its usage error; four more drivers follow.** A
re-bootstrap a few hours later moved eight corelibs (c-cpp `eb663d7`, cs `101c025`, dart `b1107ab`, java
`ab419ad`, rs `8e5a374`, rs-no-std `a180676`, ts `fee1f9f`, zig `56f11e0`; cpp/go/py unchanged, sofabgen still
`42a45893`). What corelib-c-cpp#111 started is now family-wide: corelib-cs#42, corelib-rs#35,
corelib-rs-no-std#55, corelib-zig#23, corelib-java#49, corelib-dart#20 and corelib-ts#73 all remove the
`usage` error as unreachable. Four drivers referenced it and stopped compiling — `drivers/rust/driver.rs`
(`Error::Usage`, one source for both variants), `drivers/cs/Driver.cs`, `drivers/java/Driver.java`,
`drivers/zig/driver.zig` — treated exactly like c/cpp above, except that zig's `switch` is exhaustive over the
error set, so there the arm had to *go* rather than merely fall through. `drivers/python/driver.py`'s
`"SofaStateError": "usage"` is left alone: it is a different corelib concept and corelib-py has not moved.
Six of eleven corelibs now cannot produce the class; it stays in `oracle/canonical.md` while any can.

**The dart/java/ts "unbalanced sequence end" change is invisible to this harness by construction — it is
encode-side.** Three of the eight commits read "stop rejecting an unbalanced sequence end", which looks
verdict-relevant from the subject alone; the full suite showed 0 divergences and the report-only framing axis
(§5.2 stray-end, 14 vectors) was unchanged. The commit bodies explain why, and it is structural rather than
lucky: *"the **encoder** no longer rejects an unbalanced sequence end … Every other port writes the byte and
lets the decoder judge the bytes; only dart, java, ts and py refused it at encode time."* Crucible decodes and
re-encodes an already-decoded value, which is always balanced, so it never asks a corelib to *write* an
unbalanced sequence. This is the standing encoder-side gap in `docs/TODO.md` ("the pacemaker is decode-only"),
now with a concrete instance attached. Note corelib-py was named as the fourth hold-out and has not moved yet.

**One-hour pacemaker round after the second wave — 0 new signal.** 84.17 M execs at 23,373 exec/s (the
2026-07-25 round managed 38.55 M at 10.7k/s, so roughly double the coverage for the same wall clock), cov 621
/ ft 4434, 453 new units, **0 ASan/UBSan hits**, `corpus/crashes/` unchanged at 6 files that all pre-date the
round. Corpus 546 → 890. Differential + `oracle/cluster.py` over 890 inputs: 362 agree, 528 diverge → **10
root-cause clusters** (12 before, consistent with F-0028/F-0029/F-0032 having been resolved). Exactly one is a
hard `accept_value` split, and it was checked rather than assumed: cluster 7's representative is `00 ff 7f`,
**byte-identical** to `findings/F-0033-…/u8_over_16383.bin`, with F-0033's three camps intact (c/cpp-c-cpp
reject; cpp/cs/go/rust×2/zig mask to width; dart/java/py×2/ts keep the full value). The other nine are
`I`-vs-`R` verdict splits — the INVALID-vs-INCOMPLETE precedence hole — plus the 489-input java
`incomplete_value` soft cluster that also surfaces as the regression gate's four warnings; those nine were
mapped **by shape, not byte-verified** against their catalogued reproducers. **No new finding.**
`results/CLUSTERS.md` was *not* rewritten by this run and still holds the 2026-07-17 snapshot.

**The spec checkout is not bootstrapped — and reading it retired a carve-out and opened a spec PR.**
`scripts/bootstrap.sh` refreshes only its `CORELIBS` list plus `tools/sofabgen`; **`vendor/documentation` is
in neither**, so while eleven corelibs were pulled to same-day tips the spec sat at `0894035` (2026-07-19),
five commits behind `f512349` (2026-07-24). That is the one input the repo's own rules depend on most —
`CLAUDE.md` requires every `oracle/policy.yaml` entry to cite a clause, and sweep axes carry carve-outs worded
"until the upstream clause lands" — so a landed clause can sit unnoticed while the suite reports green. Two of
the five commits were exactly that: **documentation#25** (`c77f72a`, varint minimality §4.1) and
**documentation#27** (`2e5bc40`/`33f2259`, fp32 sNaN bit-exactness §6.5, which strengthens F-0031 — it now
requires bit-exactness at *every* fp32 position and on *every* decode surface, naming the double-only
languages). documentation#26, F-0033's hole, is still open.

**`sweep_varint` hardened: agreement-only → conformance-asserting (23 → 25 vectors).** §4.1 now mandates
accept-and-normalize for a non-minimal-but-≤64-bit varint, so the ground-rule-6 carve-out
(`expect="agree"`, filed as documentation#24) is retired: those vectors carry `expect="accept"` and the runner
asserts accept-vs-reject on them — a family that agreed on *reject* would have been green before and is a
finding now. §4.1 also sharpened the 64-bit bound into two **encoding-level** halves, and the axis gained the
case the old one structurally could not build: its `pads()` capped padding at `MAX64_BYTES = 10`, so an
**11-byte encoding of a representable value** (`5` padded, every surplus bit zero — `INVALID` anyway, because
the test is on the encoding) was unreachable, as was a **10-byte encoding whose tenth byte carries payload
above `0x01`** (bits at position ≥ 64, inside the byte-count limit). A decoder bounding by accumulated value
rather than byte count passes the old axis and fails both. All 13 conform. Sensitivity checked the same way as
the §7.3 × §7.4 work: flipping one non-minimal vector's expectation to `reject` produces three
`NONCONFORM … expected R, all 13 emit A` — the assertion is live, not decorative.

**documentation#28 opened — `UsageError` removed from CORELIB_PLAN §6.3.** Reading §6.3 surfaced a
spec-vs-implementation inversion: the table still lists `UsageError` ("a type mismatch on read"), but that case
is not an error at all any more — MESSAGE_SPEC §7.3 makes it a skip — and nine ports removed the code as
unreachable on 2026-07-25/26, corelib-cpp#54 going as far as renumbering rather than leave a hole. The spec was
the only place it still existed. The PR drops the row, moves its two surviving conditions (a scalar width that
is not 1/2/4/8, a nonexistent descriptor field type) into `InvalidArgument`, and states where a
type-mismatched read now lands. If it lands, the `usage` reject class can leave `oracle/canonical.md` too —
the reason it is still there is that this table still listed it.

---

# Decision log & deviations (moved from ARCHITECTURE.md)

These dated decisions, PLAN-deviations, and the first-finding narrative used to live
in `ARCHITECTURE.md`. Per the SSOT split (ARCHITECTURE describes only the current as-built state),
the *when/why* history belongs here with the rest of the chronological log; the
resulting *what-is* stays in ARCHITECTURE.

## Key decisions (decision log)

- **2026-08-18 — the Kotlin target lands as TWO drivers, because "multiplatform" is the
  thing worth testing.** sofabgen grew a `kotlin` backend (generator#340, its 11th) and
  `corelib-kotlin-mp` joined the family, so `drivers/kotlin/` was built and the roster went
  from fifteen rows to **seventeen**. The decision was how many rows, not whether to have any.
  A Kotlin Multiplatform library is one `commonMain` codec compiled for several platforms;
  registering only `jvm` would have tested it as "a second Java port" and left the entire
  reason the library exists — that the same source produces the same bytes on unlike
  runtimes — outside the harness. The little-endian word access is an `expect`/`actual`
  (byte-array `VarHandle`s on the JVM, indexed shifts through LLVM on Kotlin/Native), so the
  two legs are genuinely different machine code over one design: the `drivers/rust/`
  situation (one `driver.rs`, two corelibs) one level up, and the same answer — one source,
  two roster rows, and any divergence between them a bug by construction. **What that cost,
  concretely:** exactly one file per target, the IO shim (`io_jvm.kt` / `io_native.kt`),
  because common Kotlin has no API for the environment, for binary stdin or for stdout and
  nothing else in a replay driver is platform-bound. The verdict mapping, the chunking, the
  three encode surfaces and the materialized walk are shared verbatim.
  **Two build decisions worth recording.** (1) The *corelib* is built by its own Gradle build
  (`jvmJar` / `linuxX64MainKlibrary`), never by hand-compiling its sources with `kotlinc`,
  which was the tempting shortcut: `build.gradle.kts` pins the JVM target, `-jvm-default=no-compatibility`
  and the native target list, and a driver linked against a differently-compiled corelib is
  not testing the artifact the project ships. The *driver* is compiled directly with
  `kotlinc`/`kotlinc-native`, for the reason `drivers/java/build.sh` calls `javac` — a
  driver is a handful of files against a built library and should not carry a build system.
  (2) `kotlinc-native` is **not** in the standalone `kotlinc` (its `bin/` is jvm/js/wasm
  only); it lives in the separate Kotlin/Native distribution, which Gradle will provision on
  demand. The image now carries it — and, separately, warms the LLVM + sysroot dependencies
  it fetches *lazily on first compile* by building a hello-world — because otherwise the
  first CI gate to touch the native leg downloads ~2 GB mid-run.
  **The materialized walker is generated, not reflected**, joining the rust/cpp/zig/dart camp
  rather than java's. Kotlin has property reflection only on the JVM (`kotlin-reflect`), so
  reflecting would have meant a second walker for the native leg — the one thing having a
  shared driver is for.
  **Validation (PLAN §13.6), all green on the first run, no divergence anywhere:** seeds 6,
  structured 111, conformance 8, regression 239, union 11 and all four limit dimensions ×
  17 drivers; the materialized oracle 111 × 17 with the C anchor still 0/111 against the
  reference; every sweep axis on both the probe and the union schema; the encode gate 111 ×
  9 configs on both legs; chunk invariance 6 × 311 chunkings on seeds and 239 × 6 on the
  regression corpus, `SOFAB_CHUNK_SCRUB` included (nothing borrows from a fed chunk). Then
  the real test for a new implementation — the **19157-input fuzzed corpus**, clustered
  against `results/known-clusters.txt`: 8898 agree, 10259 diverge into **one** root-cause
  camp, the known benign `incomplete_value` split, with both Kotlin legs **inside** the
  existing camp. No new camp. That last point is the finding of the day and it is a
  negative one: a brand-new independent implementation, dropped into a corpus grown by
  fuzzing eleven others, produced not one novel disagreement.
  **The one behaviour it did change** is a soft axis: on `INCOMPLETE` the Kotlin ports hand
  back the partial value they had already read, as `java` does, so the `incomplete_value`
  camp is now three drivers wide rather than one. Both names were written into the baseline
  row — not required (cluster.py matches a row on the drivers it names), but a row that
  under-describes its own camp produces a per-run note nobody can act on, and recording them
  arms the check that matters: a Kotlin leg *leaving* that camp now reads as NEW.
  **Not done, and deliberately:** the `js` and `linuxArm64` legs (docs/TODO.md). The JS one
  is the interesting remainder — Kotlin/JS has neither a native 64-bit integer nor an fp32
  value type, the shape that has produced findings in every other double-only port.

- **2026-08-18 — the image's JVM is Temurin 21, and the Kotlin toolchain rides on it.**
  `.devcontainer/Dockerfile` gained the toolchain for **corelib-kotlin-mp**, the new Kotlin
  Multiplatform corelib: Gradle 8.14.5, `kotlinc` 2.4.10 and `KONAN_DATA_DIR`. The part worth
  logging is not the additions but the JDK swap they forced. That repo is built by Gradle
  (its wrapper pins **8.14.5**), and Gradle 8.x **refuses to start** on the JDK the image had —
  Ubuntu 26.04's `default-jdk` is **JDK 25**. Two ways out: a second JDK used only by Gradle,
  or one JDK for the whole image. **One JDK, and it is Temurin 21** — the LTS corelib-kotlin-mp's
  own devcontainer and CI leg use. A side JDK would have to be selected by every entry point,
  and the canonical one is `./gradlew`, which reads `JAVA_HOME`/`PATH` like everything else: the
  "only for Gradle" split would have been one env var away from silently building on 25 again.
  Making it image-wide costs nothing measurable on the other side — corelib-java compiles to
  `release 17`, so `drivers/java/` cannot tell 25 from 21, and **Jazzer**, the fuzzing framework
  both JVM drivers share, tracks the LTS line rather than the newest release. One trap found
  while verifying: the Temurin package does **not** win `update-alternatives` against the distro
  JDK, so `/usr/bin/java` still reports 25 and only the explicit `JAVA_HOME`/`PATH` (at
  `/opt/java-current`, the arch-suffix symlink) decides what a build actually gets — a version
  check that reads `java -version` from a login shell without that PATH would report the wrong
  answer. `kotlinc` is installed next to Gradle for the same reason `drivers/java/build.sh` calls
  `javac` directly: Gradle builds the corelib, a driver is a couple of files compiled against its
  jar and should not carry a Gradle project of its own. Both versions are pinned to what that repo
  declares (wrapper version, `kotlin("multiplatform")` version) — a driver compiled by a newer
  `kotlinc` than the corelib fails on metadata version, which reads like a corelib bug and is not
  one. **Verified by running it, not by reading it:** the Dockerfile's steps were executed on the
  same `ubuntu:26.04` base and `./gradlew build` on corelib-kotlin-mp@main went green across all
  three legs it configures on Linux — JVM, JS on Node, and Kotlin/Native `linuxX64` (which pulls
  its own ~2 GB LLVM into `KONAN_DATA_DIR` on first use, which is why that cache is pinned out of
  the mounted workspace). **No Kotlin driver yet, and it cannot exist today**: `sofabgen --lang`
  offers `c|cpp|csharp|dart|docs|go|java|python|rust|typescript|zig` — there is no `kotlin`
  backend, so the roster, `drivers/roster` and the gates are untouched by this change.

- **2026-07-28 — `count` is a capacity: the spec contradiction I found, and the suite
  re-pointed at the answer.** The static audit against the POC branch surfaced that
  `oracle/materialized.md` and §5.1 disagreed about a `count: N` wrapper's length. Tracing it
  showed the disagreement was *inside the spec family*: `sofabuffers-schema-v1.json` has always
  defined `count` as *"Capacity (maximum element count) … the wire may carry 0 .. count
  elements"*, while MESSAGE_SPEC §3 declared a `count: N` array "fixed-length with exactly N
  logical elements" and compensated with trim-on-encode / fill-on-decode. The owner confirmed
  capacity as the intent; **documentation#31** (merged into #29 as `ad8c9d0`) rewrites §2/§3/§5.1
  around one idea — *the wire carries the length, and nothing that carries it may be elided*:
  the compact form's `M` **is** the length (no trim, no fill), a wrapper's length is *highest
  present id + 1* whether or not a `count` is declared, and one sparse rule covers both element
  kinds (interior default → id gap; **last** element always written, as an empty frame for a
  sequence element). Crucible was re-pointed the same day, deliberately **ahead of the corelibs
  and the generator**, so the suite can measure their convergence instead of ratifying whatever
  they happen to do: `gen.py` (leaf + struct wrappers, `_leaf_elements`), `materialize.py` (no
  padding anywhere), 9 new `cap_*` value vectors, the `b_*` conformance pair inverted (the two
  array forms are now *different values*, each round-tripping to itself) plus three `e_wrapper_*`
  vectors, and `sweep_empty_frame`'s element expectations. **The affected gates are expected red
  until the family follows** — that is the point, and `corpus/conformance/README.md` says so.
  Two consequences worth their own note: **F-0010's shipped resolution is superseded** (the
  `_trim_tail`/`_pad_to` pair of generator#136 / sofabgen 0.17.2 must be rolled back), and
  **F-0036 inverted** — keeping a trailing all-default element is now correct, so the 12
  implementations that keep it are right and `c` alone is wrong (corelib-c-cpp's
  `_field_is_default` elision over-reaching from §2 fields into array elements); generator#248
  was filed against the wrong side and is corrected in-thread. `engine/structured/audit_canonical.py`
  joins the repo as the static property checker that found the original contradiction — it
  re-derives canonicality from the bytes rather than from `gen.py`, so it can catch a reference
  encoder that is itself wrong, and it carries a negative control (an interior empty element is
  reported, a gap and a last-index empty are not).
- **2026-07-27 — POC spec audit: the suite retargeted to `omit-all-default-sequences` §2,
  and WP-05 completed.** The POC spec inverted §2's sequence rule (an all-default
  sequence-typed *field* is omitted; an empty frame there is non-canonical, accepted,
  normalized away; the all-default message is zero bytes) and made the empty frame's
  meaning position-dependent (array wrapper = explicit empty; struct/union field =
  absence; array *element* = present, counted). Coverage added against each rule:
  `gen.py`'s reference encoder is POC-canonical (it framed unconditionally — the old
  §2; `000_00_defaults.bin` is now the empty byte string; corpora regenerated, three
  wire-duplicate vectors retired: `arr_empty`, union `u16_zero`/`text_empty`), a new
  **blocking sweep axis `sweep_empty_frame.py`** enumerates the §2 denotations at every
  sequence position (empty frame / frame-only→0-byte re-encode / §7.4 empty-merge /
  default-element-only wrappers / zero-count compact arrays / a frame between real
  fields, plus the union §4.2 identity-loss corners in the union pass), and
  `corpus/conformance` gained the byte-exact pairs (`a_ctl_omitted`, `d_empty_frame_only`)
  with its README rewritten to the POC meaning (the `a` vector's bytes are unchanged;
  its assertion flipped with the spec). **WP-05 landed**: F-0030's fix is in the poc
  corelib-c-cpp, so `struct_array` (id 202) joined `probe` — the `struct_wrapper` walk
  in all 9 driver walkers + the reference, new positions in the ONE position model, 8
  `sw_*` value vectors, and the three sequence-ELEMENT vectors (interior empty frame
  kept; trailing trimmed; interior gap restored) that §2's most dangerous rule (element
  presence carries length) had no coverage for. A dormant policy carve-out
  (`bounded-lazy-seq-depth-noncanonical-frames`, CORELIB_PLAN §6) records the legal
  bounded-hold-back divergence before anyone trips it (`SOFAB_LAZY_SEQ_DEPTH` = 8 vs
  `probe`'s depth 3). Deferred with corrected analysis in `TODO.md`: WP-08(c) needs a
  *dynamic* defaulted array (probe-dyn, not `struct_array` — a fixed-count array has no
  empty value), the §5.1 dynamic trailing-element rule likewise, and a lazy-depth sweep
  needs a deeper schema.
  **The new element-position coverage found three real POC-family defects on its first
  run** — **F-0035** (10 backends append struct-array elements id-blind, corrupting the
  decoded value on id gaps/reopens; the generated leaf-element path places by id in the
  same file), **F-0036** (12 of 13 never trim a trailing all-default sequence element on
  re-encode, §3/§5.1; only `c` normalizes via its F-0030 fix), **F-0037** (the generated
  C++ decode leaves a phantom default element after a §7.3 mistyped-skip inside the
  wrapper; once F-0036 lands this is only visible to the materialized oracle) — all
  three codegen (G-0020/21/22), minimal reproducers + controls in `findings/`, the
  affected sweep cells carved out per the F-0034 pattern with the finding id at each
  carve. One Crucible-side fix fell out: the **C materialize walker** projected a
  struct wrapper at its fixed capacity (5 all-default objects) where the family
  reports container length — `md_slot_empty` in `drivers/c/driver.c` now recurses
  into SEQUENCE slots (mirroring the corelib's `_field_is_default`), and the
  materialized gate is green at 97×13 with the C anchor at 0/97.
- **2026-07-27 — the vendored family follows *this checkout's branch*, not `main`.**
  The `omit-all-default-sequences` change lands family-wide on a same-named branch in
  every corelib and in the generator before it lands on `main` (spec side:
  `documentation@spec/omit-all-default-sequences`). Comparing Crucible's branch against
  `main` corelibs would measure the transition, not the family, so `scripts/bootstrap.sh`
  now resolves a **`FAMILY_BRANCH`** — defaulting to Crucible's own branch
  (`GITHUB_HEAD_REF`/`GITHUB_REF_NAME` first, since Actions checks out detached) — and
  fetches every corelib and the generator to it, falling back to `main` per repo,
  announced, when a repo lacks it. On `main` behaviour is unchanged, so the gates keep
  their conformance meaning. Two supporting rules: each corelib is moved with `checkout
  -B <ref>` so `vendor/<lib>` never *names* a branch other than the one it holds, and on
  a non-`main` branch the **release fallback is suppressed** — the generator publishes
  its `sofabgen-<os>-<arch>` artifacts on `main` only, so bootstrap builds the branch
  from source (Go) instead of silently pairing `main` codegen with branch corelibs, a mix
  whose divergences would all be artifacts of the mix. First run: 11 corelibs at the poc
  tips, sofabgen built from generator `d694117`.
- **2026-07-27 — a cached venv is a stale corelib: `drivers/python/build.sh` reinstalls
  corelib-py when the vendored source moves.** The venv was created behind an `if [ ! -x
  venv/bin/python ]` guard, and `pip install <path>` is a *copy*, so the Python drivers
  kept testing whichever corelib-py was vendored when the venv was first built. The
  branch switch exposed it: both Python drivers rejected all 6 seeds
  (`Encoder has no attribute write_sequence_begin_lazy` — poc codegen against a
  pre-poc corelib-py), i.e. 12 "divergences" that were a stale build, not a family
  disagreement. This is the same trap the 2026-07-15 bump hit and cleared by hand with
  `rm -rf drivers/python/build/venv`. The install is now stamped and refreshed when
  `src/`, `pyproject.toml`, or `setup.py` is newer — the rule the Java driver already
  applied to its jar. Every other driver regenerates and rebuilds per run.
- **2026-07-22 — `SOFABGEN.md` moved `docs/` → `results/`.** The G-00NN codegen-defect
  log is the generator-side sibling of `results/FINDINGS.md` (corelib bugs); Crucible's
  triage splits every finding into exactly those two catalogs by owning repo, so they now
  live together under `results/` (the "what the fuzzer surfaced" tree), leaving `docs/` for
  harness design/plan/status. All references rewritten in the same change (README, CLAUDE.md
  incl. the triage table, ARCHITECTURE/STATUS/TODO, FINDINGS, and the `findings/*/NOTES.md`
  that cite G-numbers).
- **2026-07-18 — drivers build with strict UTF-8 ON (F-0004 / crucible#55).** The
  fuzzer runs the §8 `SOFAB_STRICT_UTF8` check ON so an invalid-UTF-8 `string` is
  rejected family-uniformly. Most drivers are strict by default (go/zig/cpp default
  ON; py/ts/java/cs/rs Unicode types always strict); the **C corelib defaults OFF**
  for footprint, so the two corelib-c-cpp-based drivers opt in: `drivers/c/build.sh`
  and `drivers/cpp/build.sh` (`c-cpp`) add `-DSOFAB_ENABLE_STRICT_UTF8` and compile
  `corelib-c-cpp/src/utf8.c` (defines `sofab_utf8_valid`). The **zig** driver builds
  the corelib as a bare module with `zig build-exe` (no `build.zig`), so it
  synthesizes the `build_options` module corelib-zig's `utf8.zig` imports
  (`strict_utf8 = true`). Seeds: `engine/structured/utf8_seeds.py`.
- **Separate repo, arena-cloned structure.** Instrumented (sanitizer+coverage)
  vs arena's optimized builds; opposite configs → own repo. See PLAN §2, §11.
- **One coverage pacemaker (C), N differential oracles.** PLAN §3.
- **Purpose-built driver ABI, not the generator CLI.** Persistent + canonical
  diff form, not process-per-input JSON. PLAN §7.
- **The oracle is disagreement, not the crash.** PLAN §1, §6.
- **Name:** `crucible` (`corelib-*` is reserved).
- **2026-07-08 — comparator has no driver registry.** Drivers are passed to
  `comparator.py` as `name:path`; adding a language needs no central edit, only a
  `--driver` flag in `run.sh` (mirrors arena's "impls discovered from output").
- **2026-07-08 — bring up on a minimal schema, not full-scale.** Fastest path to
  a proven loop, canonical form, and comparator. See Deviation 2026-07-08a.
- **2026-07-08 — Rust: capture the corelib's verdict, not the generated API's.**
  The generated Rust `decode` was infallible; testing it verbatim would make Rust
  ACCEPT everything and flood the comparator with codegen-artifact divergences.
  The driver originally read the corelib's true `feed` result via a two-pass
  (null-visitor verdict + `decode` value), isolating wire semantics from the
  codegen's error-handling gap (results/FINDINGS.md G-0001). **Superseded
  2026-07-14 (crucible#10):** G-0001 is fixed — the driver is now single-pass on
  the fallible `try_decode`, which surfaces the verdict directly *and* runs the
  real generated per-field checks the null-visitor pass had skipped (e.g. the
  over-count-array check; F-0003 / generator#100 — **fixed in sofabgen 0.16.1**,
  re-verified 2026-07-15: clean over-count array → rust `R`).
- **2026-07-08 — generated-code weaknesses go to results/FINDINGS.md.** Building the
  Rust drivers surfaced four (G-0001 infallible decode; G-0002 std/no-std invalid
  UTF-8; G-0003 std/no-std chunked strings; G-0004 no-std silent capacity drop);
  the C++ drivers a fifth (G-0005 infallible C++ decode). Crucible tests corelibs,
  but codegen ships to users, so codegen defects are tracked as generator changes,
  not worked around silently. (Python's generated `decode` *raises* — the
  fallible model G-0001/G-0005 propose for Rust/C++.)
- **2026-07-08 — comparator is crash-isolating.** A driver that dies mid-stream
  (fewer output lines than inputs) is reported as `[CRASH] driver X on input N`
  and the run continues comparing the survivors, instead of aborting the whole
  differential. Necessary once the pacemaker feeds adversarial inputs — a
  crashing implementation (F-0003) is itself a finding, not a harness failure.
- **2026-07-15 — comparator is hang-isolating (per-driver timeout).** Companion to
  crash isolation: a per-driver wall-clock budget (`--timeout`, default
  `max(30s, 0.25s × corpus size)`; `TIMEOUT=` env through `run.sh`/`run-limits.sh`).
  `run_driver` sends the driver's stdout/stderr to temp files (not pipes) so that on
  a `subprocess` timeout — which on POSIX does *not* carry the killed process's
  partial output — the flushed lines are still recovered; the culprit is the input
  at index `len(lines)`, reported `[TIMEOUT] driver X hung … culprit ≈ input N`.
  `cluster.py` recovers past it exactly like a crash. A driver that takes unbounded
  time on a small malformed input is a **DoS finding**, not a wedged run (the
  gap the structure-aware mutator surfaced: maxed array counts / deep nesting made
  the replay loop crawl). Precision note: exact for flush-per-line drivers; a
  slurp-then-emit driver (ts) yields 0 partial lines, so it reports "hung, produced
  0/N" without a precise index — bisection to localize those is a follow-up.
- **2026-07-08 — canonical form v1: round-trip re-encoding.** Replaced the v0
  per-field text form with `A <hex(encode(decode(input)))>`. Reason: the full-scale
  message (arrays, nested structs, unions) makes per-field walking in 12 languages
  intractable and error-prone; re-encoding the decoded value is schema-agnostic
  (drivers reference no fields) and identical across the family because the
  encoders are sparse-canonical (the arena reference-wire invariant). Also gives
  the round-trip oracle for free. Tradeoff (benign masking of encode-equivalent
  differences) recorded in `oracle/canonical.md`. This is what surfaced F-0002.
- **2026-07-13 — canonical form v2: three-valued verdict (`A`/`I`/`R`).** Added a
  third verdict line `I` (INCOMPLETE) alongside `A`/`R`, tracking the finish-less
  MESSAGE_SPEC §7 decode model (documentation PR #12). Truncated input is
  INCOMPLETE — a distinct, non-error outcome — not accept and not reject. Touched
  the canonical-form triad together (the CLAUDE.md invariant): the grammar +
  three-verdict table in `oracle/canonical.md`, the `parse()`/compare logic in
  `oracle/comparator.py` (new `incomplete_value` axis, soft), and the driver
  contract in `drivers/common/CONTRACT.md`. `policy.yaml` gains
  `incomplete_value: soft` and resolves the PLAN §8 truncated-input question
  (SPECIFIED as INCOMPLETE). Drivers emit `I` only once their corelib exposes the
  state (generator#86 + per-corelib issues); until then F-0001 stays red — the
  correct signal. Verification tracked in crucible#8. See Deviation 2026-07-13a.
- **2026-07-08 — Python: build the Cython extension per interpreter.** The
  prebuilt `_speedups.so` is version-specific; a mismatched CPython silently falls
  back to pure, so "cython" mode would be a false label. build.sh compiles the
  extension for the venv's interpreter and asserts `sofab.IMPL` matches the
  requested mode.
- **2026-07-16 — the regression corpus admits an input only when it is green *for
  the reason the finding is about*.** The tempting rule is "a finding is fixed →
  its reproducer joins the gate." That is wrong here, because several reproducers
  are raw fuzzer inputs that trip **two** axes: F-0003's `array_overflow.bin` is
  over-count *and* truncated, F-0008's `hang_min.bin` is over-index *and*
  truncated. Both findings are fixed, yet both inputs still split the family on the
  *open* INVALID-vs-INCOMPLETE precedence hole (documentation#15). Admitting them
  would force a choice between a red gate and a policy exception that mutes a real
  open divergence. So a contaminated reproducer stays in `findings/` and the gate
  gets a **clean isolate** (`engine/structured/isolates.py`) testing the one axis —
  the F-0004 lesson ("characterize with a minimal isolate, not a raw fuzzer input")
  applied to the gate. Corollary: **never weaken the gate to admit an input.** The
  exclusions and their reasons are listed in `corpus/regression/README.md`, so an
  excluded reproducer is visibly deferred rather than silently forgotten.

## Deviations from PLAN

### 2026-07-23d — float bit-pattern specials + integer gaps in the value corpus (WP-06)
- **PLAN says:** the cross-encode + materialized oracles run valid, value-rich messages so encoders and
  decoders are cross-checked on the value space wire-mutation misses (PLAN §6).
- **Change (docs/improvements.md WP-06):** `gen.py` gained **raw-byte fp support** (`fp32`/`fp64` accept
  bytes; `f32b`/`f64b` pin an exact 32/64-bit pattern — a Python float round-trip would canonicalize a NaN)
  and vectors for the previously-missing value corners: min/max **subnormal** f32+f64, **quiet-payload**
  NaN, **negative** NaN, **fp64 sNaN**, explicit **+0.0**, and unsigned **mid** values. `materialize.py`
  handles raw-byte fp (the element-access oracle already compares floats by raw bits). `gen.py` now clears
  stale `*.bin` before regenerating (vector indices shift as the set grows, and the committed corpus is
  replayed with `REGEN=0`). Corpus 75 → **90** vectors; cross-encode + materialized green (90×13 each).
- **F-0031 carved out:** an fp32 *signaling* NaN (`0x7F800001`) is quieted to `0x7FC00001` by
  `py-cython`/`typescript`/`dart` (double-backed fp32) where the other 10 (incl. `py-pure`) preserve it —
  §4.6 requires bit-for-bit, no normalization. Filed corelib-py#49 / corelib-ts#66 / corelib-dart#15; the
  `f32_snan` vector is held out of the green gate (`findings/F-0031`) until fixed.


### 2026-07-23c — union value space cross-encoded (WP-02 Part A)
- **PLAN says:** the cross-encode oracle (PLAN §6) runs valid, value-rich messages through the
  round-trip + decode-agreement oracle; `schema/` is the single source of the fuzzed message.
- **Change (docs/improvements.md WP-02 Part A):** `gen.py` gained `encode_union` + `union_vectors`
  (18 value-rich union vectors — each member at boundary values, `default_id`, tag+member+trailer
  combos) written to `corpus/structured-union/` via `gen.py --union`. `scripts/cross-encode.sh` runs a
  second **union pass** over `schema/probe-union.sofab.yaml` (rebuild the roster → probe-union →
  differential → restore probe binaries, the SCHEMA-switch discipline), gated by `replay.yml` (which runs
  `cross-encode.sh`). **18 × 13 → 0 divergences** — the union value space round-trips identically; blocking.
- **Part B deferred:** the union *materialized* (element-access) oracle is a scoped follow-up — the C anchor
  materializes a union out-of-the-box (form `{opt_id:value}` for every member), but the 6 runtime walkers
  (go/py×2/java/ts/cs) and 6 generated walkers (rust×2/cpp/cpp-c-cpp/zig/dart) plus `materialize.py` need
  `union`-node support (a ~12-walker sub-project). `oracle/materialized.md` gets the union form then.


### 2026-07-23b — harness hygiene: one position model, schema-derived bounds (WP-11)
- **PLAN says:** `schema/` is the single source of the fuzzed message; the sweep family
  enumerates a rule across every position of it.
- **Change (docs/improvements.md WP-11):** removes three silent-desync risks in the
  sweep harness — no coverage change beyond one gap closed:
  - **One position model.** `wiretype_sweep.py` carried its own parallel position list
    (29 entries, including the wrapper-**element** positions the shared
    `sweep_positions.POSITIONS` lacked — so wrapper elements were swept for §7.3 but not
    §4.6). The wrapper-element positions (`welem_str`/`welem_blob`) now live in
    `sweep_positions.POSITIONS` (27→29), and `wiretype_sweep` consumes it via a new
    `CAT_TO_CONSTRUCT` map. A schema change is mirrored **once**. Consequence:
    reserved-subtype (§4.6) now also sweeps the wrapper elements — its vector count rose
    110→**118** (+2 positions × 4 reserved subtypes), a **gap closed**; wiretype stays 319,
    every other axis unchanged (no count dropped — the WP-11 hard-fail guard).
  - **Schema-derived bounds.** `sweep_positions` read `count`/`maxlen` from bare literals
    (`5`/`64`/`32`/`4`); they now come from `_BOUNDS`, read from `schema/probe.sofab.yaml`
    (the single source). `materialize.py`'s `ARR_COUNT = 5` is now derived from the schema
    descriptor with a uniform-count assertion (fails loudly on a non-uniform schema
    instead of silently mis-padding). Committed `oracle/materialized-schema.json` unchanged.
  - **`STRUCT_CHILDREN`** for the `arrays` (id 100) scope now lists all eight numeric
    arrays (was two); the §7.4 merge-vs-replace test still samples the first two (two
    distinct child ids suffice to distinguish merge from replace — documented, not left
    ambiguous), the rest available for wider reopen tests.
  - **Doc drift:** the "all 12"/"12 drivers" mentions across `engine/structured/*.py`
    (13 since Dart) are swept.
- **Verified:** all six blocking sweep axes green post-refactor (reserved-subtype's +8
  wrapper-element vectors reject uniformly); emit counts identical or higher than before;
  derived bounds byte-match the old literals. Lands **before** WP-05's schema growth so
  the new composite-array field enters one position model, not two.

### 2026-07-23a — framing & format-ceiling sweep axis added (WP-04, report-only)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  schema position; a divergence is a finding.
- **Change (docs/improvements.md WP-04):** a seventh axis
  `engine/structured/sweep_framing.py` covering two malformation classes with no
  dedicated coverage — stray/unbalanced `sequence-end` (§5.2; `sweep_truncation` only
  emits *open* sequences) and the format ceilings ID_MAX / FIXLEN_MAX / ARRAY_MAX /
  MAX_DEPTH (§6.2). Over-ceiling values sit at **unknown field ids** and use **2³¹**
  (over the ceiling on every profile), and declare a huge size with **no payload** so a
  conformant decoder rejects at the header word and never allocates (the F-0013
  amplification discipline). Registered via `scripts/sweep.sh` **report-only** (the axis
  is not green — see below); `gen.varint`/`gen.py` primitives only, hand-built vectors.
- **Report-only, not blocking:** the axis found two divergences (ground rule 4 keeps a
  non-green axis report-only until every divergence is a catalogued finding):
  - **F-0028** — `cpp` + `dart` decoders accept a field id > ID_MAX (skip it) where 11
    reject; both check ID_MAX only on encode. → corelib-cpp#47 + corelib-dart#14.
  - **F-0029** — `typescript`'s `cursor` decode path reports INCOMPLETE for nesting past
    MAX_DEPTH (its `fast.ts`/`state.ts` paths enforce it; `cursor.ts` does not).
    → corelib-ts#65.
  Both corelib (format ceilings are schema-independent wire checks), not codegen. The
  stray-end, FIXLEN_MAX and ARRAY_MAX vectors are green across all 13. Promote the axis
  to blocking + gate the reproducers once the findings resolve (the F-0025/F-0026 arc).

### 2026-07-22d — non-minimal varint sweep axis added (WP-03; sweep gate 6→7 axes)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  schema position; a divergence is a finding, a spec-silent case is a spec hole (§8).
- **Change (docs/improvements.md WP-03):** a seventh sweep axis
  `engine/structured/sweep_varint.py` (§2 varint canonicality). A varint admits
  non-minimal forms (redundant continuation bytes adding zero high bits); `gen.varint`
  emits only minimal ones, so no corpus reached this class (F-0016 covered only the
  >64-bit overflow). The axis places a non-minimal varint at every varint **role**
  (field-id header, fixlen length word, array count, array element, and inside a skipped
  field) with minimal-accept controls and an overflow-reject contrast. Registered in
  `sweep_run.py` `AXES`, blocking in `scripts/sweep.sh`, gated by `replay.yml` (which runs
  `sweep.sh`). `gen.varint` is left untouched — it is the canonical reference encoder;
  the non-minimal forms are hand-built in the axis.
- **Blocking but agreement-only:** the spec is **silent** on a non-minimal-but-≤64-bit
  varint (CORELIB_PLAN §4.1 guards only overflow; MESSAGE_SPEC §2 constrains the encoder,
  not the decoder). Per ground rule 6 the 18 non-minimal vectors carry `expect="agree"` —
  the runner asserts only that all 13 agree (and, for free, that the round-trip normalizes
  them to the one canonical form), **not** accept-vs-reject conformance — until a clause
  lands. Filed [documentation#24](https://github.com/sofa-buffers/documentation/issues/24)
  proposing the observed consensus (accept + normalize; reject
  overflow). On adoption the vectors tighten to `expect="accept"` and the axis becomes a
  conformance gate.
- **Result:** green — all 13 accept every non-minimal varint and re-encode identically to
  the minimal canonical form; all 13 reject the overflow. 23 vectors, 0 divergences. No
  finding.

### 2026-07-22c — union pulled under the structural sweeps (WP-01)
- **PLAN says:** the sweep family (PLAN §6) enumerates each normative rule across every
  position of the fuzzed message; `schema/` is the single source of the fuzzed message.
  Union coverage was a separate differential suite (`run-union.sh`) over 11 static seeds.
- **Change (docs/improvements.md WP-01):** the `union` wire feature — previously invisible
  to the generated pipeline (`engine/structured/schema.py` raised `ValueError` on `union`) —
  is now swept. `schema.py` learned the `union` kind; `sweep_positions.UNION_POSITIONS` is
  **derived from that descriptor** (not a second hand-maintained position literal); five axes
  (wiretype §7.3, repeated-id §7.4, over-bound §7.1, reserved-subtype §4.6, truncation §7)
  gained an `emit_union` pass; `sweep_run.py` gained `--union`; `scripts/sweep.sh` runs a
  **report-only** union pass that rebuilds the 13 drivers to `probe-union`, runs the axes, and
  rebuilds back to `probe` (the SCHEMA-switch discipline, so binaries are never left mixed).
- **Why a second schema, not folded into `probe`:** `probe` is byte-canonical and stable;
  a union member selected by id does not fit the fixed-shape `probe` cleanly, so the union
  lives in its own `probe-union` schema (the same reasoning `run-union.sh` already used). The
  sweep now parameterizes the position model *by schema* to reach it — a step toward WP-11's
  one-position-model goal, taken here rather than adding a third parallel literal.
- **Report-only, not blocking:** ground rule 4 (a new axis is report-only until green or every
  divergence is catalogued). 4 of 5 axes are green over 13; the wiretype pass surfaced
  **F-0027** (`rust-nostd` cannot §7.3-skip an array/fp64 field `probe-union` never declares —
  sofabgen provisions the no-std corelib's cargo features from the schema's *used* wire types).
  Primary attribution **generator (G-0017)**, corelib-rs-no-std implicated. The pass is not
  promoted to blocking and its vectors are not in `corpus/regression/` until the fix lands.
- **Result:** 130 union vectors; `probe` sweeps unchanged (still six blocking axes, green).
  `replay.yml` unchanged (the union pass is report-only, wired only into `sweep.sh`).

### 2026-07-22b — Dart added as the 11th corelib / 13th driver (roster 12→13)
- **PLAN says:** `drivers/` lists c/rust/go/java/python + cpp/cs/ts/zig (PLAN §11);
  onboarding a new language follows the §13 checklist.
- **Change:** `drivers/dart/` added (crucible#77 / generator#211, sofabgen's 10th
  language target). Roster is now **13 drivers / 11 corelibs**. Registered in every
  suite: `run.sh` (seeds/regression/cross-encode/union), `run-limits.sh` (heap
  roster), `engine/structured/sweep_run.py` (structural sweep), `materialize.sh`
  (element-access). No PLAN revision — this is the §13 checklist executed; PLAN's
  "N drivers" abstraction is unchanged.
- **Why it slots in cleanly:** the schema-agnostic round-trip form means the replay
  driver needs zero per-field code; the generated `Probe.tryDecode → DecodeStatus`
  maps 1:1 to `A`/`I`/`R`/`L`. Only the materialized oracle needs schema knowledge,
  supplied by a build-time-generated walker (AOT Dart has no `dart:mirrors`).
- **AOT, never JIT** — the suite runs the native `dart compile exe` binary, not
  `dart run`/VM (operator constraint).
- **CI:** the gates invoke the scripts (which carry Dart), so **no per-gate edit**;
  the CI image already installs the Dart SDK (`.devcontainer/Dockerfile`), so it only
  needs the standing one-time `image.yml` rebuild to carry it into `replay`/`nightly`.
- **Result:** all suites green — seeds 6×13, regression 73×13, cross-encode 75×13,
  union 11×13, limit mode (arr/str/blb) 10-heap-driver roster, structural sweep
  (5 blocking axes), materialized 75×13. No
  Dart-attributable finding. (One Crucible-side walker bug found+fixed during
  Stage 4; one toolchain-bump side-result: F-0025 now resolved on the CI build.)

### 2026-07-22a — bootstrap installs the latest sofabgen *CI build*, not the latest *release*
- **PLAN/prior as-built:** `scripts/bootstrap.sh` installed the latest published
  sofabgen **release** binary (checksum-verified) — see the `bootstrap.sh` row above
  as it was before this entry.
- **Change:** bootstrap now installs the binary the generator's `ci.yml` attaches to
  its latest **green run on `main`** (still sha256-verified, via the `.sha256` shipped
  in the same artifact). The tagged-release path is preserved but demoted to an
  explicit opt-in (`SOFABGEN_VERSION=vX.Y.Z`); it is also the **loud fallback** when no
  cross-repo token is present or the artifact is missing, so the tree never wedges and
  every run says which build it used.
- **Why:** the release cadence lagged behind merged generator work. The trigger was
  **Dart** (crucible#77): `corelib-dart` + the `dart` backend (generator#211) landed on
  generator `main` and CI began attaching a `dart`-capable `sofabgen` (target list now
  `…|dart|…`) and a `generated-dart` artifact — but no *release* carried it yet. Pulling
  the CI build lets Crucible exercise the newest family members as they merge, which is
  the whole point of a conformance fuzzer, without pinning to an *unmerged* PR (rejected
  — that would violate the "never lie about what it compiled" invariant).
- **Cost / caveat:** workflow-run artifacts are not anonymously downloadable, so CI needs
  a PAT secret (`SOFABGEN_TOKEN`, `actions:read` on `sofa-buffers/generator`) — wired into
  `replay.yml`/`nightly.yml`; absent it, CI degrades loudly to the latest release. CI
  builds carry a pseudo-version (`0.0.0-<ts>-<sha>`) rather than a semver tag.

### 2026-07-08a — Phase 1 used a minimal `probe` schema (RESOLVED in Phase 3)
- **PLAN says:** the fuzzed message is the "full scale" message (every width,
  arrays, nested structs, unions, unicode) — PLAN §13/§14.
- **Phase 1–2:** shipped a 4-field `probe` (u32/i32/fp32/string) to prove the
  loop, driver ABI, canonical form, and comparator without the full canonical-form
  surface area.
- **Resolved (Phase 3):** `schema/probe.sofab.yaml` is now the full-scale message
  (8 scalar widths, fp32/fp64, string, blob, 8 numeric arrays, nested fp arrays,
  string array). The switch to the round-trip canonical form (decision
  2026-07-08) made this a **schema+seeds-only change with zero driver edits** —
  the drivers reference no fields. Loop green across all 12 drivers on 6
  full-scale seeds. Kept the message key `probe` so generated type names are
  stable. Unions are the one full-scale feature not in this message (the family's
  full-scale example has none) — **covered separately** via
  `schema/probe-union.sofab.yaml` + `scripts/run-union.sh` rather than folded into
  `probe` (keeping the main message's type names stable). The schema-agnostic
  round-trip form pays off again: pointing the oracles at the union schema needs
  only a rebuild, no driver edits. All 12 backends generate + agree on every
  variant and the one-of/unknown-member edge cases — green, no finding.

### 2026-07-08b — absent/default/value collapsed to two states
- **PLAN says:** canonical form distinguishes *absent* / *present-but-default* /
  *value* (PLAN §7).
- **Reality:** the C object API and Go visitor API both materialize values with
  the schema default for omitted fields; on the sparse-canonical wire
  `absent == default`, so the two are equal and indistinguishable. Canonical form
  emits the value (default when absent).
- **Why:** both Phase-1 decoders are value-materializing; neither tracks presence.
- **Impact:** documented in `oracle/canonical.md`. When a presence-tracking
  decoder joins, the canonical form gains a presence marker and the comparator
  learns cross-model compatibility. No PLAN revision — PLAN §7's three-way
  distinction remains the target for models that support it.

### 2026-07-08c — C libFuzzer pacemaker not built in the bare workspace
- **PLAN says:** C pacemaker built with libFuzzer + sanitizers (PLAN §3, §12).
- **Reality:** the bare workspace has gcc but no clang, so only the gcc replay
  driver (with ASan/UBSan) is built/verified here. The libFuzzer front-end exists
  in `driver.c` behind `CRUCIBLE_LIBFUZZER` and builds in the devcontainer.
- **Why:** libFuzzer is a clang/LLVM feature; the devcontainer ships clang.
- **Impact:** none to the differential loop (which runs on the replay drivers).
  Coverage-guided pacemaker runs live in the devcontainer/CI.

### 2026-07-13a — canonical verdict is three-valued (`A`/`I`/`R`), not binary
- **PLAN says:** the canonical form's verdict axis is accept-vs-reject (PLAN §6/§7
  frame decode as a binary outcome).
- **Reality:** MESSAGE_SPEC §7 (finish-less, documentation PR #12) makes decode
  three-valued — COMPLETE / **INCOMPLETE** / INVALID — where INCOMPLETE (truncated
  but well-formed-so-far) is an explicit non-error outcome. The canonical form
  gained a third line `I` (`oracle/canonical.md` v2), the comparator a third
  verdict + a soft `incomplete_value` axis, and the driver contract an `I`
  mapping.
- **Why:** collapsing INCOMPLETE into accept (`A`) or reject (`R`) is exactly the
  F-0001 bug; the loop cannot verify the family's convergence on INCOMPLETE
  without a distinct verdict for it.
- **Impact:** verdict comparison now ranges over `A`/`I`/`R` (all hard). Drivers
  emit `I` only after their corelib exposes INCOMPLETE (generator#86 +
  per-corelib issues); until then their `A`/`R` on a truncated seed is a real
  verdict divergence. No PLAN revision needed — this refines §7's outcome model to
  match the now-settled spec. Verification: crucible#8.

### Pacemaker (as built)

`scripts/fuzz.sh` builds the C driver's `CRUCIBLE_LIBFUZZER` entry with clang
(`-fsanitize=fuzzer,address,undefined`) and runs it, seeded from `corpus/seeds` +
`corpus/interesting` + the findings reproducers; new coverage-increasing inputs
grow `corpus/interesting/`, crashes land in `corpus/crashes/`. Measured ~41k
exec/s, ~1M runs in 26s. It only decodes (coverage over the C decoder); the
discovered inputs then go through the differential loop
(`CORPUS=corpus/interesting ./scripts/run.sh`) where decode+re-encode across all
12 drivers finds the divergences. On its **first** run over 309 discovered inputs
it produced F-0003 (2 crashes) and a large divergence cluster dominated by F-0004
(string UTF-8) and F-0001 (truncated input) — findings 8 hand-seeds never reached.

Needs clang + `libclang-rt-dev` (in the devcontainer image); the comparator
(`oracle/comparator.py`) is **crash-isolating** — a driver that dies mid-stream is
reported as `[CRASH] driver X on input N`, not a bare harness abort, so the
pipeline survives a crashing implementation.

### Clustering (as built)

`oracle/cluster.py` (`CLUSTER=1 ./scripts/run.sh`) reduces the divergence firehose
to root causes: for each divergent input it partitions the drivers into
equivalence classes by identical output, drops the exact bytes, and keys the
cluster by the *shape* (which driver-set landed in each class, with its verdict).
Inputs sharing a shape share a root cause; clusters rank by size with a minimal
representative. It recovers past crashes (re-runs a crashed driver on the
remaining inputs). First run: 256 divergences → 47 clusters, top 12 ≈ 208, mapping
to F-0001/F-0004/F-0005 (+ the F-0003 crash cluster). Snapshot +
finding-mapping in `results/CLUSTERS.md`.

## Phase 1 note (moved from results/FINDINGS.md, 2026-08-03)

The loop found F-0001 on its **first run** over hand-written seeds — before any
coverage-guided or structure-aware fuzzing. That is the differential oracle
working as designed: a divergence no single-implementation fuzzer could report,
because no impl crashes — they simply disagree. Phase 2 (adding Rust, C++,
Python, Java, TypeScript, C#, and Zig) grew it from 1-vs-1 into a
7-accept-vs-5-reject **two-camp** split — four independent lineages (Go, Python,
TypeScript, Zig) reject where the C/C++/Rust/Java/C# camp accepts. That is exactly
the extra signal more implementations buy: a lone outlier is ambiguous; four
independent rejects point firmly at the answer — and the split cuts across the
systems/managed line, so it is a genuine per-decoder design difference.

## First finding

The Phase-1 loop found **F-0001** on its first run: a truncated trailing varint
(`80`, `ff ff ff`). Phase 2 grew it to a **7-accept vs 5-reject camp split** — the
C/C++/Rust/Java/C# camp (c-cpp, cpp, c-cpp wrapper, rs, rs-no-std, java, cs)
accepts it as the all-defaults message; **four independent lineages — Go, Python
(cython and pure), TypeScript, and Zig — reject it**. Real, hand-verified against
all twelve drivers. Notably Zig (a systems language) rejects while C/C++/Rust
accept, so the split is per-decoder-design, not systems-vs-managed. Four
unrelated implementations rejecting is strong evidence the lenient camp is wrong —
exactly the pressure the PLAN §8 spec decision needs.
See `results/FINDINGS.md` and `findings/F-0001-truncated-trailing-varint/`.

## Spec decisions (adopted MESSAGE_SPEC clauses)
- **§7** (finish-less, documentation PR #12) — decode is three-valued
  COMPLETE/INCOMPLETE/INVALID, returned identically by one-shot `decode` and every
  streaming `feed`. **There is no `finish`/`finalize`/`end`**, and **INCOMPLETE is
  an explicit non-error outcome** — whether a trailing INCOMPLETE is a truncation
  error is the caller's decision (its own framing: length prefix, datagram, EOF).
  A truncated message (e.g. a lone `0x80`) is INCOMPLETE, not INVALID. Family
  implementation: epic **generator#86** + 10 per-corelib issues; Crucible-side
  verification (third verdict `I`): **crucible#8**.
- **§8** — `string` is UTF-8, `blob` is opaque bytes; strict-reject is conformant but
  gated behind a corelib flag (`SOFAB_STRICT_UTF8`) that may default OFF; conformance
  + the fuzzer run it ON.
