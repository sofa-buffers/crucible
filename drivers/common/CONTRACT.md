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
