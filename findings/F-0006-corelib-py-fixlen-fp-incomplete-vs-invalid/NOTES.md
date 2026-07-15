# F-0006 — corelib-py: truncated wrong-length fixlen fp32/fp64 → INCOMPLETE (`I`) instead of INVALID (`R`)

> **✅ RESOLVED 2026-07-15.** Fixed on corelib-py `main` — the decoder now validates
> the fp32/fp64 fixed width (4/8) at the FIXLEN header (decoder.py L338-341), before
> the payload read, exactly as proposed. [corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)
> **closed**. Re-verified: `56 0a 59` and `56 02 38` → **all 11 drivers `R`** (py no
> longer the `I` outlier). The rest of this file is the original analysis.

**Status:** open — filed upstream as a **corelib-py** decoder bug. Surfaced
2026-07-15 while re-verifying findings after the sofabgen 0.16.1 + corelib-py@main
bump (corelib-py commit `e14e4ba` "decode resource limits + un-eager array
allocation", #31/#34).
**Found:** re-running the F-0005 reproducer (`56 0a 59`) — cpp is now fixed (rejects,
F-0005 resolved), but **corelib-py moved from `R` to `I`** on the same bytes.
**Axis:** verdict (hard, `oracle/policy.yaml`) — `I` (INCOMPLETE) vs `R` (INVALID).
**Affects:** `corelib-py` — **both** engines (`py-cython` native `_speedups` and
`py-pure`), i.e. the shared `src/sofab/decoder.py`, not codegen.

## The divergence (11 vs 1)

Input `56 0a 59` (3 bytes) — inside the `nested` sequence, field id 1 (`f64`) is a
FIXLEN whose length-header `0x59` declares **length 11, subtype FP64**. An FP64
FIXLEN must be **8** bytes, and **0** of the 11 declared payload bytes are present.

| verdict | drivers |
|---|---|
| **R** invalid_msg | c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, java, typescript, csharp, zig (10) |
| **I** (INCOMPLETE) | **py-cython, py-pure** (corelib-py) |

Same shape for fp32 — `56 02 38` (field id 0 `f32`, FIXLEN length 7 ≠ 4, subtype
FP32, truncated): 10 × `R`, corelib-py × `I`.

## Why `R` is correct (not `I`)

MESSAGE_SPEC §7: **INVALID = "malformed regardless of what follows"** and takes
precedence over INCOMPLETE (truncation). A FIXLEN whose subtype is FP32/FP64 has a
**mandatory fixed width** (4 / 8). A declared length that is not that width is
malformed *no matter what bytes arrive next* — no continuation can rescue an fp64
field that claims length 11. So the outcome must be **INVALID**, independent of
whether the payload is truncated. Ten independent implementations agree.

Two controls prove the wire interpretation and isolate the precedence:

- `control_A_wronglen_full.bin` = `56 0a 59` + 11 payload bytes + `07`
  (**not** truncated, length still 11 ≠ 8): **all 12 → `R`** — corelib-py *does*
  validate the width once the bytes are present.
- `control_B_validlen_trunc.bin` = `56 0a 41` (length **8**, valid) + only 3 of 8
  bytes: **all 12 → `I`** — a *correctly-sized* truncated fp64 is INCOMPLETE
  family-wide.

So the bug is strictly the **precedence** when the field is *both* wrong-width and
truncated: corelib-py lets INCOMPLETE win; the spec and the family make INVALID win.

## Root cause (corelib-py `src/sofab/decoder.py`)

The FIXLEN header parse (≈L323-353) reads `length`/`subtype` but does **not**
validate the fixed width for FP32/FP64 there — it only range-checks
(`subtype > BLOB`, `length > FIXLEN_MAX`) and stashes `_pending = (_FIXLEN,
subtype, length)`. The width check lives in the value readers:

```python
def float64(self):
    data = self._take_fixlen(FixlenSubtype.FP64)   # _read_exact(length) → SofaIncompleteError if truncated
    if len(data) != 8:                              # ← INVALID check, only reached if the payload was fully read
        raise SofaDecodeError("fp64 payload must be 8 bytes")
```

On a truncated payload `_take_fixlen` → `_read_exact(11)` raises
`SofaIncompleteError` **before** the `len(data) != 8` check runs — so INCOMPLETE
pre-empts the INVALID verdict. The fixlen-**array** path already does this
correctly, validating element width eagerly at header time (≈L597-614: *"the
fixlen_word must declare a 4-byte element width for fp32; reject …"*). The scalar
FIXLEN path is the inconsistent one.

## Fix (proposed, corelib-py)

Validate the fixed width at the FIXLEN **header** stage (decoder.py ≈L326, where
`subtype` and `length` are known), before any payload read — mirroring the
fixlen-array path:

```python
if subtype == FixlenSubtype.FP32 and length != 4:
    raise SofaDecodeError("fp32 fixlen length must be 4")
if subtype == FixlenSubtype.FP64 and length != 8:
    raise SofaDecodeError("fp64 fixlen length must be 8")
```

Then a wrong-width fp field is INVALID regardless of truncation, matching §7 and
the other ten implementations. STRING/BLOB keep their variable length (a truncated
string/blob is legitimately INCOMPLETE — do **not** eager-check those).

Upstream issue: **[sofa-buffers/corelib-py#38](https://github.com/sofa-buffers/corelib-py/issues/38)**.

## Secondary observation (not filed — needs its own isolate)

Sweeping the fp64 declared length `L` (subtype FP64, empty/truncated payload)
shows the **C-family** is also length-dependent here, so corelib-py is the
*systematic* outlier but not the only lenient one at some lengths:

```
L :  1   2   4   7   8   9  11  16      (verdict; 0 payload bytes)
c  :  I   I   I   I   I   R   R   I
ccp:  I   I   I   I   I   R   R   I      (cpp-c-cpp)
cpp:  R   R   R   R   I   R   R   I
go :  R   R   R   R   I   R   R   I
py :  I   I   I   I   I   I   I   I      ← always I: never width-checks before truncation
```

At L=9 and L=11 corelib-py is the *sole* outlier (all others `R`) — the clean
reproducers above. At other lengths c/cpp-c-cpp (and cpp at L=16) are also lenient
in a non-monotonic, not-yet-understood way. That broader
"fixlen-fp width vs truncation precedence" divergence is a **candidate follow-up**
(characterize with minimal isolates per the F-0004 lesson before filing) and may be
a MESSAGE_SPEC precedence clarification rather than a single corelib bug. corelib-py
is filed now because its behavior is fully root-caused and uniformly wrong for every
L ≠ 8.
