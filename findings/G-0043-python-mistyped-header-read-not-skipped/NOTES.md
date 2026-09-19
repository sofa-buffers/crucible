# G-0043 — generated Python reads a header that contradicts the declared type instead of skipping it, in three visitor scopes (§7.3)

**Status:** ✅ **fixed in sofabgen `7470127`** — [generator#575](https://github.com/sofa-buffers/generator/issues/575) via generator#576, verified 2026-09-19; [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail, this file is the evidence.
**Guard:** wiretype_sweep — the size-graded mismatch family (`*_ARRbig_mism` / `*_ARRhdronly_mism` / `*_ARRpartial_mism`, at every position plus index 9 in each wrapper), blocking and green since the fix. The four reproducers are also in `corpus/regression` as `G0043_*`.
**Issue:** [generator#575](https://github.com/sofa-buffers/generator/issues/575)

**Found 2026-09-19** triaging nightly run 35320714690 (2026-09-18) locally, on the **main**
family: every corelib at `main`, sofabgen `0.0.0-20260918231252-6b375bfb7b1a` (generator
`6b375bf`), corelib-py `0.10.1` (`fbc48b8`). The nightly itself produced no cluster verdict:
its differential step failed to build the go driver (`sofab.WithPassThrough`, fixed on main
by `eac69af` after the run), so the camps below come from the local re-cluster of the merged
corpus (21421 inputs).

## The divergence

Two new camps in `corpus/interesting`, both **py-cython + py-pure against the other fifteen**:

| camp | inputs | isolate | others | Python |
|---|---|---|---|---|
| 1 | 2 (`76a83162…`, `984abe91…`) | `r1_nightly_partial_skip_buffered.bin`, 2190 B | `I` | `R invalid_msg` (`SofaArgumentError`) |
| 2 | 1 (`3232056b…`) | `r0_nightly_hdronly_skip_capped.bin`, 7 B `d60c9356ef9273` | `I` | `L` (`SofaLimitError`) |

Both inputs had been in the local corpus since August and were green against the previous
Python generation, so this is a **regression** from the move of generated Python onto the
corelib-py destination table (generator#561 `d4d7561`, corelib-py #149/#150/#152).
`run-chunked.sh --modes chunk,scrub` over the same corpus shows camp 1 from the other side:
fed whole it is `R`, fed in chunks (where the stream decoder's reassembly buffer is
`MAX_FIELD_SPAN + 65536`) it is `I` — 14 mismatches per Python engine, the same two inputs.

Decoded, both isolates are the same shape. `d6 0c` opens `struct_array` (id 202), and
directly inside the wrapper sits a field that is **not a sequence**: id 9 `ARRAY_SIGNED`
count 76 (camp 1, the 28th such array cut 71 bytes into its payload), and id 1378
`ARRAY_UNSIGNED` count 1886575 with no payload (camp 2). A struct element is framed as a
sequence (MESSAGE_SPEC §5.1), so each is a mistyped element, which §7.3 says to skip.

`r2_complete_elem_over_cap.bin` is the same mistake without any truncation: a **complete**
70007-byte message with one mistyped element carrying 70000 entries. Fifteen drivers accept it;
both Python engines raise `SofaLimitError`. `r2_ctl_complete_elem_small.bin` is its control
(3 entries), accepted everywhere: the element is read there too, but a small read is invisible.

## Attribution — generator (Python backend), established

The generated visitor's `on_field` is what decides skip-or-read, and it **accepts** these
headers; corelib-py then reads what it was handed, which is its documented contract.

- `drivers/python/build/gen/message.py`, scope `_L_Probe_struct_array`: the only decline is
  `fld.subtype >= FixlenSubtype.STRING`, then `return True`. The sibling scopes
  `_L_Probe_string_array` / `_L_Probe_blob_array` decline every header whose subtype is not the
  declared one.
- Emitter: `generators/python/visitor.go` at `6b375bf` — `arrFieldArm` (L901–922) gives a
  sequence-framed element kind only `textPayloadGuard("")`; `objFieldArm` (L841–879) gives no
  tag test to a wrapper-array field (`continue`, L861–866) or to a scalar/struct/union field
  (`default: continue`, L869–870) that is not on the destination table.
- corelib-py is correct: a field a visitor accepts is read (capped, and replayable, hence held
  in the reassembly buffer), and a single-chunk carry larger than the buffer is refused —
  pinned by `tests/test_reassembly.py::test_a_carry_larger_than_the_buffer_is_refused_on_the_way_out`.
  Its own skip route (`_DISCARD`, #139) never buffers and never caps; it is simply not reached.
- Confirmed by patching the generated `on_field` alone (decline every non-sequence header in
  the wrapper scope): both isolates turn `I`, `r2` turns `A`, on both engines.

**Refuted on the way** — recorded because each looked right for a while:

1. *corelib-py applies `max_dyn_array_count` to a skipped field.* Its `_skip_pending` drops a
   parked cap (`_LIMIT`, #128) explicitly; the cap fired because the field was never skipped.
2. *corelib-py holds more than one construct in the reassembly buffer* (a run of held-back
   sequence headers). The 71-byte carry is exactly the partial payload of **one** array:
   `wire[2119:]`, after its header and count word.
3. *This is generator#388's cap machinery.* It is not: the cap and the buffer both behave; the
   visitor routes a skip onto the read path.

## What the new sweep family found beyond the nightly

`wiretype_sweep` placed each §7.3 mismatch with a one-element body, which is exactly why this
stayed hidden: a small read is indistinguishable from a skip. The axis now carries the same
mismatch at three sizes at every position (complete over both default cap tiers; truncated at
the count word; truncated inside a payload far above any `MAX_FIELD_SPAN`), plus index 9 in each
wrapper. 18 vectors diverge, all Python-only, in **three** scopes, not one:

| positions | declared there | scope |
|---|---|---|
| `202_id0`, `202_id9` | a struct element (sequence) | wrapper scope (`arrFieldArm`) |
| `root_id200`, `root_id201`, `root_id202` | the wrapper-array field itself (sequence) | root visitor scope (`objFieldArm`) |
| `202_0_id0` | `k: u32` inside an element | element scope (`objFieldArm`) |

Root scalars and the `nested`/`arrays` structs are correct because they are on the destination
table, whose route checks the tag; the string/blob wrapper elements are correct because their
arm declines on subtype. generator#575 carries all three with a standalone reproducer
(`rows.sofab.yaml` + `repro.py` in this folder: ten cases, seven wrong before the fix, all `ok` with the
three-arm fix, round trip unchanged).

## Reproduce

```sh
FAMILY_BRANCH=main ./scripts/bootstrap.sh
python3 engine/structured/sweep_run.py wiretype_sweep        # 18 divergences (py-* only) before 7470127, 0 after
CLUSTER=1 CORPUS=findings/G-0043-python-mistyped-header-read-not-skipped ./scripts/run.sh
```

Standalone, against generated Python only:

```sh
tools/sofabgen --lang python --in findings/G-0043-*/rows.sofab.yaml --out /tmp/g43
PYTHONPATH=/tmp/g43 drivers/python/build/venv/bin/python findings/G-0043-*/repro.py
```

## Resolution — verified 2026-09-19

generator#576 (`7470127`, *"every visitor-handled position declines a header that contradicts
its declared type"*) closed generator#575 the same morning it was filed, and covers all three
scopes. Verified on the **main** family: every corelib at `main` (unchanged since the find),
sofabgen `0.0.0-20260919074829-7470127355ba` from generator CI run 35430323783 (sha256
verified), all 17 drivers:

| check | before | after |
|---|---|---|
| `repro.py` on `rows.sofab.yaml`, Cython and pure engines | 7 of 10 wrong | 10 of 10 `ok` |
| this folder's reproducers (`run.sh`) | 3 Python-only camps | 0 divergences |
| the three nightly inputs (`76a83162…`, `984abe91…`, `3232056b…`) | 2 camps | 0 divergences |
| `wiretype_sweep`, 471 vectors | 18 divergences | 0 divergences |
| `corpus/regression` (239) · seeds | green | green |

The reproducers are promoted to `corpus/regression` as `G0043_*`, and the three G-0043 rows
are gone from `results/known-clusters.txt`, so a return reads as a NEW camp.
