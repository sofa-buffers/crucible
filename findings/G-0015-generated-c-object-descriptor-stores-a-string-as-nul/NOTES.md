# G-0015 — ~~generated C object descriptor stores a `string` as NUL-terminated~~ (WITHDRAWN)

**Status:** ⚪ **WITHDRAWN 2026-07-18 — not a codegen defect.** Reclassified as a **by-design
allowed divergence**, not a bug (`oracle/policy.yaml`; finding
[`F-0018`](../findings/F-0018-c-embedded-nul-string-truncation/NOTES.md)).

Original hypothesis: the C backend emits `SOFAB_OBJECT_FIELDTYPE_STRING` (NUL-terminated), so
an embedded U+0000 in a `string` is lost on re-encode (`A\0B` → `A`) — the string analogue of
G-0012's unsized blob. **Why it is *not* a codegen bug:** the C object API deliberately models
a `string` as a C string (`char[]` + `strlen`), and a C string's length *is* "up to the first
NUL" — `sofab_ostream_write_string`'s `strlen` is correct, not defective. The corelib also
receives the value in full (the istream fills the buffer and the strict-UTF-8 check validates
all bytes); the projection to first-NUL is a property of the NUL-terminated representation, and
the lossless path is the byte/length (visitor) API. Forcing a sized-string object field would
de-idiomatize C strings for a pathological input. So this is a **type-representation projection**,
tolerated in `policy.yaml` (axis `accept_value`, spec basis MESSAGE_SPEC §8), not a generator
change. G-0015 is retired and the number is not reused.
