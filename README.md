<p align="center"><img src="assets/sofabuffers_logo.png" alt="SofaBuffers" height="140"></p>

# SofaBuffers vs. The World

<b>Structured Objects For Anyone</b><br>
<i>... so optimized, feels amazing.</i>

## Crucible

**Differential fuzzing for the SofaBuffers wire format.** SofaBuffers ships one
wire format implemented independently in many languages (`corelib-c`, `-cpp`,
`-cs`, `-go`, `-java`, `-py`, `-rs`, `-rs-no-std`, `-ts`, `-zig`). Independent
implementations of one format **drift** — and the drift that hurts is *silent*:
two implementations both accept a byte sequence but decode it to different values,
or one accepts what another rejects. No crash, no exception — just broken interop
discovered in production.

Crucible makes that drift **loud, automatic, and continuous**. It feeds the *same*
bytes to every corelib and fails when they **disagree**.

> **The defining principle:** the oracle is *disagreement between implementations*,
> not a crash. A single-implementation fuzzer can only ask "did I crash?".
> Crucible asks "do all implementations agree on what these bytes mean?" — the
> question that actually matters for a shared wire format. Sanitizers (ASan/UBSan)
> are only a **second net**.

Sibling to [`arena`](../arena) (which measures speed/size). Crucible reuses arena's
proven shape — vendor every corelib, one uniform per-language driver contract, one
schema, one runner — but builds the corelibs **instrumented** (sanitizers +
coverage) instead of optimized, which is why it lives in its own repo.

## How it works

```
   seed / structured / mutated bytes
                 │
                 ▼   fan out the SAME bytes to every implementation
   ┌────────┬────────┬────────┬───────┬──────── … 12 drivers
   ▼        ▼        ▼        ▼       ▼
 C(san)   Rust      Go      Java   Python   …        each: decode → re-encode
   │        │        │        │       │                    → one canonical line
   └────────┴────────┴───┬────┴───────┘
              canonical result + verdict
                         ▼
               DIFFERENTIAL COMPARATOR
        all must agree on the verdict + the decoded value,
              modulo the allowed-divergence policy
```

Every `drivers/<lang>/` is a **persistent replay driver**: it reads
length-prefixed candidate bytes on stdin and emits exactly one **canonical line**
per input. The canonical form is *round-trip re-encoding* — on accept a driver
emits `A <hex(encode(decode(input)))>`, the decoded value re-encoded with the
corelib's own sparse-canonical encoder. This makes drivers **schema-agnostic** (no
per-field code — scaling the schema needs zero driver edits) and folds a round-trip
oracle in for free. The comparator diffs those lines byte-for-byte across all
drivers.

**Three oracles** run at once (PLAN §6):

1. **Decode agreement** — same wire bytes → every decoder → same verdict and, on
   accept, the same decoded value.
2. **Round-trip idempotence** — `decode → re-encode` is stable (folded into the
   canonical form; catches non-canonical encoding).
