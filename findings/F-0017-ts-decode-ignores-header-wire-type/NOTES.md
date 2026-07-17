# F-0017 — TS generated decode ignores the header wire type (stream mis-framing)

**Oracle:** verdict (hard). **Attribution:** generator (sofabgen **TypeScript backend**) — **G-0014**.
**Upstream:** [generator#160](https://github.com/sofa-buffers/generator/issues/160). **Found:** 2026-07-17, 3 h fuzz on sofabgen 0.17.7 (cluster 2, 94/5607 sample inputs; minimized 127 B → 24 B → this 3 B isolate).

## Summary

The generated TypeScript `Probe.decodeFrom` dispatches on the field **id alone** and
calls the schema-typed reader **without checking the header's wire type** (`c.wire`).
When a field header carries a wire type ≠ the field's declared type, TS reads the
bytes as the *schema* type and **desynchronizes from the wire framing** — consuming
the wrong number of bytes and mis-reading everything after it. Every other
implementation frames the field by its actual wire type (per MESSAGE_SPEC §7,
"driven by the corelib feed"), so they agree; TS is a lone outlier.

## Clean isolate

`05 00 01` (3 bytes):

| | verdict |
|---|---|
| c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython, py-pure, java, csharp, zig | `R invalid_msg` |
| **typescript** | **`I`** |

Header `05` = `(id 0 << 3) | 5` → field id 0, wire type **ArrayFixlen (5)**. Field id 0
in the probe schema is declared **`u8`** → wire type **Unsigned (0)**. The 11 frame it
as an array-fixlen and reject the malformed element word `01` (subtype fp64, size 0 ≠ 8)
as INVALID (§4.8/§5.2). TS ignores the wire type, calls `readUnsigned()`, reads `00`
as `u8 = 0`, then treats the trailing `01` as a *new* header (id 0 / wire Signed) whose
value runs off the end → INCOMPLETE.

## Mechanism proof

`05 07` (2 bytes) → **TS returns `A 0007…`** — it round-trips field 0 as `u8 = 7`,
proving it read the array-fixlen header `05` as an unsigned scalar and consumed `07`
as the value. (c/go return `I`: array-fixlen count 7, element word truncated.)

## Root cause (generated code)

`drivers/ts/build/message.ts`, every known-field `case`:

```js
case 0: o.u8 = Number(c.readUnsigned()); break;   // never checks c.wire
case 2: { const _s = c.readString(); ... }          // same
case 10: o.nested = ProbeNested.decodeFrom(c);      // never checks c.wire === SequenceStart
```

Only the `default:` (unknown id) branch dispatches on the wire type
(`c.skip(c.wire)`), which is why *unknown* fields validate correctly and *known*
fields do not. The corelib `Cursor.readHeader()` captures `c.wire`; the generated
dispatch simply never consults it. The corelib readers (`readUnsigned`, `readString`,
`readFp32`, …) assume they are only called for the matching wire type — an implicit
contract the generated code violates.

The other sofabgen backends drive the corelib feed/visitor, which frames by wire type,
so they cannot desynchronize. **This is a TS-backend codegen defect**, not a corelib
bug: the corelib source `Cursor` skip path (`decode/cursor.ts`) rejects `05 00 01`
correctly — verified directly (`tsx`, bypassing the generated dispatch) → `INVALID_MSG`.

## Fix

In the TS backend's per-field dispatch, guard the header wire type before reading:
reject a mismatch as `INVALID` (matching how the family frames `05 00 01`), or at
minimum route a mismatched header through `c.skip(c.wire)` so the cursor stays framed
by the wire. The `default:` branch already models the wire-typed dispatch.

## Related / not this

- **Not** the corelib-ts INVALID-vs-INCOMPLETE precedence family (F-0012 skip path,
  F-0014 array-fixlen element word, F-0016 overlong varint) — those were corelib fixes
  and are resolved. This is upstream of them: the wrong reader is selected before any
  precedence question arises.
- A *separate, already-soft* axis: a **well-formed** wrong-wire-type value
  (`03 01 07`, `01 02`, `02 20 00000000`) splits the family accept-vs-reject
  (strict {c, cpp-c-cpp, py} reject; lax {go, rust, cpp, java, cs, zig} accept). That
  is policy-soft (MESSAGE_SPEC §7 does not pin wrong-wire-type handling). F-0017 is the
  **hard** subset: TS mis-frames rather than either accepting or rejecting, producing a
  verdict (`I`) no other impl produces. A §7 clarification (generated code MUST frame
  each field by the header wire type) would also settle the soft axis; filed as codegen
  first because the other 11 already frame correctly.

## Reproducers

- `wrong_wire_type_misframed.bin` = `05 00 01` — the hard 11-vs-1 isolate (TS `I`, family `R`)
- `misframe_proof_u8.bin` = `05 07` — TS `A` with `u8 = 7`, proving the wire type is ignored
- `cluster2_original_24B.bin` = the byte-minimized fuzzer rep this reduced from
