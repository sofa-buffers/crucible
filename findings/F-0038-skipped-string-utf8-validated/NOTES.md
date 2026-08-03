# F-0038 — six corelibs UTF-8-validate a **skipped** string, which CORELIB_PLAN §6.4 forbids


**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Found 2026-07-27** by the 60-minute pacemaker round (105.6 M execs) on the
`poc/omit-all-default-sequences` family; it was clusters 6 and 13 of the post-fuzz
triage — two shapes, one root cause.

## The split (3-byte isolate)

`unknown_id_string_invalid_utf8.bin` = `4a 0a 8a` — an **unknown** field id (9, absent
from `probe`) carrying wire type FIXLEN with subtype **string**, payload one byte
`0x8a` (a lone continuation byte, invalid UTF-8):

| camp | verdict | drivers |
|---|---|---|
| skip without validating (**correct**) | `A` (all-default message) | c, cpp, cpp-c-cpp, py-cython, py-pure, typescript, zig (7) |
| validate while skipping | `R invalid_msg` | go, rust-std, rust-nostd, java, csharp, dart (6) |

Three controls isolate the axis exactly:

| control | result | what it rules out |
|---|---|---|
| `ctl_unknown_id_string_valid_utf8.bin` (`4a 0a 41`, same id, `"A"`) | all 13 `A` | not the unknown id — an unknown *string* field is otherwise skipped fine |
| `ctl_unknown_id_blob_same_byte.bin` (`4a 0b 8a`, subtype blob) | all 13 `A` | not the byte — only the **string** subtype triggers it |
| `ctl_known_field_invalid_utf8.bin` (`56 12 0a 8a 07`, `nested.str`) | all 13 `R invalid_msg` | the strict-UTF-8 check itself is correct family-wide; the defect is *where* it runs |

`skipped_element_invalid_utf8.bin` (`d6 0c 02 12 ff ff 07`) shows the same six rejecting
when the skip comes from **§7.3** instead of an unknown id — a fixlen string at a
`struct_array` element slot, which declares a sequence. Same camps, so one root cause.
*(In that vector `cpp`/`cpp-c-cpp` additionally emit a phantom element — that is F-0037,
orthogonal.)*

## The spec answers this — it is not a hole

CORELIB_PLAN §6.4, **normative**:

> **Skipped fields are never validated (normative).** Skipping stays what it is
> everywhere else in the design: a length jump over bytes that are not inspected
> (§5.2). UTF-8 validation runs only where a `string` is **materialized** — read into
> a destination — never on skip, in any mode. Wire validity of unread content is the
> **producer's** responsibility (MESSAGE_SPEC §8's MUST NOT, enforced by the strict
> encode side); protobuf treats unknown/unread fields the same way.

MESSAGE_SPEC §8 points at that clause for exactly this question ("the skip exemption").
So the seven accepters are conformant and **the six rejecters violate a MUST**.

## Attribution — corelib, one issue per implementation

The failing vector's field id is **unknown to the schema**, so generated code is not
involved at all: the corelib's own skip path is the only code that sees the field, and
it is the corelib that decides whether a length jump also transcodes/validates. Per the
CLAUDE.md triage question — *does the fix need knowledge only the schema has?* — no: it
needs the wire subtype, which the `fixlen_word` carries. §6.4 is a CORELIB_PLAN clause
for the same reason.

Six issues to file: **corelib-go, corelib-rs, corelib-rs-no-std, corelib-java,
corelib-cs, corelib-dart**.

Likely shape per language: the Unicode-string targets (java, cs, dart, rust `String`)
transcode at the boundary and their skip path evidently routes a string field through
that boundary instead of jumping the bytes; go is a byte-container target, so its skip
path is calling the strict check outright. The neighbouring precedent is **F-0012**
(corelib-ts validated the *fixlen word* in the skip path — the correct half: framing
must be checked while skipping, **content** must not).

## Repro

```
CORPUS=findings/F-0038-skipped-string-utf8-validated ./scripts/run.sh
```

## Coverage note

No sweep axis carried an invalid-UTF-8 payload at a *skipped* position: `utf8_seeds.py`
places invalid bytes in declared string fields (F-0004's axis, where all 13 agree), and
the §7.3 wiretype sweep uses valid payloads. Worth adding the product — invalid UTF-8 ×
every skippable position — once the six fixes land.
