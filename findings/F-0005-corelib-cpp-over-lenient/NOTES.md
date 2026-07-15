# F-0005 — corelib-cpp accepts malformed messages the whole family rejects

> **Re-verified ✅ resolved 2026-07-15 (sofabgen 0.16.1 + corelib-cpp@main):** cpp
> now rejects the reproducer `56 0a 59` in step with the family. **New, unrelated:**
> on that same input corelib-py now returns `I` (INCOMPLETE) where the family
> returns `R` — split out as [F-0006](../F-0006-corelib-py-fixlen-fp-incomplete-vs-invalid/NOTES.md)
> (filed corelib-py#38), part of the broader [F-0007](../F-0007-invalid-vs-incomplete-precedence/NOTES.md)
> precedence family. Not a regression of F-0005.

**Status:** ✅ **resolved** — fixed upstream in corelib-cpp ([issue #22](https://github.com/sofa-buffers/corelib-cpp/issues/22) closed). Re-verified 2026-07-08 against **sofabgen 0.15.1 + corelib-cpp@main**: `cpp_accepts_malformed.bin` no longer diverges — corelib-cpp now rejects it in step with the rest of the family.
**Found:** Phase 3, by clustering the pacemaker's divergences (`oracle/cluster.py`)
— the single largest divergence source after F-0001
**Axis:** verdict + accept_value (hard)
**Affects:** `corelib-cpp` (the pure-C++20 corelib). Its sibling `corelib-c-cpp`
(the C++ wrapper over the C corelib) does **not** have this bug — they disagree.

## What

`corelib-cpp`'s decoder accepts inputs that every other implementation — including
the other C++ corelib — rejects as malformed, and often decodes many different
malformed inputs to the **same** value.

Reproducer `cpp_accepts_malformed.bin` (3 bytes: `56 0a 59`):

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0005-corelib-cpp-over-lenient/cpp_accepts_malformed.bin | drivers/cpp/build/cpp/driver
#   cpp        -> A 5607a606560707c60c07   (accepts, decodes to a nested-ish value)
#   cpp-c-cpp  -> R invalid_msg            (rejects)
#   c          -> R invalid_msg            (rejects)
#   (go, rust, java, csharp, py, ts, zig all reject too)
```

Feeding several *different* malformed inputs to corelib-cpp yields the **same**
`A 5607a606560707c60c07` — i.e. it is not just lenient, it collapses distinct
malformed inputs onto one garbage value instead of rejecting them.

## Scale

Clustering the 309 pacemaker-discovered inputs, corelib-cpp is the outlier in a
large fraction of the clusters — it appears accepting (or decoding to a different
value than the rest) in ~10 of the top ~12 root-cause clusters (see
`results/CLUSTERS.md`). After the F-0001 truncated-input split, this is the
biggest divergence generator in the family.

## Why it matters

A pure-C++ producer/consumer built on `corelib-cpp` will accept and silently
mis-decode messages that every other implementation — and even the C++/c-cpp
wrapper — treats as invalid. That is a correctness + interop bug, and a hardening
gap (a lenient parser is an attack surface).

## Fix

In `corelib-cpp`'s decoder (`corelib-cpp/include/sofab/sofab.hpp`, the IStream
cursor/parseTopLevel path), tighten validation to reject the same malformed
frames the rest of the family rejects. The c-cpp wrapper and the C corelib are a
reference for the intended strictness. This is a **corelib** bug (not codegen);
`oracle/cluster.py` gives the exact reproducer set.
