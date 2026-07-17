# `corpus/regression/` — the resolved-findings green gate

Every input here is a **reproducer for a finding that is now fixed**, and every input must
produce **0 divergences across all 12 drivers**. A divergence here means a resolved bug
came back — that is the whole point of the directory.

```sh
CORPUS=corpus/regression ./scripts/run.sh        # must report 0 divergence(s)
```

Run in CI by `.github/workflows/replay.yml` on every push and PR, alongside the seed,
cross-encode, union, and limit-mode gates.

Until this existed, the resolved findings were verified only by ad-hoc replay of
`findings/<id>/*.bin` during a bump, with the results written up in prose in
`docs/STATUS.md`. That caught the 0.17.2 go regression (F-0011) only because someone was
looking. This corpus makes it automatic.

## Contents (26 inputs)

| file | finding | fixed by | the gate asserts |
|---|---|---|---|
| `F0001_dangling_varint.bin`, `F0001_garbage.bin` | F-0001 | MESSAGE_SPEC §7 (finish-less) | a truncated message is `I` on all 12 — not the old 7-accept/5-reject split |
| `F0002_i_negative.bin` | F-0002 | corelib-c-cpp#70 | no UBSan left-shift on a negative value; all agree |
| `F0003_overcount_clean.bin` | F-0003 | generator#87 + #100 (sofabgen 0.16.1) | a clean over-count array (8>5) is `R` on all 12 — no crash, no rust-only accept |
| `F0005_cpp_accepts_malformed.bin` | F-0005 | corelib-cpp#22 | corelib-cpp does not accept what the family rejects |
| `F0006_*.bin` (4) | F-0006 | corelib-py#38 | a wrong-width fixlen fp is `R`, validated at the header, incl. both controls |
| `F0007_*.bin` (3) | F-0007 | corelib-c-cpp#82 | the C istream checks the exact fp width (4/8), not `length > target_len` |
| `F0009_blob_short.bin`, `F0009_blob_zero.bin` | F-0009 | generator#128 (0.17.1) | a sub-`maxlen` / all-zero blob round-trips instead of being padded or dropped |
| `F0010_u32_count3.bin`, `F0010_i16_count1.bin` | F-0010 | generator#136 (0.17.2) + corelib-c-cpp#87 | an under-count array round-trips to the canonical count 3 / count 1 |
| `F0011_empty_arrays.bin`, `F0011_undercount_siblings.bin` | F-0011 | generator#139 (0.17.3) | an all-default `count:N` array is omitted (§2), not emitted as `<hdr> 00` |
| `F0014_c_family_subtype_string.bin`, `F0014_py_fp32_size0.bin`, `F0014_ts_reserved_subtype.bin` | F-0014 | corelib-c-cpp#89 + corelib-py#41 + corelib-ts#51 | an `ARRAY_FIXLEN` element word is validated **at the header**: a non-fp32/fp64 subtype, a wrong element width, and a reserved subtype are each `R` on all 12 — not `I` on whichever impl skipped that check |
| `F0015_string_40_over_maxlen32.bin`, `F0015_blob_8_over_maxlen4.bin`, `F0015_strarray_elem_70_over_maxlen64.bin` | F-0015 | MESSAGE_SPEC §7.1 (documentation#20) + sofabgen 0.17.5 | a `string`/`blob` over its schema `maxlen` is `R invalid_msg` on **all 12** — the bound binds every target, not just the ones whose buffer happens to be too small |
| `F0015_control_string_within_maxlen32.bin` | F-0015 (control) | — | the **counter-direction**: a value *within* `maxlen` is still accepted by all 12 — guards against over-rejecting |
| `F0013_overindex_clean.bin` | F-0013 | generator#142 (0.17.4) + #149→#151/#150 (0.17.6) | a `string_array` element at index ≥ the schema `count` is `R invalid_msg` on **all 12** — heap and fixed-capacity alike; no silent drop, no DoS |

Filenames are `F<nnnn>_<original-name>.bin`; the originals stay in `findings/<id>/` as the
finding's own record. `F0003_overcount_clean.bin` has no original — see below.

### Expected warnings (not failures)

Three inputs raise a policy-`soft` `incomplete_value` warning: on an `I` verdict, `c` emits
no partial value where `java` emits the default skeleton. That axis is `soft` in
`oracle/policy.yaml`, so the gate still exits 0. Divergences — not warnings — are the
signal.

## What is deliberately NOT here

A reproducer only belongs here once it is **green for the right reason**. These are
excluded, each because the family still legitimately splits on it:

| excluded | why |
|---|---|
| `F-0004/invalid_utf8.bin` | **open finding.** The 4-way UTF-8 split waits on the `SOFAB_STRICT_UTF8` epic (spec §8 / generator#85) |
| `F-0003/array_overflow.bin` | the original is over-count **and truncated**, so rust reports `I` and the family `R` — that is the open precedence spec-hole ([documentation#15](https://github.com/sofa-buffers/documentation/issues/15)), not the over-count axis the finding is about |
| `F-0008/hang_min.bin`, `hang_orig.bin` | the hang is fixed (generator#126) and they terminate, but both end mid-sequence, so py says `R` (eager) and the family `I` (lazy) — documentation#15 again |

The last two are the reason `F0003_overcount_clean.bin` exists: F-0003's fix is real, but
its *kept* reproducer cannot demonstrate it, because the input tests two axes at once. The
clean isolate tests the over-count axis alone. It was quoted only as prose hex in
`STATUS.md` / `FINDINGS.md` until this corpus made it a file — the F-0004 lesson
(characterize with a minimal isolate, not a raw fuzzer input) applied to the gate itself.

Both clean isolates are generated by `engine/structured/isolates.py`, which imports the wire
primitives from `engine/structured/gen.py` (the one reference encoder) so a format change
cannot silently desync them:

```sh
python3 engine/structured/isolates.py .    # idempotent; the committed bytes are the contract
```

## Adding to this corpus

When a finding's fix lands (`TODO.md` "Verify fixes as they land"):

1. Re-run the reproducer through all 12 drivers and confirm **0 divergences**.
2. If it is green **for the reason the finding is about**, copy it here as
   `F<nnnn>_<name>.bin` and add a row above. If it is green only incidentally, or still
   splits on an unrelated open axis, write a **clean isolate** in `isolates.py` instead —
   do not weaken the gate to accommodate a contaminated input.
3. Flip the status in `results/FINDINGS.md` and note the promotion in `docs/STATUS.md`.
