# F-0034 — dart falsely rejects a §7.3-skippable fixlen field because the generated `maxlen` guard ignores the wire subtype

**Status:** 🔴 OPEN — codegen (sofabgen **dart** backend), **G-0019**. Filed as
[generator#224](https://github.com/sofa-buffers/generator/issues/224) (write-up in [`ISSUE.md`](ISSUE.md)).
Found 2026-07-23 by the wiretype
(§7.3) sweep on the sofabgen CI build `0.0.0-20260723154129-241dc8f44efb` +
corelib-dart `origin/main` (`f9e64ec`) — the first run after that corelib bump.

## Divergence

One vector, `blob_field_fp64_mism.bin` (12 B):

```
56 1a 41 00 00 00 00 00 00 f8 3f 07
└┬┘ └──────────── FIX_fp64 body ──────────┘ └ SEQ_END
 └ open sequence id 10        payload = 1.5 (little-endian f64, 8 bytes)
    └ fixlen header: field id 3, subtype fp64, length 8
```

Inside the nested struct at id 10, a **fixlen fp64** value is placed at **field id 3,
which the schema declares a `blob` (`maxlen: 4`)** — a wire subtype the field does not
declare. Per **MESSAGE_SPEC §7.3**, a fixlen field whose header subtype ≠ the declared
type MUST be **skipped**; the message then decodes all-default → verdict **accept**.

| drivers | verdict |
|---|---|
| c, cpp, cpp-c-cpp, go, rust-std, rust-nostd, py-cython, py-pure, java, typescript, csharp, zig (12) | **A** — skip the mismatched field, round-trip `5607a606560707c60c07` |
| **dart** | **R `invalid_msg`** |

**Control** `blob_field_fp32_mism_ctl.bin` (8 B, `56 1a 20 00 00 c0 3f 07`): the same slot
receiving a **FIX_fp32** (4-byte payload) — also a subtype mismatch, also skipped — is
**accepted by all 13**, dart included. The split appears only when the mismatched
payload's length exceeds the declared `maxlen`.

## Root cause — generated `onFixlenHeader` does not gate its `maxlen` check on the subtype

`drivers/dart/build/bin/message.dart`, the generated `ProbeNested` visitor (regenerated
from `schema/probe.sofab.yaml` by the current sofabgen):

```dart
@override
void onFixlenHeader(int id, int subtype, int length) {
  switch (id) {
    case 2: if (length > 32) e.inv = true; return;   // str,  maxlen 32
    case 3: if (length > 4)  e.inv = true; return;   // blob, maxlen 4   <-- fires on ANY fixlen subtype
  }
}
```

The check consults `length` and the schema `maxlen`, but **ignores `subtype`**. Our vector
delivers `(id 3, subtype fp64, length 8)`; the guard evaluates `8 > 4 → e.inv = true` and
the message is rejected — even though a fp64 at a blob slot is a subtype mismatch that §7.3
requires be *skipped*, not measured against the blob's `maxlen`.

The correct emission gates the bound on the subtype matching the field's declared fixlen
subtype:

```dart
case 3: if (subtype == FixlenType.blob && length > 4) e.inv = true; return;
//         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ only enforce the blob maxlen for an actual blob
```

### Why this is new — the corelib bump introduced the callback the generator now (mis)uses

corelib-dart `f9e64ec` ("INVALID dominates INCOMPLETE via MessageVisitor header callbacks",
#18/#19) added `onFixlenHeader(id, subtype, length)`, a header hand-off fired **before the
payload / truncation check** so a schema-bound consumer can reject an over-`maxlen` value at
the header (§5.2: INVALID dominates a truncated tail). The generator dutifully emitted the
override — moving the blob `maxlen` check from the post-decode `onBlob` path (which is
implicitly subtype-gated: `onBlob` only fires for a *real* blob) to the header path (which
fires for *any* fixlen subtype at that id) **without carrying the subtype gate along**. The
old subtype-implicit check still exists too (`onBlob` line 314, `if (value.length > 4)`), so
the new header check is a redundant *and* wrongly-un-gated duplicate.

## Attribution — codegen (generator), corelib not implicated

Per CLAUDE.md's triage: `subtype == blob` and `maxlen == 4` are **schema facts** — the
corelib is schema-agnostic by design and cannot know them. The corelib faithfully hands off
what it read on the wire (`subtype = fp64`, `length = 8`); `shouldRead(id 3, wiretype =
fixlen)` legitimately returns true (id 3 *is* a fixlen-family field — the blob/fp64 subtype
distinction is invisible to the corelib). The decision to enforce the blob bound only when
the subtype actually matches is therefore the **generated code's** job, and it is the one
place the fix belongs. corelib-dart's header hand-off is working as designed → **not
implicated** (unlike F-0027's "occasionally both"). Files against **generator (sofabgen)**,
dart backend → **G-0019**.

Sibling-split confirmation (diagnostic step 3): every *other* backend's generated dispatch
gates the declared-type bound on the full wire type/subtype before enforcing it (that is
why the 12 skip), so this is dart-backend-specific generated code, not a shared-wire or
corelib issue.

## Scope / consistency

The only fixlen-scalar field with a `maxlen` small enough to be exceeded by any swept
construct is the `blob` at id 3 (`maxlen 4`) receiving `FIX_fp64` (8-byte payload) — so
exactly **one** vector diverges, matching the sweep's `1 divergence` report. The string
field at id 2 (`maxlen 32`) carries the identical latent bug, but no swept construct's
payload exceeds 32, so it does not surface here. A schema with a tighter string `maxlen`, or
a wider mismatched construct, would surface the id-2 path too — the fix (subtype gate) covers
both arms.

## Gate handling

The wiretype (§7.3) sweep is a **blocking** axis (`scripts/sweep.sh`). The one divergent
cell is carved out of emission via `KNOWN_OPEN` in
`engine/structured/wiretype_sweep.py` (citing this finding), mirroring the F-0032
`STRUCTURAL` carve-out precedent, so the axis stays green-except-known until the generator
fix lands. The isolate + control live here (kept **out** of the green `corpus/regression/`
gate while open); re-enable emission and promote them into the gate once fixed.
