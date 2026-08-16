# F-0056 — corelib-cpp re-parses a fixlen array's payload as a varint when a later field truncates

**Status:** ✅ **RESOLVED** — [corelib-cpp#71](https://github.com/sofa-buffers/corelib-cpp/issues/71) fixed by [corelib-cpp#72](https://github.com/sofa-buffers/corelib-cpp/pull/72), merged the same day — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.

**Found 2026-08-03** by re-clustering CI's 8512-input nightly corpus against the post-fix family.
It is the camp `c5d8b383`, which had resisted triage since the morning review: an earlier attempt
to rebuild it from its description did not reproduce, because the reconstruction guessed the fp32
*values* mattered. They do not — the **byte pattern** does. Minimized 62 B → **32 B** by the
batched delta-minimizer, then rebuilt as a 22-byte isolate.

## The isolate

`a6 06 56 05 03 20 ff×12 04 24 07 07` (22 B) — inside `arrays.nested`:

| bytes | meaning |
|---|---|
| `a6 06` `56` | open `arrays` (id 100), then `nested` (id 10) |
| `05 03 20` | id 0, **ARRAY_FIXLEN**, count 3, `fixlen_word` = fp32 / 4 bytes per element |
| `ff` × 12 | the 3 × 4 payload bytes. An fp32 has no continuation bit — but *read as a varint*, every one of these bytes has bit 7 set |
| `04 24` | id 0, ARRAY_SIGNED, count 36 — a §7.3-mistyped repeat, and the input ends here |

| verdict | drivers |
|---|---|
| `I` (**correct** — the message is truncated inside a field that must be skipped) | c, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, rust-no-std, rust-std, typescript, zig (12) |
| `R invalid_msg` | **cpp** (1) |

## What actually triggers it — the payload is read as a varint

Neither the float values nor the §7.3 mistyping matter. Two conditions do, and both are necessary.

A note on wording first, because it is the whole finding: **an fp32 has no continuation bit.**
Bit 7 marking "another byte follows" is a *varint* convention (§4.1); an fp32 element is four raw
IEEE-754 bytes with no such structure. That bit 7 of those bytes decides anything at all is not a
property of the data — it is the proof of the defect, because it means something is reading a
varint where a payload lies.

**1. Read as a varint, the payload must be an unbroken run of continuation bytes.**

| payload, ×3 elements | cpp |
|---|---|
| `ff ff ff ff` | `R` |
| `80 80 80 80` | `R` |
| `ff ff ff 7f` — a terminator every 4 bytes | `I` |
| `80 80 80 00` — a terminator every 4 bytes | `I` |
| `7f 7f 7f 7f` | `I` |
| `00 00 80 3f` (= 1.0) | `I` |

The float value is irrelevant; **bit 7 of each byte** is everything. `ffffffff` is a NaN and so
is `0000c07f` — but `0x7f` has bit 7 clear, so a varint reader stops there, and only the first
triggers. That is what ruled out the "NaN-ish payload" reading the camp was first filed under,
and it is why the values in the table below (`1.0`, `0x7f7f7f7f`) matter only for their bytes.

**2. The run must exceed 10 bytes**, §4.1's 64-bit varint bound:

| elements | payload bytes | cpp |
|---|---|---|
| 1 | 4 | `I` |
| 2 | 8 | `I` |
| **3** | **12** | **`R`** |
| 4, 5 | 16, 20 | `R` |

Two elements give an 8-byte continuation run, which is a *valid* varint prefix. Three give 12,
which is longer than any varint may be — so a decoder reading those bytes **as a varint** must
call it `INVALID` (§4.1). That is exactly what cpp reports, and the threshold falls exactly where
§4.1's bound does.

**Conclusion:** cpp is not decoding the array wrongly. It is *re-reading the array's payload from
the wrong offset*, as though those bytes were a field header, on the path taken when a later field
truncates. The over-count (36) is incidental — count 5 triggers it too. The mistyped repeat is
incidental — an **unknown** id (999), a different id, and a different wire type all trigger it
equally. The truncation is **required**: the same message with the trailing array complete is
accepted by all 13.

## Attribution — `corelib-cpp`

Parsing a `fixlen` array's payload and resuming after it is wire mechanics with no schema
involvement. The decisive control is the sibling profile: **`cpp-c-cpp` is correct**. Both are the
generator's C++ backend against the same schema; they differ only in the corelib underneath —
`cpp` uses corelib-cpp, `cpp-c-cpp` uses corelib-c-cpp. Same generated shape, one correct, one
not, so the defect is in the corelib rather than in codegen.

Candidate site, **not yet confirmed by instrumentation**:
`include/sofab/sofab.hpp:2270-2278`, the fixlen-array element loop —

```cpp
consumed_ = false;
const uint8_t *payload = p_;
if (!skipElem) cb(fieldId, fixLen_, count_);
if (!consumed_)
{
    p_ = payload;      // rewind to the payload …
    skipPayload();     // … and skip it by length
}
```

`p_` is rewound to the start of the payload whenever the callback did not mark it consumed. If
that path is also taken on the truncated-resume, the reader restarts inside the payload and the
next varint it reads is made of the element bytes. The 10-byte threshold is consistent with that
and with nothing else this axis produced.

## Resolution

Fixed by [corelib-cpp#72](https://github.com/sofa-buffers/corelib-cpp/pull/72) (`main` @ `48f06db`).
The inferred site was right, and the fix names the mechanism more precisely than this write-up
did: a nested `read()` that runs out of bytes returns **unconsumed**, exactly as a *declined*
field does, so a truncation fell into the decline path — `p_` rewound to a payload the callback
had already descended *through*, and `skipPayload()` re-read it under the metadata of whatever
innermost field the descent stopped at. `parseTopLevel` had guarded this all along
(`sofab.hpp:3133`); `dispatchLevel` never did. The fix bails out at the field's start when the
callback reported incomplete, before the decline-skip.

Verified 2026-08-03 against `48f06db`: all seven reproducers now agree with the 12-implementation
consensus — the three triggers moved `R` → `I`, the four controls unchanged. Full suite green
(nine gates, 1104 sweep vectors, `materialize.sh` 0/108). Promoted to the `corpus/regression/`
gate as `F0056_*` (181 → **188** inputs); the camp signature is deleted from
`results/known-clusters.txt`.

**An adjacent defect the fix deliberately left open** is filed as
[crucible#130](https://github.com/sofa-buffers/crucible/issues/130): `read(void *, size_t)`, the
raw blob read, sets `error_` rather than `incomplete_` on a short payload and drops the buffered
tail, so the message never completes. Reproduced against `48f06db`. It is invisible to this suite
twice over — generated code calls `readBlob()`, which is correct, and the replay driver feeds each
message **whole**, while the defect lives at a chunk boundary.

## Reproducers

| file | what it pins |
|---|---|
| `r0_corpus_minimum_32b.bin` | the corpus find, minimized 62 → 32 B; carries the original's §7.3 repeat and over-count |
| `r1_ff_run_n3.bin` | the 22-byte isolate: 3 × `ffffffff` |
| `r2_continuation_80_n3.bin` | the same with `80808080` — the value is irrelevant, the continuation bit is not |
| `ctl_n2_below_threshold.bin` | 2 elements = 8 continuation bytes, still a legal varint length → `I` on all 13 |
| `ctl_n3_terminated_every4.bin` | 3 elements, but a terminator byte every 4 → `I` on all 13 |
| `ctl_n3_ordinary_value.bin` | 3 elements of `1.0` → `I` on all 13 |
| `ctl_n3_ff_not_truncated.bin` | the same message with the trailing array complete → `A` on all 13 |

The four controls are what separate this from F-0046 (schema `count` applied to a kind-mismatched
array) and from F-0043 (a schema-bound verdict landing after the word): under either of those the
element count and the payload bytes would be irrelevant, and here they are the whole story.

## Why no gate caught it

`sweep_reserved_subtype` and `wiretype_sweep` both build fixlen arrays, but their payloads are
ordinary values — no axis emits an element payload made of continuation bytes, because no axis
had a reason to care what the *bytes* of a well-formed element look like. `sweep_varint` places
non-minimal and over-long varints at every varint **role**, but an fp32 element is not a varint
role, so it is never filled with one.

That is the product cell: *a payload that is not a varint, positioned where a decoder that
mis-seeks would read one.* Worth an axis of its own — a fixlen payload built from continuation
bytes, at every fixlen position, against a following truncated field — since it costs nothing to
emit and catches exactly the class of reader-position bug that no value-shaped vector can.
