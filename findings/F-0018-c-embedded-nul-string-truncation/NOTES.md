# F-0018 — embedded U+0000 in a `string`: the C object API projects to first-NUL (by design)

**Status:** **by-design / allowed divergence** (`oracle/policy.yaml`, 2026-07-18) — **not a bug, not a fix.**
A `string` carrying an embedded U+0000 is valid on the wire and preserved by the 10
length-carrying profiles; the two corelib-c-cpp object-API profiles (`c`, `cpp-c-cpp`)
re-encode it up to the first NUL, because their string representation is a NUL-terminated
`char[]`. Inherent to the C-string convenience, not a decode error.
**Axis:** accept_value (round-trip) — all 12 **accept**; the re-encoded value differs. Sanctioned in policy.yaml.
**Found:** 2026-07-18 while adding F-0004's embedded-U+0000 valid control (crucible#55).

## The observation

Reproducer `embedded_nul.bin` = a valid `probe` whose only set field is `nested.str = "A\0B"`
(bytes `41 00 42`). All 12 drivers **accept** (verdict `A`). On re-encode:

| behavior | drivers | re-encoded `str` |
|---|---|---|
| project to first NUL | `c`, `cpp-c-cpp` (2) | `"A"` (`56 12 0a 41 …`) |
| preserve | the other 10 | `"A\0B"` (`56 12 1a 41 00 42 …`) |

## Why this is not a bug

Two different notions of "string" meet:
- **wire `string`** — length-delimited UTF-8, MAY contain U+0000 (a valid scalar);
- **C `string`** — a NUL-terminated `char[]` whose length *is* `strlen`, and which cannot
  represent an embedded NUL by construction (the NUL *is* the end).

The C object API models the field as the latter — `SOFAB_OBJECT_FIELDTYPE_STRING`, a
`char as_text[N]`. That is a deliberate, idiomatic choice: a C string's length is "up to the
first NUL", and `sofab_ostream_write_string` correctly uses `strlen` (`ostream.h:302`). There
is **no bug in that function** — that is the only meaningful definition of a C-string length.

**The corelib receives the value perfectly.** On decode the istream copies all `length` bytes
into the buffer and appends a terminator (`istream.c:779`), so `as_text` holds `41 00 42 00` —
the full value, nothing dropped, and the strict-UTF-8 check validates all three bytes
(`istream.c:886`). The projection to first-NUL happens only when the value is read back **as a
C string** (the object-API convenience `write_string` → `strlen`).

So this is a **representation projection** — like storing a value in a type that cannot hold
all of it — not a decode fault, and not "silent because broken": it is the documented
behavior of a NUL-terminated string type.

## The lossless path exists

A consumer that needs embedded NUL uses the **byte/length (streaming/visitor) API**, which
hands the raw `{ptr, len}` — a `memcpy` preserves everything. The object-API `STRING` field is
the C-convenient projection; the visitor API is the faithful one. Both are internally
consistent; the caller chooses. (The object struct has **no length member** for strings —
unlike the sized `blob` — so the *convenience* representation cannot itself reconstruct the
boundary; that is what makes it a projection rather than a lossless store.)

## Disposition — allowed divergence, not a fix

- **Not INVALID.** Rejecting a value the corelib received and stored in full would be wrong.
- **Not a family-wide ban.** U+0000 is legal on the wire; the 10 length-carrying profiles
  preserve it correctly and must keep doing so.
- **Not a codegen bug.** (The earlier `docs/SOFABGEN.md` G-0015 entry is withdrawn.)
- **Sanctioned in `oracle/policy.yaml`** as an allowed `accept_value` divergence for the
  NUL-terminated C profile — spec basis MESSAGE_SPEC §8 (string preservation across
  decode/encode is implementation-defined for a NUL-terminated / constrained profile; a
  one-line normative note is proposed, §6.4-style profile allowance until adopted).

Reproducer kept here as the record. It stays **out** of the green `corpus/regression/` gate —
it legitimately diverges, by policy.
