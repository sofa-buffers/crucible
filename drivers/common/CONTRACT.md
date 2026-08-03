# Driver contract

Every `drivers/<lang>/` implements this contract so the comparator can drive all
implementations uniformly. Two front-ends share one decode core:

1. **Replay driver** (the differential path) — a persistent process the
   comparator feeds. Buildable with the stock compiler (gcc / go), no clang
   required. This is what proves implementations agree.
2. **Coverage front-end** (the fuzzing path) — a libFuzzer / go-fuzz / Jazzer /
   Atheris entry point that exercises the same decode core for coverage-guided
   exploration and sanitizer/crash detection. Built with the language's fuzzing
   framework (clang for libFuzzer, etc.).

The decode core is identical between them; only the front-end differs.

## Replay protocol (persistent mode)

The comparator speaks this to every replay driver over stdin/stdout:

- **Input (stdin):** a stream of length-prefixed records. Each record is a
  4-byte little-endian `uint32` length `N`, followed by `N` bytes of candidate
  wire input. Clean EOF at a record boundary → the driver exits 0.
- **Output (stdout):** for each input record, **exactly one** canonical line
  (`oracle/canonical.md`), `\n`-terminated, in the same order as the inputs.
- **stderr:** logs/diagnostics only — never parsed.

Persistent mode is mandatory: one process handles the whole corpus. Fork+exec
per input caps throughput ~1000× and is why the generator's `encode`/`decode`
CLI is *not* reused here.

### Optional: `SOFAB_SPLIT=k` — chunked re-feed (NOT YET IMPLEMENTED BY ANY DRIVER)

When `SOFAB_SPLIT` is set to a positive integer `k`, a driver feeds each record as
**two chunks into one decoder** — `[0,k)` then `[k,end)` — and emits the canonical line
of the **final** state. Unset, or `k >= len`, is today's behaviour: one feed.

This exists because the replay protocol hands a record over whole, so a defect that only
appears at a chunk boundary is invisible to every gate here. CORELIB_PLAN §6.4 (for UTF-8)
and §7.2 item 4 (for the decoder at large) require that **a chunk boundary must not change
the outcome**, and `scripts/run-chunked.sh` checks exactly that: for every input and every
split point, the split line must equal the whole line. Sweeping `k` covers every
metadata/payload boundary without the harness knowing where they are.

Two properties follow, and neither is reachable otherwise:

- **chunk invariance** — the outcome does not depend on how the bytes arrived;
- **resumability** — an `I` after the first chunk must still reach the right verdict *and
  value* after the second. corelib-cpp's raw blob read returned `INVALID` and then dropped
  the buffered tail, so the message never completed even once the rest arrived
  ([crucible#130](https://github.com/sofa-buffers/crucible/issues/130)).

Unlike every other oracle in this repo the check is **not differential** — it compares a
driver against itself. So it needs no second implementation to be useful, drivers can opt in
one at a time, and it is the only gate that can catch a defect the whole family shares.

**A driver that ignores the variable emits byte-identical output, which is indistinguishable
from passing.** Support is therefore declared explicitly to the gate, never inferred: it runs
only the drivers named in `SOFAB_SPLIT_DRIVERS` and skips loudly when that is empty.

The obstacle is that every driver today decodes one-shot (`DecodeProbe(data)`,
`Probe::try_decode(data)`, …); honouring `SOFAB_SPLIT` means reaching the corelib's streaming
`feed` and the generated visitor, which differs per language. Tracked in `docs/TODO.md`.

## Decode core requirements

- Decode the candidate bytes into the `probe` message using the corelib's real
  decode entry point (generated from `schema/` via `sofabgen`).
- Map the corelib's **three-valued** decode outcome (MESSAGE_SPEC §7) to the
  canonical line (`oracle/canonical.md`):
  - `COMPLETE` → emit `A <hex>`.
  - `INCOMPLETE` (decode ended mid-field/varint or with an open sequence — **not**
    an error) → emit `I` (optionally `I <hex>` for the partial value). Do **not**
    report it as `A` or `R`.
  - `INVALID` → emit `R <class>`, mapping the corelib's error to the canonical
    reject class.
- A driver can only emit `I` once its corelib exposes a distinct `INCOMPLETE`
  outcome (tracked in generator#86 + the per-corelib issues). Until then it emits
  `A`/`R` and F-0001 stays red for that impl — the correct signal.
- **Never** crash, hang, or read out of bounds on malformed input — if it does,
  that is itself a finding (the coverage front-end + sanitizers exist to catch
  exactly this).
- No global state carried between records: each record decodes from a fresh,
  zero-initialized message.

## Files per driver

```
drivers/<lang>/
  meta          key=value: lang, corelib, framework, pacemaker(true|false)
  build.sh      regenerate from schema/ via sofabgen, build the replay driver
                (sanitizers on where the toolchain supports it), print the binary path
  driver.<ext>  the decode core + replay front-end (+ guarded coverage front-end)
```
