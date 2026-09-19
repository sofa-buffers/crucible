# F-0064 — `corelib-c-cpp` reads a `boolean` as a one-byte unsigned: a non-zero value is not normalized to `true`, and a value above 255 is rejected as `INVALID`

**Status:** 🔴 **OPEN** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** the six vectors in this folder (`r0`–`r2` + three controls) and the §4.4 family of `engine/structured/sweep_tolerance.py` (blocking axis, currently **RED**); not promoted to `corpus/regression` — promote with the fix, so that gate starts green rather than red.
**Issue:** [corelib-c-cpp#172](https://github.com/sofa-buffers/corelib-c-cpp/issues/172) (filed 2026-09-19)
**Sibling:** [G-0042](../G-0042-cpp-backend-maps-array-of-boolean-to-uint8-elements/NOTES.md) — the same clause on the array path, which *is* the generator's and carries its own write-up (so it gets a folder, not a `**Codegen:**` line: that line is for a codegen defect with no write-up of its own).

**Found 2026-09-18** by the new §4.4 boolean family of the tolerance sweep, on the day
`schema/probe.sofab.yaml` first declared a `boolean` field. Until then no corpus in this
repo could carry one, so the whole of §4.4 was untestable family-wide — the gap AUDIT_v3
records from the other side, as an open "no dedicated boolean read function" finding in ten
of the twelve ports.

## The rule

CORELIB_PLAN §4.4 (`CORELIB_PLAN.md:285-301`, `main@382159e`):

> **Booleans have no wire type of their own (normative).** A boolean is an unsigned integer
> with value `0` or `1`.
> * The corelib **MUST** provide dedicated boolean read/write functions **performing that
>   mapping**.
> * **Canonical on encode, tolerant on decode.** An encoder **MUST** write `true` as `1`. A
>   decoder **MUST** read **every value other than `0`** as `true`: such a value is **not**
>   `INVALID` (§5.2), it is normalized away, and a re-encode emits `1` […] (This is why a
>   boolean is **not** bound the way an `enum` or a `bitfield` is — MESSAGE_SPEC §1. Those
>   carry the width their declaration implies, and a value outside it **is** `INVALID`; a
>   boolean carries **no width bound at all**.)

MESSAGE_SPEC §1 states the same from the wire side: `boolean` is *"unlike every other
integer-backed leaf type … the value carries **no** width bound — a decoder reads every
non-`0` as `true` and normalizes it"*.

## The divergence

`schema/probe.sofab.yaml` declares `flag: { id: 203, type: boolean }`. Fourteen of the
seventeen drivers implement the clause; three do not, in two different ways.

| input | bytes | §4.4 requires | `c` | `cpp-c-cpp`, `cpp-c-cpp-dyn` | the other 14 |
|---|---|---|---|---|---|
| `r0_bool_two.bin` | `d8 0c 02` | `A d80c01` | **`A d80c02`** — echoed back | **`A `** (empty) — decoded as **`false`** | `A d80c01` ✓ |
| `r1_bool_256_over_u8.bin` | `d8 0c 80 02` | `A d80c01` | **`R invalid_msg`** | **`R invalid_msg`** | `A d80c01` ✓ |
| `r2_bool_u64_max.bin` | `d8 0c ff×9 01` | `A d80c01` | **`R invalid_msg`** | **`R invalid_msg`** | `A d80c01` ✓ |
| `ctl0_bool_one.bin` | `d8 0c 01` | `A d80c01` | `A d80c01` ✓ | `A d80c01` ✓ | `A d80c01` ✓ |

Both failures reproduce at every scalar boolean position the schemas declare, identically:
the root scalar (203), the struct child (`nested`/9), the wrapper-element child
(`struct_array`/…/2), and the union member `as_flag` in `schema/probe-union.sofab.yaml`
(`sweep_tolerance`'s union pass: 5 divergences, same camps). The array position (204) is
G-0042's.

The union pass is **not** reached by CI while this finding is open: `scripts/sweep.sh` exits
on the red probe pass before it builds the union drivers. It was run by hand on 2026-09-19.

### The controls are the load-bearing half

`ctl1_u8_two.bin` (`00 02`) and `ctl2_u8_256_over_width.bin` (`00 80 02`) put the **same
two values** at a real `u8` field (id 0). There, all seventeen agree — `2` is the value 2
(`A 0002`) and `256` is `R invalid_msg`, because a `u8` *does* carry a width bound (§7.1).
So the machinery works; what is wrong is that the boolean is being run through it. The
defect is not "rejects a large varint", it is "treats a boolean as a `u8`".

`r0` and `cpp-c-cpp` deserve one more line: `2` decodes as **false** while `0xff` decodes
as **true**. That is not a threshold — it is bit 0. See below.

## Where it is, and why this is the corelib's and not the generator's

Three sites, all in `vendor/corelib-c-cpp` (`@7b68297`):

1. **`src/include/sofab/istream.h:403-407`** — the dedicated read function §4.4 asks for
   exists, and does not perform the mapping:

   ```c
   static inline void sofab_istream_read_bool (sofab_istream_t *ctx, bool *var)
   {
       sofab_istream_read_field(ctx, var, 1,
           SOFAB_ISTREAM_OPT_FIELDTYPE(SOFAB_TYPE_VARINT_UNSIGNED));
   }
   ```

   A one-byte destination of type *unsigned*. Two consequences follow directly: the raw
   value is stored as-is (no `!= 0`), and a value that does not fit one byte is an
   over-width read — reported as `InvalidMessage`. Both are what the table above shows.

2. **`src/include/sofab/sofab.hpp:2591-2593`** — the C++ wrapper routes `T = bool` into
   that same function, so the raw wire value lands in a `bool` object. A `bool` holding the
   bit pattern `2` violates the C++ ABI invariant, and the compiler is entitled to test only
   bit 0: g++ emits `test al,1`, which is why `2` reads back as `false` (`2 & 1 == 0`) and
   `0xff` as `true`. It is undefined behaviour, not merely a wrong value — the vectors here
   are also a sanitizer target.

3. **`src/include/sofab/object.h:57-67`** — the descriptor-driven object layer (the route
   `drivers/c` uses, and the one `sofabgen`'s C backend targets) has **eleven** field-type
   tags, `UNSIGNED` through `SEQUENCE`, and **no boolean among them**:

   ```c
   #define SOFAB_OBJECT_FIELDTYPE_UNSIGNED  0x0
   …
   #define SOFAB_OBJECT_FIELDTYPE_SEQUENCE  0xA
   ```

   This is what decides the attribution. The generated descriptor says
   `SOFAB_OBJECT_FIELD(203, message_probe_t, flag, SOFAB_OBJECT_FIELDTYPE_UNSIGNED)`
   (`drivers/c/gen/probe.c:94`) — and there was no other tag it *could* have said. The
   generator knows the field is a `boolean`, but the surface it has to express that through
   does not admit it, so the schema fact has nowhere to go. Per CLAUDE.md's triage question
   ("does the fix need knowledge only the schema has?") the answer is yes *and* the corelib
   offers no way to carry it: the corelib must grow a boolean slot type before any backend
   can emit one.

**What a fix has to cover:** `read_bool` normalizing (`*var = (raw != 0)`) and reading
through a full-width accumulator rather than a one-byte destination, plus a boolean field
type in the object layer so the descriptor route can reach the same code. Fixing only the
first leaves `drivers/c` unchanged, because it never calls `read_bool`.

## Reproducing

```sh
python3 engine/structured/sweep_run.py sweep_tolerance     # 24 divergences, all §4.4
CORPUS=findings/F-0064-boolean-read-not-normalized-and-bound-to-destination-width \
    ./scripts/run.sh                                        # the six isolates
```
