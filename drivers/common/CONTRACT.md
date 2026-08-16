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

## The streaming axes

The replay protocol above hands every record over **whole** and re-encodes it with a
single call. The generated API has grown two streaming surfaces on either side of that
— a chunked decoder (`feed`/`finish`) and a streaming encoder (`serialize(os)`) — and
neither is reachable through the protocol as written. A defect that lives only there is
invisible to every gate in this repo.

Five environment variables open those surfaces. All five share one shape:

- **Unset is today's behaviour**, byte-identical. A driver that has not been taught an
  axis simply keeps working.
- The **output form does not change** — still exactly one canonical line per record, in
  order. Only *how the bytes get in* or *which call produces the hex* changes.
- They **compose**, with each other and with `SOFAB_MATERIALIZE`. Chunked decode plus a
  materialized dump is a value oracle over the streaming path, and is worth running.
- Each is an **intra-driver invariant** — a driver against itself, not against the
  family. That is why a single driver is already worth landing, and it is the only kind
  of gate here that can catch a defect the *whole* family shares.

### Decode side — the bytes arrive in pieces

| variable | meaning |
|---|---|
| `SOFAB_SPLIT=k` | feed each record as **two** chunks, `[0,k)` then `[k,end)`, into one decoder |
| `SOFAB_CHUNK=n` | feed each record in **fixed-size** chunks of `n` bytes (last one short) |
| `SOFAB_CHUNK_SCRUB=1` | overwrite each chunk's buffer with `0xA5` after `feed` returns |

`SOFAB_SPLIT` sweeps the boundary: run it for every `k` and every metadata/payload edge
in the message has been cut, without the harness needing to know where those edges are.
`SOFAB_CHUNK=1` is the other extreme — every varint, every length word and every payload
is split, so any parse state a decoder fails to carry across a `feed` shows up. Both are
worth having: the sweep localizes *which* boundary breaks, byte-at-a-time finds the ones
a two-way split happens to straddle.

`SOFAB_CHUNK_SCRUB` is a lifetime oracle, not a boundary one: a decoder that borrows from
a fed chunk rather than copying out of it will read scrubbed bytes. It requires the driver
to own a mutable copy of each chunk it feeds.

CORELIB_PLAN §6.4 states the rule for UTF-8 and §7.2 item 4 for the decoder at large: **a
chunk boundary must not change the outcome.** So under any of these the canonical line must
equal the line the whole record produces. Two properties follow, and neither is reachable
otherwise:

