# G-0014 — generated TypeScript decode ignores the header wire type (stream mis-framing)

**Status:** ✅ **fixed in sofabgen 0.18.0** — [generator#160](https://github.com/sofa-buffers/generator/issues/160),
**Issue:** [generator#160](https://github.com/sofa-buffers/generator/issues/160)

PR [#161](https://github.com/sofa-buffers/generator/pull/161) ("frame each decoded field by
header wire type"). **Re-verified 2026-07-18:** isolate `05 00 01` → **all 12 `R invalid_msg`**
(ts was `I`); `F0017_ts_wiretype_iso.bin` promoted into the regression gate. Found 2026-07-17
by the 3 h differential fuzz on sofabgen 0.17.7 (cluster 2; minimized 127 B → 24 B → a 3 B
isolate). Finding [`F-0017`](../findings/F-0017-ts-decode-ignores-header-wire-type/NOTES.md).

The **TypeScript backend**'s generated pull-decoder dispatches on the field **id alone**
and calls the schema-typed reader **without checking the header's wire type** (`c.wire`).
When a field header carries a wire type ≠ the field's declared type, the generated code
reads the bytes as the *schema* type and **desynchronizes from the wire framing** —
consuming the wrong byte count and mis-reading everything after the field. Only the
`default:` (unknown id) branch dispatches on the wire type (`c.skip(c.wire)`), so unknown
fields validate correctly and known fields do not.

```js
// generated Probe.decodeFrom — every known-field case, no c.wire guard:
case 0: o.u8 = Number(c.readUnsigned()); break;   // header wire could be anything
case 2: { const _s = c.readString(); ... }
case 10: o.nested = ProbeNested.decodeFrom(c);    // no c.wire === SequenceStart check
default: c.skip(c.wire); break;                    // the ONE branch that frames by wire
```

**Isolate `05 00 01`** — header `05` = `(id 0 << 3) | ArrayFixlen(5)`; field id 0 is
declared `u8` (wire Unsigned, 0). The other 11 impls frame it as an array-fixlen and
reject the malformed element word `01` (fp64 size 0 ≠ 8) → `INVALID`. TS ignores the wire
type, reads `00` as `u8 = 0`, then treats `01` as a new header (id 0 / Signed) → runs off
the end → `INCOMPLETE`. **Proof `05 07`** → TS decodes `u8 = 7` and round-trips `00 07`,
confirming it read the ArrayFixlen header as an unsigned scalar.

The corelib is **not** at fault: driving `Cursor` directly (bypassing the generated
dispatch) on `05 00 01` throws `INVALID_MSG` ("invalid fixlen array element type"). The
corelib readers assume they are only called for the matching wire type — a contract the
generated dispatch violates. The other backends drive the corelib feed/visitor, which
frames by wire type, so they cannot desync — this is a TS-backend codegen defect.

**Fix:** guard the header wire type per field before reading — reject a mismatch as
`INVALID` (matching how the family frames `05 00 01`), or at minimum route a mismatched
header through `c.skip(c.wire)` so the cursor stays framed by the wire. Upstream of the
resolved corelib-ts precedence family (F-0012/F-0014/F-0016): the wrong reader is selected
before any INVALID-vs-INCOMPLETE precedence question arises.