3. **Cross-encode** — a value encoded in impl A must decode identically in impl B
   (the [cross-encode / structured suite](#2-cross-encode--structured-values-scriptscross-encodesh)).

**Verdicts** (`oracle/canonical.md`) are three-valued per MESSAGE_SPEC §7, plus a
limit-mode fourth:

| line | meaning |
|---|---|
| `A <hex>` | **COMPLETE** — a valid message; the re-encoded sparse-canonical wire |
| `I [<hex>]` | **INCOMPLETE** — bytes end mid-field / open sequence; a valid-so-far partial (**not** an error) |
| `R <class>` | **INVALID** — malformed regardless of what follows |
| `L [<class>]` | **LIMIT_EXCEEDED** — a configured receiver-side cap was hit (limit mode only) |

Disagreeing on which verdict applies is a finding. The comparator is
**crash-isolating** (a driver that dies mid-stream → `[CRASH] driver X on input N`,
the run continues) and **hang-isolating** (a per-driver wall-clock timeout →
`[TIMEOUT] … input N`; a decoder that loops on untrusted bytes is itself a DoS
finding).

**One engine, N oracles.** A single **pacemaker** — the C corelib, fastest to
instrument, libFuzzer + sanitizers — drives coverage-guided exploration. Every
input it flags as interesting is replayed through *all* drivers and compared. C is
the coverage motor, **not** a privileged oracle: its own output is diffed like
everyone else's.

## Quick start

```sh
./scripts/bootstrap.sh     # vendor the corelibs @origin/main + install the latest sofabgen release
./scripts/run.sh           # build every driver, run the differential over the seed corpus
```

`run.sh` prints, per driver, its built binary, then the differential result:

```
6 inputs × 12 drivers (c, go, rust-std, rust-nostd, cpp, cpp-c-cpp, py-cython,
  py-pure, java, typescript, csharp, zig): 0 divergence(s) (0 crash, 0 timeout), 0 warning(s)
```

No toolchains in the bare workspace — everything runs inside
[`.devcontainer/`](.devcontainer/), which carries the fuzzing frameworks
(libFuzzer, cargo-fuzz, Jazzer, Atheris, SharpFuzz, Jazzer.js) and every language
toolchain.

## Test suites

All suites share the same 12 drivers and the same comparator; they differ in what
they feed and how they build. Each is one command.

| suite | command | what it hunts |
|---|---|---|
| [Differential loop](#1-differential-loop-scriptsrunsh) | `./scripts/run.sh` | the core gate — accept/reject + value divergence over a corpus |
| [Cross-encode / structured](#2-cross-encode--structured-values-scriptscross-encodesh) | `./scripts/cross-encode.sh` | encoder/decoder asymmetry on **valid, value-rich** messages |
| [Union suite](#3-union-suite-scriptsrun-unionsh) | `./scripts/run-union.sh` | the `union` (tagged-variant) wire feature — variants, one-of, unknown members |
| [Limit mode](#4-limit-mode-scriptsrun-limitssh) | `./scripts/run-limits.sh` | receiver-side decode caps (`max_dyn_*`) on unbounded fields |
| [Coverage pacemaker (fuzz)](#4-coverage-pacemaker--fuzzing-scriptsfuzzsh) | `./scripts/fuzz.sh` | crashes, hangs, and deep-path divergence via coverage-guided + grammar-aware mutation |
| [Clustering](#5-clustering-cluster1) | `CLUSTER=1 ./scripts/run.sh` | reduce a divergence firehose to root causes |

### 1. Differential loop (`scripts/run.sh`)

The core suite and the green regression gate. Builds each `drivers/<lang>/` replay
driver (sanitized where the toolchain supports it), frames a whole corpus into one
stream per driver, and reports every disagreement.

```sh
./scripts/run.sh                       # differential over corpus/seeds (the green gate)
CORPUS=corpus/interesting ./scripts/run.sh   # over any other corpus dir
TIMEOUT=5 ./scripts/run.sh             # per-driver hang budget in seconds
                                       # (default max(30, 0.25 × corpus size))
```

Exit `0` = all agree (modulo soft axes); `1` = a hard divergence (a finding).

### 2. Cross-encode / structured values (`scripts/cross-encode.sh`)

The third oracle. The malformed track (below) feeds *wire* and mostly exercises
decoders on reject/incomplete paths; this suite instead generates **valid,
value-rich** `probe` messages — float specials (±0, ±inf, NaN, subnormal), unicode
strings, boundary integers — and runs them through the round-trip + decode-agreement
oracle. Because the whole family is byte-canonical (every encoder emits identical
wire for a value), "encode in A, decode in B, compare" reduces to *all drivers must
emit the same `A <hex>`* — so a divergence here is a real cross-language
encoder/decoder asymmetry the wire-mutation fuzzer almost never reaches.

```sh
./scripts/cross-encode.sh              # regenerate corpus/structured, run the differential
REGEN=0 ./scripts/cross-encode.sh      # re-run without regenerating
python3 engine/structured/gen.py <dir> # just emit the structured corpus
```

The value vectors live in `engine/structured/gen.py` (a small reference encoder for
`schema/probe.sofab.yaml`). On its first run this suite found **F-0009** (the C
object API pads a sub-`maxlen` blob to `maxlen` / drops an all-zero blob).

### 3. Union suite (`scripts/run-union.sh`)

The `probe` message covers every wire feature except one — the **union** (a
tagged/​discriminated variant: a field that holds exactly one of several members).
This suite points the differential + round-trip oracles at
`schema/probe-union.sofab.yaml` (a message with a 4-variant union). Because the
drivers are schema-agnostic, no driver code changes — they are just rebuilt against
the union schema.

```sh
./scripts/run-union.sh                 # build all 12 drivers on the union schema, differential over corpus/union
```

It exercises each variant, the tag/​trailer around the union, and the union failure
modes (a wire with **two** members set, an **unknown** member id). The whole family
agrees on all of them — the last untested wire feature, confirmed consistent.

### 4. Limit mode (`scripts/run-limits.sh`)

Exercises the receiver-side decode caps (`max_dyn_array_count` /
`max_dyn_string_len` / `max_dyn_blob_len`) that bind schema-*unbounded* fields. It
uses a dedicated unbounded schema (`schema/probe-dyn.sofab.yaml`) and a **heap-only**
roster, baking the **same** caps into every driver — so a disagreement on `A` (under
cap) vs `L` (LIMIT_EXCEEDED, over cap) is a real verdict finding.

```sh
./scripts/run-limits.sh                # cap = 8, corpus/limits/{arr,str,blb}
LIMITS=16 ./scripts/run-limits.sh      # different cap
```

### 5. Coverage pacemaker / fuzzing (`scripts/fuzz.sh`)

The discovery engine. Builds the C driver's libFuzzer front-end (clang:
`-fsanitize=fuzzer,address,undefined`) and runs it with a **structure-aware
mutator** (`engine/mutator/`) that edits the wire at the TLV/varint *field* level —
truncating varints, over-counting arrays, nesting sequences to the depth limit,
injecting NaN/invalid-UTF-8 — so it drives the decoder into deep paths on purpose
instead of by luck. New coverage-increasing inputs grow `corpus/interesting/`;
crashes land in `corpus/crashes/`.

```sh
./scripts/fuzz.sh                              # C pacemaker; grow corpus/interesting
FUZZ_TIME=300 ./scripts/fuzz.sh                # wall-clock budget in seconds (default 120)
CORPUS=corpus/interesting ./scripts/run.sh     # replay what it found through all 12 drivers
```

The mutator is a pure, standalone-testable unit; its safety/determinism soak
(no libFuzzer needed) is:

```sh
cc -std=c11 -fsanitize=address,undefined -Iengine/mutator \
   engine/mutator/test_mutator.c engine/mutator/sofab_mutator.c -o /tmp/mut && /tmp/mut
```

### 6. Clustering (`CLUSTER=1`)

Over a big fuzzed corpus the comparator emits one row per (input, driver-pair) —
thousands of rows for a handful of real bugs. Clustering groups them by
**camp-partition** (which driver-set landed in each output class) so identical root
causes collapse to one entry, ranked by size with a minimal representative.

```sh
CLUSTER=1 CORPUS=corpus/interesting ./scripts/run.sh   # inventory → results/CLUSTERS.md
```

## Findings

The oracle has caught real disagreements across the family. Reproducers in
`findings/`, catalog in [`results/FINDINGS.md`](results/FINDINGS.md), generated-code
defects in [`docs/SOFABGEN.md`](docs/SOFABGEN.md). Fixes live in the **owning
repos**; Crucible is the catalog + acceptance test.

| finding | what | status |
|---|---|---|
| F-0001 | truncated input → three-valued `INCOMPLETE`; lenient vs strict camps — spec §7 | ✅ resolved (family converged on `I`) |
| F-0002 | `corelib-c-cpp` encoder left-shifts a negative value (UB) | ✅ resolved |
| F-0003 | Rust array-fill OOB → panic; then over-count array must be `INVALID` | ✅ resolved (generator#87/#100) |
| F-0004 | invalid UTF-8 in a string: four behaviors driven by the string type — spec §8 | ⏳ open (generator#85, `SOFAB_STRICT_UTF8`) |
| F-0005 | `corelib-cpp` accepts malformed messages the family rejects | ✅ resolved |
| F-0006 | `corelib-py`: truncated wrong-width fixlen fp read `I` instead of `R` | ✅ resolved (corelib-py#38) |
| F-0007 | fixlen-fp `INVALID`-vs-`INCOMPLETE` precedence (C istream) | ✅ resolved (corelib-c-cpp#82) |
| F-0008 | generated **fixed-capacity C++** string/blob-array fill infinite-loops (DoS) on an index ≥ capacity | ⏳ open (generator#126, G-0011) |
| F-0009 | C object API pads a sub-`maxlen` blob to `maxlen` / drops an all-zero blob | 🔎 candidate (found by cross-encode) |

## Status

**Phases 1–3 largely complete; Phase 4 (continuous/CI) next.** The differential
loop runs green across **12 drivers / 10 corelibs** — C (pacemaker), Go, Rust-std,
Rust-no-std, C++, C++/c-cpp, Python-Cython, Python-pure, Java, TypeScript, C#, Zig —
over the full-scale `probe` schema (8 scalar widths, fp32/fp64, string, blob,
numeric + nested-fp + string arrays). Built: the round-trip canonical form, the
structure-aware mutator, limit mode, cross-encode/structured values, auto-clustering,
and a crash- + hang-isolating comparator. Roadmap in [`docs/PLAN.md`](docs/PLAN.md)
§12; open work in [`TODO.md`](TODO.md).

## Layout

| path | what |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | the master plan — everything is built from here |
| [`docs/STATUS.md`](docs/STATUS.md) | current-state snapshot — start here for orientation |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | living as-built architecture + deviations from PLAN |
| [`docs/SOFABGEN.md`](docs/SOFABGEN.md) | generated-code weakness log (codegen defects → the generator) |
| `schema/` | the fuzzed message(s), single source of truth |
| `drivers/<lang>/` | per-language replay driver + coverage front-end (12 drivers) |
| `drivers/common/` | the driver contract |
| `oracle/` | canonical form, comparator, clusterer, allowed-divergence policy |
| `engine/mutator/` | structure-aware TLV/varint grammar mutator (+ standalone soak test) |
| `engine/structured/` | structured-value generator (the cross-encode track) |
| `corpus/` | `seeds/` (green gate), `structured/` (cross-encode gate), `limits/`, `interesting/`, `crashes/` |
| `findings/` | minimized, reproducible divergences (F-0001 … F-0009) |
| `results/` | findings catalog + cluster inventory |
| `scripts/` | `bootstrap`, `run`, `cross-encode`, `run-limits`, `fuzz` |
| `.devcontainer/` | fuzzing toolchains (clang/libFuzzer, cargo-fuzz, Jazzer, Atheris, SharpFuzz, Jazzer.js) |
