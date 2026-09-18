# F-0063 — corelib-ts quiets an fp32 array's **signaling** NaN whenever the array does not fit the output buffer (the streaming encode path)

**Status:** 🔴 **OPEN** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** live and currently **red** — the encode gate (`scripts/run-encode.sh`) already replays `corpus/structured/083_arr_fp32_nan_bits.bin` at every `SOFAB_FLUSH` size and reports 6 mismatches on `typescript`. The four vectors in this folder are the minimized form, kept here because the corpus input alone does not separate the mechanism from its neighbours.
**Issue:** [corelib-ts#185](https://github.com/sofa-buffers/corelib-ts/issues/185)

**Found 2026-09-18** by the encode gate on the first full suite run after catching the
drivers up to sofabgen `0.0.0-20260918072500-d865b921` (corelibs at their `origin/main`
tips). Ten of eleven gates green, `encode` red on one driver:

```
[typescript] 111 input(s) x 9 config(s), surfaces=stream, min_output_buffer=1 — 6 mismatch(es)  [FAIL]
```

Six mismatches, one input, **every** flush size — `SOFAB_FLUSH=1,2,3,5,8,16`.

## The divergence

The input is a five-element `fp32` array (`arrays.nested.fp32`, field 100 → 10 → 0):

```
a6 06  56  05 05 20  0100807f 0100c07f 0000c0ff 01000000 0000803f  07 07
             ^count ^fixlen_word (4<<3)|0
                     ^^^^^^^^ element 0 = 0x7f800001, a SIGNALING NaN
```

The same encoder, the same value, two buffer sizes:

| how the message is encoded | element 0 comes back as |
|---|---|
| buffer holds the message, no sink (the default replay path) | `0100807f` — `0x7f800001`, **unchanged** |
| any buffer with a flush sink (`SOFAB_FLUSH=1..16`) | `0100c07f` — `0x7fc00001`, **quieted** |

The quiet bit is set. The other four elements — a quiet NaN, a negative quiet NaN, a
subnormal and `1.0` — survive both paths, which is the whole shape of the defect: only a
*signaling* NaN loses information when it passes through a 64-bit double.

All sixteen other drivers encode both ways byte-identically.

## Reproduced without a driver

Straight against `vendor/corelib-ts/src`, five elements, no generated code involved:

```js
const a = new Float32Array(5);
new Uint32Array(a.buffer)[0] = 0x7f800001;        // signaling NaN
new OStream(new Uint8Array(64)).writeFp32Array(0, a);                  // no sink
new OStream(new Uint8Array(4), 0, sink).writeFp32Array(0, a);          // with sink
```

```
no sink        : 0505200100807f0100c07f0000c0ff010000000000803f
 4-byte + sink : 0505200100c07f0100c07f0000c0ff010000000000803f
 8-byte + sink : 0505200100c07f...
16-byte + sink : 0505200100c07f...
```

## Root cause — one of two paths in `writeFp32Array` is bit-exact

`vendor/corelib-ts/src/encode/ostream.ts:697-709`:

```ts
writeFp32Array(id: number, values: ArrayLike<number>): void {
  this.arrayHead(id, WireType.ArrayFixlen, values.length);
  this.putVarintNum(4 * 8 + FixlenSubtype.Fp32);
  if (this.reserveBulk(values.length * 4)) {
    this.pos = this.kernel.packFp32Array(values, this.buf, this.pos);   // bit-exact
  } else {
    for (let i = 0; i < values.length; i++) this.putFp32(values[i]!);   // re-quantizes
  }
}
```

`reserveBulk(n*4)` asks for the whole payload **contiguously**. It succeeds when the
installed buffer can hold the array and fails otherwise — so the fallback is not an edge
case, it is *the streaming case*, which is what an output buffer smaller than the message
exists for (§5.1).

The kernel it skips already knows why this matters — `src/backend/js.ts:174-188`:

> A `Float32Array` source already HOLDS the 32-bit wire words, so they are copied rather
> than read: `values[i]` widens each element to a double, and widening a SIGNALING NaN
> quiets it (`0x7f800001` comes back `0x7fc00001`), so **reading the values is exactly how
> an fp32 payload gets lost** (§4.6/§6.5).

The fallback does the thing that comment names. `putFp32(values[i])` reads the element as
a double and narrows it again through `setFloat32`.

## Which clauses it breaks

**CORELIB_PLAN §6.5** (`CORELIB_PLAN.md`, documentation `main@382159e`) — the requirement is
stated over positions *and* paths, not over a default path:

> for **every** implementation, decode → re-encode of any `fp32` payload (signaling NaN
> included) **MUST** reproduce the exact 4 wire bytes, at **every** `fp32` position — a
> **scalar** `fp32` (§4.6) **and** each element of an **`fp32` array** (§4.8).

**CORELIB_PLAN §5.1.4** is the cleaner statement of the same failure, because it needs no
argument about NaNs at all:

> Any buffer at or above it **MUST** work and **MUST** produce output **byte-identical to
> the one-shot path**.

corelib-ts declares `MIN_OUTPUT_BUFFER = 1` (`drivers/ts/meta`), so a 4-byte buffer is far
above the minimum and owes byte-identical output. It does not deliver it.

## Attribution — corelib, not codegen

The **corelib**. The question CLAUDE.md poses — *does the fix need knowledge only the schema
has?* — answers itself here: `writeFp32Array` is handed a `Float32Array` that already holds
the exact wire words, and writing them through needs no schema fact. The bit-exact code is
already in the same repository, one call away, in the branch the fallback does not take.
Generated code has no choice left to make.

## Why it surfaces only now, and why it is not F-0031 coming back

Before sofabgen `cf6de0fb` ("every native array is a typed array"), the generated TS class
kept the wire bytes of an fp32 array beside the value (`<field>Fp32Raw`) and called
**`writeFp32ArrayRaw`** whenever any element was a NaN — which writes the payload verbatim
and never enters `writeFp32Array` at all. The new codegen drops that companion, correctly:
a `Float32Array` *is* the raw channel. It therefore relies on `writeFp32Array` being
bit-exact, and one of its two paths is not.

**[F-0031](../F-0031-fp32-snan-quieted-py-cython-ts-dart/NOTES.md) is resolved and stays
resolved.** Its guard (`corpus/regression`) replays the default path, and that path is
green here too — `r0` encodes correctly with no sink, on every driver. What this finding
reaches is a site that guard never covered: the same class at the **flush** path of an
**array**, the way F-0062 was the F-0043 class at a site its ticket never scoped. Decided by
reading `ostream.ts`, not by re-running the old reproducer.

## Vectors

| file | what it pins |
|---|---|
| `r0_fp32_array_snan.bin` | the finding — element 0 is `0x7f800001`; `ts` default matches the `c` anchor, `SOFAB_FLUSH=4` does not |
| `c1_control_scalar_fp32_snan.bin` | the **scalar** `fp32` carrying the same signaling NaN is unaffected on both paths — the scalar still has its `Fp32Raw` companion, so the defect is the array path alone |
| `c2_control_fp32_array_quiet_nan.bin` | the identical array with a **quiet** NaN at element 0 is unaffected — it is the signaling bit that the widening destroys, not the NaN-ness |
| `c3_control_fp64_array_same_shape.bin` | the same shape as an **fp64** array is unaffected — an fp64 wire word survives a JS double intact, which pins the widening as the mechanism |

Measured with the drivers of this branch:

```
vector                                 c (anchor)         ts default         ts SOFAB_FLUSH=4
c1_control_scalar_fp32_snan.bin        5602200100807f07   5602200100807f07   5602200100807f07
c2_control_fp32_array_quiet_nan.bin    a6065605052001…c0  a6065605052001…c0  a6065605052001…c0
c3_control_fp64_array_same_shape.bin   a606560d0541010…   a606560d0541010…   a606560d0541010…
r0_fp32_array_snan.bin                 a60656050520010…   a60656050520010…   …0100c07f  DIFFERS
```

## Fix

Take the `Float32Array` fast path in the fallback too: when the source is a `Float32Array`,
the four bytes of element *i* are already in its buffer and can be emitted through
`writeRaw`/`putRaw` per element instead of `putFp32`. The array then splits across flushes
exactly as it does today — §5.1.3 makes one `fp32` element an atomic unit, and the fallback
already writes element by element — it simply stops going through a double on the way.

`writeFp32ArrayRaw` is unaffected and stays the entry point for a caller holding a payload
rather than a typed array.
