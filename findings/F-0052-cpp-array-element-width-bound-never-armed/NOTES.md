# F-0052 — the cpp backend never arms `readArray`'s element-width bound, so `cpp` masks an over-width array element

**Found 2026-08-03** by the 4-hour pacemaker round (577 M execs, corpus 878 → 2609) — the one
new cluster of that round, minimized 49 B → 11 B and then rebuilt as a clean isolate.

## What happens

`arrays.u8` is `array of u8, count 5`. An element carrying **5208** is over `u8`'s declared
width, which documentation#32 made a **validity bound** (§1/§7.1) — the rule F-0033 closed.

| verdict | drivers |
|---|---|
| `R invalid_msg` (**correct**) | c, cpp-c-cpp, csharp, dart, go, java, py-cython, py-pure, rust-no-std, rust-std, typescript, zig (12) |
| `A`, re-encoding the element as **88** | **cpp** |

5208 mod 256 = 88 — the value is **masked to the declared width and kept**, precisely the
behaviour documentation#32 forbids ("never masked, never kept"). Reproduced on three widths:
`u8`, `i8` (via zig-zag) and `u16`.

**`ctl_scalar_u8_over` is the control that scopes it**: the same over-width value at a *scalar*
`u8` position is rejected by all 13, cpp included. So cpp's scalar path is correct — F-0033 is
genuinely closed there — and only the **array element** path is not.

## Why the corelib is not at fault

corelib-cpp **shipped this check**, in `readArray`
([corelib-cpp#67](https://github.com/sofa-buffers/corelib-cpp/issues/67), `c4b8eef`
*"reject an over-width array element instead of masking it"*, 290 lines in `sofab.hpp`). The
vendored corelib is `2466869`, which contains it.

The check is **opt-in**:

```cpp
bool readArray(T &dst, long schemaCount = -1, long dynCap = -1,
               ElemBound elem = {}) noexcept
{
    ...
    if (elem.armed)
    {
        /* the bounded decode */
        return readIntElements<true>(sp.first(std::min(sp.size(), count_)), elem);
```

and the generated code never arms it. Every one of the ten array reads in
`drivers/cpp/gen/cpp/probe.hpp` passes two arguments:

```
readArray(u8, 5)   readArray(i8, 5)   readArray(u16, 5)   … readArray(fp64, 5)
```

`grep -c ElemBound` over the generated header: **0**.

So `elem` is default-constructed, `elem.armed` is false, the bounded path is never taken, and
the unbounded one masks. The corelib provides the capability; the backend does not consume it.

## Attribution — generator (sofabgen **C++ backend**)

This is the **F-0042 shape**: a corelib widened a hook to let generated code enforce a schema
bound, and the fix is only complete once the backend passes it. There, seven corelib issues
landed first and generator#259 consumed them.

Two further reasons it is not corelib-cpp:

- The bound is a **schema fact** — `u8` vs `u16` is the declared type, which the corelib is
  schema-agnostic about by design (MESSAGE_SPEC §7). It can only enforce what the caller hands
  it, and `ElemBound` is exactly that channel.
- **`cpp-c-cpp` is correct.** Same C++ backend, different corelib — and the C corelib's array
  path enforces it. So the split follows the corelib *API being used*, not the code generator
  being wrong about the rule; what is missing is one argument at ten call sites.

The generated code already does the equivalent explicitly for a **scalar**
(`probe.hpp:470`: `if (_v > 4294967295) { is.invalidate(); return; }`), which is why the scalar
control passes. Arrays were left on the unbounded overload.

## Why no gate caught it

The over-width axis has vectors only at **scalar** positions (F-0033's four reproducers, now in
`corpus/regression/`). There was no over-width **array element** vector anywhere — the same
scalar-only blind spot that F-0049 had for fp32 raw bits, found the same week. `sweep_overbound`
sweeps §7.1 bounds but the *width* bound arrived later (documentation#32) and was never added to
it.

`docs/TODO.md` carries the follow-up: extend the over-width vectors to the array-element
position, ideally as a `sweep_overbound` axis case rather than a one-off vector.
