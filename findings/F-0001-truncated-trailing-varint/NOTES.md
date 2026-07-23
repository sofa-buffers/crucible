# F-0001 — a truncated trailing varint: Go rejects, C/Rust accept

**Status:** ✅ **RESOLVED — the target is met.** Spec-resolved (§7 finish-less: truncated =
INCOMPLETE), and the family now implements it: **all 12 drivers emit `I`** on both seeds
(was 7-accept vs 5-reject). **Verified green 2026-07-13, re-verified 2026-07-17** — both
reproducers (`80`, `ff ff ff`) live in the green `corpus/regression/` gate, so a
regression fails CI. Tracked upstream as [generator#86](https://github.com/sofa-buffers/generator/issues/86)
(the epic may still be formally open; the observable target is met).

> **Note on the one residual difference:** `java` additionally emits an
> `incomplete_value` payload on `I` (`I 5607a606…`) where the other 11 emit a bare `I`.
> That is the **soft** `incomplete_value` axis (`oracle/policy.yaml`), *not* F-0001's
> verdict axis — the verdict is unanimous. It is one of the 3 soft warnings in the green
> regression gate, and shows up as the largest (soft) cluster in the fuzzer landscape.

*(Historical: this file's earlier status — "still diverging, 7 accept vs 5 reject",
re-verified 2026-07-08 — was stale; the camps collapsed to `I` on 2026-07-13.)*
**Found:** Phase 1 (C + Go); refined through Phase 2 (all 12 drivers)
**Axis:** verdict (hard, per `oracle/policy.yaml`)

## The split — two camps (7 accept, 5 reject)

| impl | verdict on `80` / `ff ff ff` |
|---|---|
| `corelib-c-cpp` | `A u=0 i=0 f=00000000 s=` (accept, all defaults) |
| `corelib-cpp` | `A …` (accept) |
| `corelib-c-cpp` (C++ wrapper) | `A …` (accept) |
| `corelib-rs` (std) | `A …` (accept) |
| `corelib-rs-no-std` | `A …` (accept) |
| `corelib-java` | `A …` (accept) |
| `corelib-cs` | `A …` (accept) |
| `corelib-go` | **`R invalid_msg`** (reject) |
| `corelib-py` (Cython) | **`R invalid_msg`** (reject) |
| `corelib-py` (pure) | **`R invalid_msg`** (reject) |
| `corelib-ts` | **`R invalid_msg`** (reject) |
| `corelib-zig` | **`R invalid_msg`** (reject) |

Note: the camps do **not** split along systems-vs-managed lines — Zig (systems)
rejects while C/C++/Rust (systems) accept, and Java/C# (managed) accept while
Go/Python/TS (managed) reject. It is a per-decoder-design difference.

The C/C++/Rust/Java/C# camp tolerates an incomplete trailing field-header varint and returns the all-defaults message (corelib-cpp does so by design — its `feed`
buffers "an incomplete trailing field … into the accumulator for the next
feed()" and returns `None`). **Four independent lineages — Go, Python, TypeScript, and Zig — reject it.** This
is no longer a lone outlier: four unrelated implementations agreeing on *reject*
is strong evidence the lenient camp is wrong. The wire is an incomplete varint (continuation bit set, no terminating
byte). Reproduce:

```sh
python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(); sys.stdout.buffer.write(struct.pack('<I',len(d))+d)" \
  findings/F-0001-truncated-trailing-varint/06_dangling_varint.bin | ./drivers/c/build/driver
# -> A u=0 ...   (Go's driver -> R invalid_msg)
```

## Analysis

The C/C++/Rust/Java/C# camp tolerates an incomplete trailing varint: the bytes
leave the decoder mid-varint, no complete field was consumed, and `feed` returns OK —
yielding the all-defaults message (corelib-cpp does this deliberately, buffering
the tail for a future `feed`). Go's cursor, Python's decoder (raising `SofaDecodeError`), TypeScript's `Cursor`
(throwing `SofabError`), and Zig's istream (returning `error.InvalidMessage`) all
treat trailing bytes that cannot form a complete field as an invalid message.

This is **not** a driver artifact (verified by hand against all twelve drivers;
the Rust/C++ verdicts come from the corelib's real `feed` `Result`, not the
infallible generated `decode` — see results/FINDINGS.md G-0001/G-0005) and **not**
the empty-input precondition (handled separately; see ARCHITECTURE). It is a real
leniency difference on truncated input. The 7-vs-5 **two-camp** split (rather than
a lone outlier) is stronger evidence for resolving PLAN §8: four independent
lineages reject, so "reject truncated input" is the better-supported reading.

## Resolution path

This was the canonical case behind PLAN §8: is decoding of truncated input
**specified** or **undefined**? **RESOLVED** by MESSAGE_SPEC §7 (finish-less,
documentation PR #12): truncated input is **specified** — it is `INCOMPLETE`, a
distinct **non-error** outcome, neither accept nor reject. So **both** camps are
wrong today: the lenient camp collapses INCOMPLETE→COMPLETE (accepts as done), the
strict camp collapses INCOMPLETE→INVALID (rejects as malformed). The correct
verdict is a third value. This is not a `policy.yaml` allow-entry — it is a
family-wide bug on both sides.

## Implementation

Resolved in **MESSAGE_SPEC §7 (finish-less)**: one-shot `decode` and streaming
`feed` both return `COMPLETE`/`INCOMPLETE`/`INVALID`; there is **no** `finish`
step, and `INCOMPLETE` is an explicit non-error outcome (the caller owns
end-of-input). Two coordinated efforts close this:

- **Corelibs** — epic [generator#86](https://github.com/sofa-buffers/generator/issues/86)
  + 10 per-corelib issues. Lenient camp (c-cpp #72, cpp #27, cs #29, rs #21,
  rs-no-std #37, java #35) **introduces a distinct INCOMPLETE** (don't collapse
  into COMPLETE); strict camp (go #41, py #32, ts #39, zig #11) **splits
  INVALID→INCOMPLETE** (truncation is no longer an error); rs/rs-no-std/ts/zig
  additionally **remove the finish-promotion**.
- **Crucible** — [crucible#8](https://github.com/sofa-buffers/crucible/issues/8):
  canonical form v2 adds the third verdict line `I`; comparator parses `A`/`I`/`R`.

**Target (revised):** F-0001 goes green when **every impl emits `I`** on the
truncated seed — *not* the earlier "every impl rejects". The current 7-accept /
5-reject split all become `I`.

## ✅ Verified green — 2026-07-13

All 10 corelibs implement the finish-less §7 outcome (Camp A + Camp B PRs) and all
12 Crucible drivers were wired to emit the third verdict `I`. Running the
differential over the F-0001 reproducers (`80` and `ff ff ff`) across **all 12
drivers**:

```
2 inputs × 12 drivers (c, go, rust-std, rust-nostd, cpp, cpp-c-cpp,
  py-cython, py-pure, java, typescript, csharp, zig): 0 divergence(s), 2 warning(s)
```

**Every driver now emits `I`** on both seeds — the historical 7-accept-vs-5-reject
split is resolved to unanimous INCOMPLETE. The 2 warnings are the **soft**
`incomplete_value` axis only (java emits `I <partial-hex>`, others bare `I` — a
per-language partial-value materialization difference, not a verdict conflict).

Driver notes: the exception/return-code corelibs (c, cpp, cpp-c-cpp, go, rust-std,
rust-nostd, py-cython, py-pure, ts, zig) propagate INCOMPLETE through the generated
decode; the **status-returning** corelibs (csharp, java) needed a two-pass driver
(verdict from a direct `feed`+status read, value from generated decode) because the
generated one-shot decode discards the status — logged as **G-0008** /
[generator#105](https://github.com/sofa-buffers/generator/issues/105).
