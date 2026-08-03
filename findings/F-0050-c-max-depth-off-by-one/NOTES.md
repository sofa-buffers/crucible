# F-0050 — `corelib-c-cpp` permits nesting depth **256**, one past `MAX_DEPTH` (255)


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-08-02** by the **Go steering engine** on its first run — one of two divergence
classes the C pacemaker never produced across ~370 M execs over the same schema (see
`results/CLUSTERS.md`, the Go-steered snapshot).

## The rule

CORELIB_PLAN §6.2 fixes `MAX_DEPTH = 255`, §4.9 makes exceeding it `INVALID`, and §5.2 lists
*"nesting past `MAX_DEPTH`"* among the conditions that are malformed **regardless of what
follows** — so it outranks `INCOMPLETE` even when the input is also truncated:

> **Truncation is _not_ `InvalidMessage`** … but input that is *both* malformed and truncated
> *is*: `INVALID` takes precedence over `INCOMPLETE` (§5.2).

## The measurement

Depth is built as one `SEQ_BEG` for `nested` (id 10) plus *n−1* further opens, optionally
closed by *n* end markers.

| vector | depth | closed | 11 others | **c, cpp-c-cpp** |
|---|---|---|---|---|
| `ctl_depth255_complete` | 255 | yes | accept | accept ✅ |
| `ctl_depth255_truncated` | 255 | no | `I` | `I` ✅ |
| **`r1_depth256_truncated`** | 256 | no | `R invalid_msg` | **`I`** ❌ |
| **`r2_depth256_complete`** | 256 | **yes** | `R invalid_msg` | **accept** ❌ |

`r1` is byte-identical to the input the Go engine found (256 B).

**`r2` is the one that settles the diagnosis.** It is fully closed — no truncation anywhere —
and the C family still **accepts** it, re-encoding to the empty message. So this is not the
INVALID-vs-INCOMPLETE precedence bug the truncated vector alone would suggest (the F-0007 /
F-0012 / F-0014 class). The depth ceiling is simply enforced one step too late.

## The bound, measured exactly

Sweeping depth 254…271 through `c`:

```
254:A  255:A  256:A  257:R  258:R  …  271:R
```

`c` accepts up to **256**; the spec allows **255**. A clean **off-by-one** — not a missing
check, not a different limit. `cpp`, `go` and the other ten reject at exactly 256, so the
boundary is right everywhere else.

## Attribution — `corelib-c-cpp` (not codegen)

Nesting depth is wire mechanics: the sequence stack lives in the corelib's istream, and the
schema has nothing to say about it (`MAX_DEPTH` is a format-wide ceiling, not a schema bound).
Per CLAUDE.md's triage table, *"sequence framing … wire mechanics → the corelib reader"*.

Confirmed by which drivers are affected: **`c` and `cpp-c-cpp`** — the two profiles that share
the C corelib's `istream`. `cpp`, which has its own corelib, rejects correctly. That split is
the signature of a corelib defect rather than a codegen one; had it been generated code, the
two C++ profiles would differ from each other, not agree.

## Why no gate caught it

`sweep_framing` **does** carry a `MAX_DEPTH` axis — and it cannot see this:

```python
add("depth_over_MAX_DEPTH", hdr(0, WT_SEQ_BEG) * 300, "reject")   # far over
add("depth_ok_ctl",         hdr(0, WT_SEQ_BEG) * 8 + END * 8, "accept")   # far under
```

300 and 8. The boundary itself — 255 accept, 256 reject — is never tested, so an off-by-one is
structurally invisible to the axis that owns the rule.

**Closed the same day.** `sweep_framing` now carries MAX_DEPTH boundary vectors — 255 and 256,
each closed and truncated — and fails on exactly the two vectors above, nothing else. Promote
the axis to blocking when corelib-c-cpp#126 closes.

Fixing it needed **two** changes, not one, and the second was the subtler:

1. test 255 vs 256 rather than 300 vs 8; and
2. build the nest through a **declared** sequence.

`hdr(0, WT_SEQ_BEG)` — what the old vector used — opens root id 0, a *scalar* (`u8`), as a
sequence. §7.3 says skip it, so the entire chain nests inside a **skipped subtree** and
exercises the skip path's depth counter. Measured: depth 256 built that way is **unanimous**,
while depth 256 built through the declared `nested` (id 10) splits. They are different
counters, and the axis now sweeps both.

The other ceilings: `ID_MAX` already had an at-boundary control (`id_at_ID_MAX_ctl`), which is
plausibly why no off-by-one has surfaced there. `FIXLEN_MAX` and `ARRAY_MAX` deliberately get
none — §6.2 gives them as *"up to 2,147,483,647 (may be 65,535 on constrained profiles)"*, so
the ceiling is **profile-dependent** and no single boundary value exists that the whole family
must agree on: at 65,536 a constrained profile must reject and a heap profile must accept, and
that split is legal. Only fixed format-wide ceilings can be swept at their boundary.

## Resolution

**Impls:** **corelib-c-cpp** (`c` + `cpp-c-cpp`, the two profiles sharing the C `istream`; `cpp` with its own corelib rejects correctly) · **Axis:** verdict

✅ **RESOLVED 2026-08-02** — corelib-c-cpp#126 fixed and closed the same day it was filed. `fix(istream): count bound sequences towards the MAX_DEPTH ceiling` — the boundary is now 255 accept / 256 reject on all 13. **Re-verified** on the post-fix family (sofabgen `0.0.0-20260802183113-4865f8515430`, corelibs @ main): all vectors converge across 13 drivers, and the verdict *direction* was checked, not just agreement. Reproducers promoted into the green `corpus/regression/` gate (117 → 160 inputs). *Original report:
