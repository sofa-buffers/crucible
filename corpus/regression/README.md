# `corpus/regression/` — the resolved-findings green gate

Every input here is a **reproducer for a finding that is now fixed**, and every input must
produce **0 divergences across all 13 drivers**. A divergence here means a resolved bug
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

## Contents (81 inputs)

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
| `F0016_u64_over_65bit.bin`, `F0016_u64_over_70bit.bin` | F-0016 | corelib-cpp#39 / go#48 / rs-no-std#45 / py#43 / ts#53 / java#41 / cs#37 | an overlong (>64-bit) varint (u64 whose 10th byte carries bits above 64) is `R invalid_msg` on **all 12** — no silent truncation, no value corruption |
| `F0016_control_u64_max.bin` | F-0016 (control) | — | the **counter-direction**: `2^64-1` (the valid maximum) is still accepted by all 12 — guards against over-rejecting at the boundary |
| `F0004_utf8_*.bin` (11) | F-0004 | generator#162 (sofabgen 0.18.0) + per-corelib strict-UTF-8; Crucible builds with the check ON | an invalid-UTF-8 `string` (overlong incl. `C0 80`, lone surrogate, `> U+10FFFF`, bare continuation / lone `0xFF`, truncated 2-/3-byte) is `R invalid_msg` on **all 12** — not the old 4-way raw/U+FFFD/empty/reject split |
| `F0004_control_utf8_valid_{2byte,3byte,ascii}.bin` (3) | F-0004 (controls) | — | the **counter-direction**: valid UTF-8 (`é`, `€`, ASCII) is still accepted and round-trips on all 12 — the strict check rejects only malformed bytes, never a lossy U+FFFD |
| `F0017_ts_wiretype_iso.bin` | F-0017 | generator#160 (sofabgen 0.18.0, PR #161) | a header whose wire type ≠ the field's declared type (`05 00 01`) is `R invalid_msg` on **all 12** — the generated TS decode frames each field by its header wire type (was `I` on ts) |
| `F0019_dup_struct_nested.bin`, `F0019_dup_struct_arrays.bin`, `F0019_dup_wrapper_replaced.bin` | F-0019 | MESSAGE_SPEC §7.4 (documentation#23) + generator#175 + corelib-c-cpp#99 | a field id repeated in one scope: a struct/union **merges** (last occurrence per id wins, scope continues), an **array wrapper is replaced** whole — all 12 agree (was 11-vs-1 on structs, 3-vs-9 on wrappers) |
| `F0019_control_dup_scalar.bin`, `F0019_control_same_field.bin`, `F0019_control_single_seq.bin`, `F0019_control_wrapper_single.bin` (4) | F-0019 (controls) | — | the cases that already agreed and must stay agreeing: a repeated scalar (last wins), the same child twice, both children in one opening, a single-open wrapper — guard against a merge/replace fix regressing them |
| `F0020_scalar_wrong_signedness.bin`, `F0020_struct_id_gets_scalar.bin`, `F0020_wrapper_id_gets_fixlen.bin` | F-0020 | MESSAGE_SPEC §7.3 (documentation#23) + generator#174 / corelib-c-cpp#100 / corelib-cpp#43 | a field header whose wire type ≠ its declared type is **skipped** as if the id were unknown — all 12 agree (was a 4-way skip / usage / invalid / mis-decode split) |
| `F0020_control_scalar_correct.bin`, `F0020_control_struct_correct.bin` (2) | F-0020 (controls) | — | a correctly-typed scalar and a correctly-typed struct still decode on all 12 — the skip fires only on a mismatch |
| `F0021_u8_recv_array_unsigned.bin`, `F0021_i8_recv_array_signed.bin` | F-0021 | generator#183 (sofabgen 0.19.3, PR #184) | a scalar field receiving an integer array of the same signedness is **skipped**, not decoded from the array's element — all 12 agree (was decoded by rust-std/rust-nostd/csharp/java/zig, the shared-callback backends) |
| `F0021_control_legit_array.bin` | F-0021 (control) | — | a legitimate `u8` array at an actual array field still stores on all 12 — the skip does not touch real arrays |
| `F0022_arru8_recv_scalar.bin`, `F0022_arri8_recv_scalar.bin`, `F0022_arrfp32_recv_scalar.bin` | F-0022 | generator#188 (sofabgen 0.19.4) | an **array-declared** field (`u8[]` / `i8[]` / `fp32[]`) receiving a bare scalar of its element type is **skipped**, not stored as a one-element array — all 12 agree (was decoded by rust-std/rust-nostd/csharp/java/zig, the shared-callback backends) |
| `F0022_control_arru8_correct.bin`, `F0022_control_scalar_at_scalar.bin` (2) | F-0022 (controls) | — | a legit `u8` array at the `u8[]` field, and a legit scalar at a scalar field, still store on all 12 — the skip fires only on the array-field←scalar mismatch |
| `F0023_strelem_recv_fixlen_blob.bin`, `F0023_strelem_recv_fixlen_fp32.bin`, `F0023_strelem_recv_scalar_signed.bin`, `F0023_strelem_recv_sequence.bin` | F-0023 | generator#189 (sofabgen 0.19.4) | a mis-typed `string_array` **wrapper element** (blob / fp32 / signed scalar / sequence where a `string` is declared) is **skipped** per §7.3 — all 12 agree (was ts/py reject, cpp mis-accept a blob as the string, cpp-c-cpp reject a subtype mismatch) |
| `F0023_control_strelem_correct.bin` | F-0023 (control) | — | a correctly-typed `string` wrapper element still decodes into the array on all 12 — the skip fires only on a mis-typed element |
| `F0024_repro_invalid_utf8_then_trunc.bin` | F-0024 | generator#190 (sofabgen 0.19.4) | an input that is **both malformed and truncated** (invalid UTF-8 then cut short) is `R invalid_msg` on all 12 — INVALID dominates the truncated tail per §5.2, not the old rust-only `I` |
| `F0024_control_invalid_utf8_complete.bin`, `F0024_control_valid_complete.bin`, `F0024_control_valid_then_trunc.bin` (3) | F-0024 (controls) | — | the axes that isolate ordering from validation: a complete-but-invalid input is `R` (detection works), a complete valid input is `A`, a valid-but-truncated input is `I` (a clean truncation must still surface as INCOMPLETE, not be forced to `R`) |
| `F0025_fp32_scalar_recv_array.bin`, `F0025_fp64_scalar_recv_array.bin` | F-0025 | generator#193 (post-0.19.4 sofabgen) | a **scalar fp field** (`nested.f32` / `f64`) receiving an fp **fixlen array** is **skipped** per §7.3, not decoded from the array's element — all 12 agree (was decoded by rust-std/rust-nostd/csharp/java/zig; the fp analogue of F-0021, which #183 fixed for integers only) |
| `F0025_control_fp32_scalar.bin`, `F0025_control_array_field.bin` (2) | F-0025 (controls) | — | a correctly-typed fp scalar, and a legit fp array at the actual array field, still store on all 12 — the skip fires only on the fp-scalar←fp-array mismatch |
| `F0026_blob_reopen_empty.bin`, `F0026_blob_reopen_two.bin` | F-0026 | corelib-c-cpp#106 (`2416a2b`) | a re-opened `blob_array` wrapper (§7.4 replace) drops the earlier occurrence's element on **all 13** — the C object API's `sofab_object_init` now resets a sized blob's companion length, so no stale zeroed element survives |
| `F0026_control_blob_single.bin`, `F0026_control_str_reopen.bin` (2) | F-0026 (controls) | — | a single (non-reopened) `blob_array` element, and a `string_array` reopen (never buggy), still agree on all 13 — the reset touches only the sized-blob reopen path |

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
| `F-0018/embedded_nul.bin` | **by-design allowed divergence** (not a bug). Embedded U+0000 is valid UTF-8 and accepted by all 12; the C object API stores strings NUL-terminated (`char[]` + `strlen`), so `c`/`cpp-c-cpp` project `A\0B` → `A` on re-encode while the other 10 preserve it. Sanctioned in `oracle/policy.yaml` (axis `accept_value`, MESSAGE_SPEC §8) — see `findings/F-0018` |
| `F-0003/array_overflow.bin` | the original is over-count **and truncated**, so rust reports `I` and the family `R` — that is the open precedence spec-hole ([documentation#15](https://github.com/sofa-buffers/documentation/issues/15)), not the over-count axis the finding is about |
| `F-0008/hang_min.bin`, `hang_orig.bin` | the hang is fixed (generator#126) and they terminate, but both end mid-sequence, so py says `R` (eager) and the family `I` (lazy) — documentation#15 again |

(F-0004's original `invalid_utf8.bin` was the last exclusion here; it graduated in
2026-07-18 once the strict-UTF-8 check went ON family-wide — the 11 malformed-form
isolates above replace it.)

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

When a finding's fix lands (see [`docs/TODO.md`](../../docs/TODO.md)):

1. Re-run the reproducer through all 13 drivers and confirm **0 divergences**.
2. If it is green **for the reason the finding is about**, copy it here as
   `F<nnnn>_<name>.bin` and add a row above. If it is green only incidentally, or still
   splits on an unrelated open axis, write a **clean isolate** in `isolates.py` instead —
   do not weaken the gate to accommodate a contaminated input.
3. Flip the status in `results/FINDINGS.md` and note the promotion in `docs/STATUS.md`.
