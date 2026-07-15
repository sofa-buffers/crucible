# F-0007 — INVALID-vs-INCOMPLETE precedence on inputs that are *both* malformed and truncated

**Status:** open — **spec-precedence question** (candidate MESSAGE_SPEC clarification),
not a single-repo bug. The one cleanly-isolated, single-culprit instance is split
out as **[F-0006](../F-0006-corelib-py-fixlen-fp-incomplete-vs-invalid/NOTES.md)**
and filed as [corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38).
**Found:** 2026-07-15, clustering the grown `corpus/interesting` after the sofabgen
0.16.1 + corelibs@main bump — now the dominant hard-divergence family (see
`results/CLUSTERS.md`), having displaced the resolved F-0005.
**Axis:** verdict (hard) — `R` (INVALID) vs `I` (INCOMPLETE).

> **Update 2026-07-15 — family narrowed to the C corelib.** With F-0006 fixed
> (corelib-py#38 closed), corelib-py now returns `R` on `56 0a 59` / `56 0a 09`, so
> the py slice collapsed. The remaining outlier is the **C corelib**: on
> `56 0a 09` (fp64 len 1, truncated) **c and cpp-c-cpp emit `I`** while the other 9
> emit `R` — a clean 2-driver / 1-corelib (corelib-c-cpp) isolate. Root cause: the
> C istream checks the declared fixlen length only against the destination buffer
> capacity (`length > target_len`), not the fp exact width — see the Root cause
> section. **Filed [corelib-c-cpp#82](https://github.com/sofa-buffers/corelib-c-cpp/issues/82)**
> (the direct analogue of the closed corelib-py#38). Remaining: the MESSAGE_SPEC §7
> precedence clause so the whole family shares a spec basis. Minimal isolates:
> `cfamily_fp64_len1_trunc.bin` (`56 0a 09`), `cfamily_fp32_len2_trunc.bin` (`56 02 10`).

## The divergence

When an input is **simultaneously malformed** (a field header that can never be
valid — e.g. a fixlen fp with a length ≠ its fixed width, a bad wire-type, an
over-long count) **and truncated** (the stream ends before the field's declared
payload), implementations disagree on the verdict depending on **which check their
decoder runs first**:

- decoders that **validate the field header eagerly** report `R` (INVALID) —
  malformed regardless of what follows (MESSAGE_SPEC §7);
- decoders that **try to consume the payload first** hit end-of-input and report
  `I` (INCOMPLETE) before ever validating the header.

Per §7, **INVALID = "malformed regardless of what follows" and must take
precedence** — so `R` is the intended verdict. But the family has not converged,
and the camps are **input-dependent** (no single impl is always the outlier), which
is why this is a spec/precedence issue rather than one corelib's bug.

## Minimal isolates (both in this dir)

Both are a `nested` sequence opening a fixlen **fp64** field (id 1) whose declared
length ≠ 8, with the payload truncated to 0 bytes — malformed *and* truncated.

| input | I-camp (say INCOMPLETE) | R-camp (say INVALID) |
|---|---|---|
| `56 0a 59` (len 11) — `py_fp64_len11_trunc.bin` | py-cython, py-pure | **10 others** |
| `56 0a 09` (len 1) — `cfamily_fp64_len1_trunc.bin` | c, cpp-c-cpp, py-cython, py-pure | go, rust-std, rust-nostd, cpp, java, typescript, csharp, zig (8) |

Controls (prove the wire semantics; see F-0006): a *correctly-sized* truncated fp64
(`56 0a 41` + partial) is **`I` everywhere** (legitimate INCOMPLETE); a wrong-width
fp64 that is **not** truncated (`56 0a 59` + 11 bytes + `07`) is **`R` everywhere**.
So the disagreement is strictly the **precedence** when both conditions hold.

The full fp64-length sweep (declared length L, empty payload):

```
L :  1   2   4   7   8   9  11  16
c  :  I   I   I   I   I   R   R  (I)
ccp:  I   I   I   I   I   R   R  (I)
cpp:  R   R   R   R   I   R   R  (I)
go :  R   R   R   R   I   R   R  (I)
py :  I   I   I   I   I   I   I  (I)   ← (pre-#38) was always I; now R for L≠8
```

**L=16 is a red herring, not a data point:** its length-header is `(16<<3)|1 =
0x81`, a *multi-byte* varint (continuation bit set), so `56 0a 81` truncates
*inside the length varint itself* → every impl says `I` (truncated varint), for a
reason unrelated to the fp width. Drop it, and the C corelib is **monotonic**: `I`
for declared length ≤ 8, `R` for ≥ 9.

## Root cause — corelib-c-cpp (the shared C istream)

`corelib-c-cpp/src/istream.c`, `_DECODER_STATE_FIXLEN_LEN` (≈L711-732): after
reading the fixlen length-header the decoder validates the declared `length` only
against the **destination buffer capacity**, not the fp type's exact width:

```c
if (length > ctx->target_len) {      // target_len = sizeof(dest): 8 for fp64, 4 for fp32
    return SOFAB_RET_E_INVALID_MSG;   // only the UPPER bound is checked
}
```

For an fp64 field `target_len == 8`, for fp32 `== 4`. So a declared length that is
`≤ target_len` but `≠` the exact width passes this gate, the decoder sets
`fixlen_remaining = length` and reads the payload; if the payload is truncated the
feed ends mid-field → **INCOMPLETE**. A declared length `> target_len` (≥9 for
fp64, ≥5 for fp32) is correctly `INVALID` here, before any payload read.

The missing check is the **exact** width: for FP32/FP64 the wire length must be
*exactly* 4/8 — a length of 1..7 for fp64 (or 1..3 for fp32) is malformed
*regardless of what follows* (§7 INVALID), so it must be rejected at the header,
before truncation can turn it into INCOMPLETE. This is the **same bug class as the
now-closed corelib-py#38**; corelib-py deferred the check entirely (I for all L≠8),
the C corelib checks only the `≤ buffer` upper bound (I for L≤8, R for L≥9).

Confirmed on both widths (truncated, 0 payload; go = exact-width reference):

```
fp32 (target_len=4):   L= 1  2  3 | 4 | 5  7      fp64 (target_len=8):  L=1..7 | 8 | 9,11
  c / cpp-c-cpp        I  I  I | I | R  R                               I..I  | I | R  R
  go (and family)      R  R  R | I | R  R                               R..R  | I | R  R
```

**Fix (corelib-c-cpp):** at `_DECODER_STATE_FIXLEN_LEN`, for `SOFAB_FIXLENTYPE_FP32`
reject `length != 4` and for `FP64` reject `length != 8` as `INVALID`, before the
payload read — the exact-width analogue of the `length > target_len` bound already
there, and the direct C counterpart of the corelib-py#38 fix. (STRING/BLOB keep the
buffer bound — they are variable-length, so a truncated string/blob is legitimately
INCOMPLETE.)

Larger multi-field instances of the same family are the three old
`corpus/crashes/` artifacts (Jul 8), which **no longer crash** under 0.16.1 and now
land here as `c=R` vs others=`I` verdict splits — but they are not minimal isolates.

## Disposition

- **F-0006 (corelib-py)** is the clean, root-caused, single-culprit slice (py is the
  *sole* outlier at L=9/11, with an exact code location) — **filed** upstream.
- **The rest** (C family lenient at small L; typescript the lone `I` on some larger
  inputs; various camps) needs **minimal per-impl isolates** before filing anything
  (the F-0004 lesson: characterize with a minimal isolate, not a raw fuzzer input),
  and most likely a **MESSAGE_SPEC precedence clause**: "when a field is both
  malformed and truncated, the verdict is INVALID." That spec clarification would
  turn each remaining camp membership into a concrete per-corelib bug. Track like
  F-0001/F-0004 (spec-first), not as a scattershot of issues.

## TODO before filing more

1. Add a MESSAGE_SPEC §7 precedence clause (INVALID > INCOMPLETE) — upstream
   documentation repo.
2. Per corelib in the `I`-at-wrong-L camp, minimal-isolate its decoder's
   check-ordering and file individually (corelib-py already done → #38).
3. Consider a `policy.yaml` note once the spec clause lands (verdict stays hard).