- **chunk invariance** — the outcome does not depend on how the bytes arrived;
- **resumability** — an `I` after one chunk must still reach the right verdict *and value*
  after the rest. corelib-cpp's raw blob read returned `INVALID` and then dropped the
  buffered tail, so the message never completed even once the remaining bytes arrived
  ([crucible#130](https://github.com/sofa-buffers/crucible/issues/130)).

**Deriving the verdict, identically in every language.** This is the part that would
otherwise drift eleven ways, so it is normative:

1. Feed the chunks in order. An `INVALID` from any `feed` (returned or thrown) is
   **terminal** — emit `R <class>` and feed no more.
2. After the last chunk, read the decoder's **`status`**, and map it exactly as the
   one-shot path maps its outcome: `COMPLETE` → `A <hex>`, `INCOMPLETE` → `I`.
3. **Derive the verdict the way the one-shot path derives it**, so the two cannot
   differ for reasons of API shape rather than of decoding.
   - Where the backend exposes a **`status`**, read that. Do **not** route the verdict
     through `finish()`: most backends throw there when the stream ended mid-field and
     one (Dart) returns null instead, so the canonical line would carry that
     difference.
   - Where `finish()` is the **only** terminal check, use it — but only because, in
     those backends, it returns the *same* three-valued outcome the one-shot path
     returns. Rust is the case in point: its generated `Decoder` has **no `status`**
     (crucible#132's API table overstates this — verified absent at sofabgen
     `cfe5250b`), and `finish()` yields `Result<Probe, sofab::Error>`, exactly what
     `try_decode` yields. Routing through it there introduces nothing.
   - Mid-stream, an `Incomplete` from a `feed` is **not** terminal — it only says
     *those bytes* ended mid-field. Only a non-`Incomplete` error stops the feeding.
4. A record of length 0 is the valid all-defaults message and is **not fed at all**, as
   in the one-shot path (corelib-c-cpp asserts `datalen>0`).
5. Never synthesize an empty chunk: `k<=0`, `k>=len` and `n>=len` all mean one chunk
   holding the whole record, i.e. today's behaviour.

### Encode side — which call produces the `A <hex>`

| variable | meaning |
|---|---|
| `SOFAB_ENCODE=new` | re-encode with the allocating `encode()` — the default, today's path |
| `SOFAB_ENCODE=to` | re-encode with the caller-buffer `encodeTo(dst, cap)` / `EncodeTo(w)` |
| `SOFAB_ENCODE=stream` | re-encode with the streaming `serialize(os)` into an `OStream` |
| `SOFAB_FLUSH=n` | give that `OStream` an `n`-byte buffer, so it flushes every `n` bytes |

The family is byte-canonical: one value has exactly one encoding. So all three surfaces
of one implementation must emit **identical bytes** for the same decoded value, and
`SOFAB_FLUSH` must not change them either — it is the encode-side mirror of
`SOFAB_CHUNK=1`, walking the encoder across a buffer boundary at every offset.

**Which flush sizes must work is the port's own declaration.** CORELIB_PLAN §5.1 no
longer fixes the floor at one byte for every port. A corelib **MUST** expose a documented
`MIN_OUTPUT_BUFFER` — the smallest buffer it accepts *for streaming*: `1` if it splits
atomic units across a flush, otherwise the largest run it reserves as one piece, and a
declaration **MUST NOT** exceed `20`. Each driver restates that value in its `meta` as
`min_output_buffer=<n>`, which is what sizes the flush sweep.

Both halves of the clause are gated:

* a size **at or above** the declaration **MUST** work and produce bytes identical to the
  one-shot path — the sweep always includes the declaration itself, so a port is walked
  across a buffer boundary at its own floor and the sweep is never empty;
* a size **below** it **MUST** be refused where the buffer is handed over — the driver
  exits 3 there. A port declaring `1` has no such case, since `SOFAB_FLUSH=0` is how the
  drivers spell "unset".

So exit 3 for a `SOFAB_FLUSH=n` is a **conformance failure** when `n >= min_output_buffer`
and the **required** answer when `n < min_output_buffer`. Exit 3 also remains the right
answer for a **surface** the backend does not have.

The declaration is not an escape hatch: a port that raises it to avoid the hard sizes is
then held to refusing everything below it, and §5.1 caps it at 20 precisely so a port
cannot demand more than a whole message can occupy. (Until documentation#46/#48 —
2026-08-11 — the floor was one byte for everyone and no declaration existed; the earlier
latitude that let corelib-ts#94 sit behind a green gate is not restored by this, because
a sweep that runs no size at all is now impossible by construction.)

Not every backend has all three (TypeScript has no `encode()`, C has no allocating
encode — see the API table in
[crucible#132](https://github.com/sofa-buffers/crucible/issues/132)). A driver asked for
a surface its backend does not have must **exit non-zero with a one-line reason on
stderr, before emitting any record** — never fall back to another surface, which would
report a mode as passing that never ran.

### Declaring support — twice, because one mechanism cannot cover both cases

A driver that has **never heard of** a variable emits byte-identical output, which is
indistinguishable from passing. A driver that **knows** the variable but cannot honour it
can say so. Those are different failures and need different mechanisms, so the contract
carries both:

- **The gate's roster.** `scripts/run-chunked.sh` runs only the drivers named in
  `SOFAB_SPLIT_DRIVERS`, and `scripts/run-encode.sh` only those in
  `SOFAB_ENCODE_DRIVERS`. Empty → the gate skips **loudly**. This is what stops an
  untaught driver from passing vacuously.
**The announcement is checked, not merely printed (since 2026-08-16).** A driver must write
its resolved configuration to stderr whenever `SOFAB_ENCODE` names a surface — *including one
that is its own default*, which is the part that used to be silent: the C driver defaults to
`to` and so said nothing when asked for `to`, exactly as a driver ignoring the variable would.
`oracle/encode_invariance.py` now requires the line to carry `enc=<surface>`, and
`flush=<n>` whenever `SOFAB_FLUSH` is set; a missing announcement fails the gate. The one
exemption is `SOFAB_ENCODE=new`, the family-wide default name, where honouring and ignoring
the variable are the same run by construction. Announcing more than required is never wrong.

- **The driver's own hard-fail**, as in the encode rule above. This is what stops a
  taught driver from silently degrading.

`meta` records the same facts declaratively, for the reader rather than the gate:

```
chunked_decode=push|pull|none    push: feed(chunk); pull: the corelib pulls from a
                                 reader the driver wraps around the chunks (python);
                                 none: the corelib has no resumable decoder (go)
encode_surfaces=new,to,stream    which of the three this backend actually has
```

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
  meta          key=value: lang, corelib, framework, pacemaker(true|false),
                variants, chunked_decode, encode_surfaces (see "Declaring support")
  build.sh      regenerate from schema/ via sofabgen, build the replay driver
                (sanitizers on where the toolchain supports it), print the binary path
  driver.<ext>  the decode core + replay front-end (+ guarded coverage front-end)
```
