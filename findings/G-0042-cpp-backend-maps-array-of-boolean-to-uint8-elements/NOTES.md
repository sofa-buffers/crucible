# G-0042 — the sofabgen C++ backend maps `array of boolean` to `uint8_t` elements, so an element is never normalized and a value above 255 silently decodes `true` as `false`

**Status:** 🔴 **OPEN** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** the four vectors in this folder (`r0`, `r1` + two controls) and the §4.4 array vectors of `engine/structured/sweep_tolerance.py` (blocking axis, currently **RED**); not promoted to `corpus/regression` — promote with the fix.
**Issue:** [generator#581](https://github.com/sofa-buffers/generator/issues/581) (filed 2026-09-19)
**Corelib:** F-0064 — the sibling defect on the scalar path, which is `corelib-c-cpp`'s (no boolean slot in the object layer, and `read_bool` performs no mapping)

**Found 2026-09-18**, with F-0064, by the new §4.4 boolean family of the tolerance sweep.

## The rule

CORELIB_PLAN §4.4: a decoder **MUST** read every non-zero value as `true`, normalize it,
and re-encode `1`; a boolean carries **no width bound at all** (MESSAGE_SPEC §1).
MESSAGE_SPEC §4.7/§1: an `array of boolean` reuses the **unsigned array** wire form, so the
rule binds each element exactly as it binds a scalar.

## The divergence

`schema/probe.sofab.yaml` declares `flag_array: { id: 204, items: { type: boolean, count: 5 } }`.

| input | bytes | §4.4 requires | `cpp`, `cpp-fixed` | `c`, `cpp-c-cpp`, `cpp-c-cpp-dyn` | the other 12 |
|---|---|---|---|---|---|
| `r0_arr_elem_two.bin` | `e3 0c 05 02 01 00 01 01` | `A e30c050101000101` | **`A e30c05` `02` `01000101`** | `A …02…` (F-0064) | ✓ |
| `r1_arr_elem_256.bin` | `e3 0c 01 80 02` | `A e30c0101` | **`A e30c0100`** — `true` became **`false`** | `R invalid_msg` (F-0064) | ✓ |
| `ctl0_arr_elem_one.bin` | `e3 0c 05 01 01 00 01 01` | `A e30c050101000101` | ✓ | ✓ | ✓ |

`r1` is the serious one: 256 is truncated to eight bits, `256 & 0xff == 0`, and a `true`
the sender wrote comes back as `false` with a `COMPLETE` verdict. No error is raised
anywhere — this is silent value corruption on sender-chosen bytes, not a verdict split.
(`u64_max` truncates to `0xff` and happens to stay `true`, which is why a single vector
would have missed it; the sweep carries `2`, `0xff`, `256`, `2^32` and `2^64-1`.)

## Where it is

The generated C++ type, for **both** corelib profiles:

```cpp
/* drivers/cpp/gen/cpp/probe.hpp:453 */      std::vector<std::uint8_t> flag_array = {};
/* drivers/cpp/gen/c-cpp/probe.hpp:458 */    sofab::InlineVector<std::uint8_t, 5> flag_array = {};
```

against the **scalar** boolean in the same generated file, which is correct:

```cpp
/* drivers/cpp/gen/cpp/probe.hpp:460 */      bool flag = false;
/* :621 */                                   if (flag != false) { (void)os.write(203, flag); }
```

So the backend has a boolean element type and uses it at the scalar position; the array
element path falls back to `uint8_t`. The element type is a **schema** fact — the corelib
sees an array of unsigned integers and nothing more, and `corelib-cpp`'s own `read` picks
its behaviour from the destination type it is handed. Handed `uint8_t`, it faithfully
stores the wire value; handed `bool` it normalizes (which is exactly what the scalar path
proves). Per CLAUDE.md's triage question the fix needs knowledge only the schema has, so
this is the **generator**'s to start.

**`std::vector<bool>` is not the fix** (corrected 2026-09-19, before filing). The byte
storage is deliberate and documented at `generators/cpp/helpers.go:282-297` (`7470127`): the
member must be the decode destination with one addressable byte per element, and
`std::vector<bool>` is bit-packed. corelib-c-cpp binds the destination's address and fills it
later during `feed`; corelib-cpp resumes a chunk-split field into the same destination.
Neither C++ corelib offers a boolean-array read today (a `bool` element static-asserts in
both). So the fix keeps the bytes and has two routes, both in generator#581:

1. **generator only:** read into a `uint64_t` staging array and normalize afterwards. That is
   immediate for corelib-cpp, whose `readArray` fills in the call, and awkward for
   corelib-c-cpp, where the staging buffer must live in the object until the field completes.
   It costs 8× the storage.
2. **with a corelib API (cleaner):** a normalizing boolean-array element store in both C++
   corelibs (`raw != 0` into the byte, no width check), which the backend asks for. This is
   the array half of §4.4's "dedicated boolean read/write functions" and implicates
   corelib-cpp too, not only corelib-c-cpp (#172 records its array store).

The `c` / `cpp-c-cpp` columns above are F-0064 leaking into the same vectors (the C element
store rejects `256` at `istream.c:723`), not a second generator defect.

## Reproducing

```sh
CORPUS=findings/G-0042-cpp-backend-maps-array-of-boolean-to-uint8-elements ./scripts/run.sh
```
