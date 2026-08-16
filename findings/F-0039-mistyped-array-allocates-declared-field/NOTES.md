# F-0039 — a §7.3-mistyped **array** is allocated into the declared field (java, csharp)

**Status:** ✅ **RESOLVED** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** corpus/regression — replayed by the resolved-findings gate on every push; a divergence there means this bug came back.
**Issue:** [generator#254](https://github.com/sofa-buffers/generator/issues/254), [generator#259](https://github.com/sofa-buffers/generator/issues/259)
**Codegen:** G-0023 | [generator#254](https://github.com/sofa-buffers/generator/issues/254), [generator#259](https://github.com/sofa-buffers/generator/issues/259) | the generator side of F-0039 — **a §7.3-mistyped array is allocated into the declared field** — an `ARRAY_SIGNED` header at the `array of u8` slot (`a6 06 04 01 06 07`)…

**Found 2026-07-29** by the `wiretype_sweep` axis (§7.3) on the first run of the
family that carries the sparse-array rewrite — corelibs **0.9.0 @ main**, sofabgen
**0.21.0**. 30 of the sweep's 332 vectors split; every one of them is an array
position, and every one splits the same two drivers off.

## The split (6-byte isolate)

`mistyped_array_signed.bin` = `a6 06 04 01 06 07`

```
a6 0c   sequence start, id 100            -> the `arrays` struct
  04    header (0<<3)|4 = ARRAY_SIGNED, id 0
  01    element_count = 1
  06    element zig-zag varint            -> 3
07      sequence end
```

Field `arrays.u8` is declared `array of u8`, which maps to **array-unsigned**
(MESSAGE_SPEC §1/§3). The header carries **array-signed**, so the field's wire type
contradicts its declared mapping.

| camp | canonical | drivers |
|---|---|---|
| skip, leave the field at its default (**correct**) | `A` (empty — the all-default message is zero bytes, §2) | c, cpp, cpp-c-cpp, dart, go, py-cython, py-pure, rust-std, rust-nostd, typescript, zig (11) |
| allocate the declared field from the skipped header | `A a6 06 03 01 00 07` | **java, csharp** (2) |

The two rejecters re-encode a **one-element unsigned array holding 0** — a value the
wire never carried. The element itself is *not* decoded (the signed element never
lands); what leaks in is the **length**.

Two controls isolate the axis:

| control | result | what it rules out |
|---|---|---|
| `ctl_welltyped_array.bin` (`a6 06 03 01 06 07`, ARRAY_UNSIGNED) | all 13 `A a60603010607` | not the array path — a correctly typed array round-trips everywhere |
| `ctl_mistyped_scalar.bin` (`a6 06 00 01 07`, a scalar where an array is declared) | all 13 `A` (empty) | not §7.3 in general — java/csharp skip a mistyped **scalar** correctly; only the **array** kind leaks |

## What the spec requires

MESSAGE_SPEC §7.3, **normative**:

> A field whose header carries a different wire type — or, for `fixlen`, a different
> subtype — than the one its declared type maps to **MUST** be **skipped**, exactly as
> a field with an unknown id is skipped. A decoder **MUST NOT** report such a field as
> `INVALID`, and **MUST NOT decode its payload into the declared field**.

Setting the field's array length *is* decoding into the declared field: it changes the
field's value from the empty array to `[0]`. §7.3 also settles the ordering against the
schema bound — "the schema bound applied only to a field that survives it".

## Attribution: generated code → `generator` (G-0023)

The declared type and the schema `count` are **schema** facts, so only generated code
can see the contradiction (CLAUDE.md triage table; MESSAGE_SPEC §7). Confirmed in the
generated source — `drivers/java/build/gen/src/main/java/message/Probe.java`,
`arrayBegin(int id, ArrayKind kind, int count)`:

1. the **skip arm** treats `ArrayKind.UNSIGNED` and `ArrayKind.SIGNED` as one case, so
   an array-signed header at an unsigned-declared id disarms the discard counter;
2. worse, the **allocation block** below it runs *unconditionally of the wire kind* —
   `m.arrays.u8 = new long[Math.min(count, ARRAY_INIT_CAP)]` — so the declared field is
   resized from a header §7.3 says to skip. That is the `03 01 00` above.

The same block applies the schema bound (`count > 5` → `INVALID`) before the kind is
checked, which §7.3 inverts explicitly; an over-count *mistyped* array would therefore
also be a false `INVALID`.

`csharp` splits identically, so the defect is in both backends, not in one port.

## Not a corelib bug

Both corelibs hand the generated code a correctly parsed `(id, kind, count)` triple;
neither knows `arrays.u8` is declared unsigned. `cpp-c-cpp` and `c` sit on the same
corelibs and are correct, which rules the corelib out from the other side.

## Resolution

**Impls:** generator (**java + csharp backends**, codegen, **G-0023**) — the corelibs hand both a correctly parsed `(id, kind, count)`; `c`/`cpp-c-cpp` on the same corelibs are correct · **Axis:** accept_value

✅ **RESOLVED 2026-08-01** — [generator#254](https://github.com/sofa-buffers/generator/issues/254) (G-0023) closed 2026-07-29; the backends consume the widened `ArrayKind` in [generator#259](https://github.com/sofa-buffers/generator/issues/259). **Re-verified 2026-08-01** against corelibs **0.10.0 @ main** + sofabgen **0.22.0**: all three reproducers converge on all 13 (the mistyped `ARRAY_SIGNED` header leaves the `array of u8` field `[]`, not `[0]`). Promoted into the regression gate as `F0039_*.bin`, and the two `ARR_fp*`-vs-`ARR_fp*` cells this shared with F-0042 are back in the blocking `wiretype_sweep` axis (361 -> 363 vectors, green)
