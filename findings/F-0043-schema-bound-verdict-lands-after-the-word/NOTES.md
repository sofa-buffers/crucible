# F-0043 — a schema-bound violation is not INVALID until payload bytes arrive

**Found 2026-08-01** by re-enabling the F-0032 carve-out in
`engine/structured/sweep_malform_truncate.py` against corelibs **0.10.0** + sofabgen
**0.22.0**. The axis grew 43 → 96 vectors and 8 of the new ones diverge. F-0032 itself
(truncating *into* the payload of a schema-bound malformation) is resolved — this is the
**boundary offset** the old carve-out hid: the malformation is fully on the wire, and the
message is cut immediately after the word that establishes it.

## The rule

CORELIB_PLAN §5.2: **INVALID dominates INCOMPLETE.** Once the bytes seen so far are
already malformed, running out of input cannot downgrade the verdict. MESSAGE_SPEC §7
adds that a schema-bound violation (`maxlen`, `count`, element id ≥ `N`) is INVALID,
"never as `INCOMPLETE`". So the verdict must be decided **at the word that carries the
violating number** — the fixlen length word, or the wrapper element header — not after
its payload has been buffered.

## The split

| vector | bytes | `R invalid_msg` | `I` (incomplete) |
|---|---|---|---|
| `over_len_string_trunc_004` | `56 12 8a 02` | c, go, cpp, cpp-c-cpp, py-cython, py-pure, typescript, dart (8) | rust-std, rust-nostd, java, csharp, zig (5) |
| `over_len_blob_trunc_003` | `56 1a 2b` | c, go, cpp, cpp-c-cpp, typescript, dart (6) | rust-std, rust-nostd, py-cython, py-pure, java, csharp, zig (7) |
| `over_len_blob_trunc_004…007` | `56 1a 2b 00 …` | the other 11 | py-cython, py-pure (2) |
| `string_array_over_id_trunc_004` | `c6 0c 2a 0a` | c, cpp, cpp-c-cpp, py-cython, py-pure, typescript (6) | go, rust-std, rust-nostd, java, csharp, zig, dart (7) |
| `blob_array_over_id_trunc_004` | `ce 0c 2a 0b` | same 6 | same 7 |

In every row the truncation point is exactly `invalid_at` — the first byte *after* the
word that makes the message invalid. `str` has `maxlen: 32` and the string declares 266
bytes; the blob declares 43 against `maxlen: 5`; the wrapper element id is 5 against
`count: 5`.

**Controls** (`ctl_*_complete.bin`, the same malformations untruncated): all 13 agree on
`R invalid_msg`. So no implementation disputes that the message is malformed — they
disagree only on **when** that is decided, which is visible only under truncation.

## Two distinct behaviours, one class

1. **Off-by-one at the word** — rust-std, rust-nostd, java, csharp, zig (plus go/dart on
   the wrapper rows): the check fires once the *first payload byte* is in hand rather
   than at the word itself. Truncate one byte earlier and the verdict silently becomes I.
2. **Deferred to payload completion** — py-cython, py-pure on `over_len_blob`: I at every
   offset 3…7, i.e. the `maxlen` comparison waits for the whole blob to be buffered. The
   stronger form of the same defect. (Note python is in the *correct* camp for the string
   and wrapper rows, so this is per-path, not a global policy.)

That the camps differ per row — `go`/`dart` correct on the fixlen rows but late on the
wrapper rows, python the reverse — is the signal that this is **per-check ordering** in
generated code, not one shared helper.

## Attribution — generated code (a G-number), not the corelibs

`maxlen`, `count` and the element-id bound are **schema facts**; MESSAGE_SPEC §7 states
the corelib cannot know them and that generated code detects *and reports* them. The
corelib hands over the length/element word and its number faithfully; what varies is
where the emitted check sits relative to payload accumulation. Compare the java string
path, which already has the correct shape for the *destination* question
(`drivers/java/build/gen/src/main/java/message/Probe.java:337` — resolve, then leave
before a byte is buffered) but still runs the `maxlen` comparison after that point.

File against **generator** as one issue covering the affected backends, with the
per-backend rows above.

## Repro

```
CORPUS=findings/F-0043-schema-bound-verdict-lands-after-the-word ./scripts/run.sh
```

The axis that found it stays carved out in `sweep_malform_truncate.py` (STRUCTURAL-only
broadened truncation) until this closes; re-enable is a two-line deletion there.
