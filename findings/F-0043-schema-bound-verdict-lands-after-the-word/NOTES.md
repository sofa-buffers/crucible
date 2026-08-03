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

---

## Attribution addendum 2026-08-02 — the generator **cannot** fix this alone

Written for the review of [generator#267](https://github.com/sofa-buffers/generator/issues/267)
after the question came up whether corelib changes are needed. **They are** — for one camp, and
the camp split in this finding is exactly the architectural split that causes it.

### The mechanism

Generated code already performs the right check. In the rust-no-std backend, for instance, the
string sink carries it verbatim:

```rust
(_Loc::Root_nested, 2) => if total > 32 { self.inv = true; return; },
```

`total` is the declared length, and the corelib parsed it from the fixlen word. The defect is
not that the check is missing or late in *generated* code — it is that **the callback carrying
`total` never fires when the message ends at the word**. No callback, no check, so the verdict
falls through to `INCOMPLETE`.

### Verified in source, all five impls of the wrong camp

Each gates the visitor call on having payload bytes in hand:

| corelib | site | gate |
|---|---|---|
| `corelib-rs` | `src/istream.rs` | `let chunk = &buf[pos..pos + len]; v.string(id, len, 0, chunk)` — needs `len` bytes present |
| `corelib-rs-no-std` | `src/istream.rs:308` | `if self.core.state == State::FixlenRaw { … visitor.string(self.id, self.fixlen_total, offset, chunk) }` |
| `corelib-zig` | `src/istream.zig:376` | `visitor.string(st.id, st.total, offset, chunk)` inside the raw-payload path |
| `corelib-java` | `IStream.java:360` | `if (state == S_FIXLEN_RAW) { … visitor.string(id, fixlenTotal, chunkOffset, data, i, take); }` |
| `corelib-cs` | `IStream.cs:213` | `if (_state == State.FixlenRaw) { … visitor.String(_id, _fixlenTotal, chunkOffset, data, i, take); }` |

Each of these *does* have a zero-payload `string(id, 0, 0, …)` call — but only for a **declared
length of 0**, where `total` is 0 rather than the violating number. It is not a header hook.

**Those five are precisely this finding's wrong camp** for `over_len_string_trunc_004`
(rust-std, rust-no-std, java, csharp, zig).

### Why the other camp gets it right

They do not read the value through a payload-carrying visitor callback at all:

- **typescript** — generated code uses the **cursor/pull** API (`c.wire`, `c.fixSub`,
  `c.readFp32Raw()`), so the length word is inspectable *before* the payload is requested.
- **c / cpp-c-cpp** — the object-descriptor path, where the corelib holds the schema and can
  decide at the word itself.
- **go / py / dart** — likewise surface the length before delivering payload.

So the split is not "some backends are careless". It is **push/visitor versus pull/descriptor**,
and no amount of codegen can move a decision earlier than the earliest callback it is given.

### What the fix needs

A header-level hook in the five push/visitor corelibs — either a dedicated
`fixlenHeader(id, total, subtype)`, or firing `string`/`blob` once with `offset = 0` and an
empty chunk immediately after the fixlen word — plus backends that consume it.

**There is a precedent in this repo for exactly this shape: F-0042.** The corelib array-header
hook was widened to carry the fixlen element subtype (seven corelib issues, all closed
2026-08-01) and the backends consume it in generator#259. Same problem, same resolution:
generated code cannot decide at a word the corelib never shows it.

*Scope note:* the wrapper-element rows (`string_array_over_id_trunc_004`,
`blob_array_over_id_trunc_004`) have a different camp — go and dart join the wrong side there —
so the element-id half may need its own analysis. What is established above is the `maxlen` half.

---

## Addendum 2026-08-03 — the same rule at a **third** bound: the declared integer width

The 4-hour pacemaker round produced a cluster that isolates to this finding's rule on an axis it
did not previously cover. **`width_elem_trunc.bin`** = `a6 06 0c 05 b0 51` (6 B) — `arrays.i8`
(`count 5`) declares five elements, the first carries **5208** (far outside `i8`), and the
message ends there.

| verdict | drivers |
|---|---|
| `R invalid_msg` (**correct** — §5.2, INVALID dominates INCOMPLETE) | c, cpp-c-cpp, csharp, java, rust-no-std, rust-std, zig (7) |
| `I` | cpp, dart, go, py-cython, py-pure, typescript (6) |

The violating element is **fully on the wire** — only elements 2–5 are missing — so every
implementation has read it. `ctl_width_elem_inrange_trunc.bin` is the same truncation with an
in-range element and is unanimous `I`, so the truncation alone is not the trigger.

**Five of the six deferrers reject the *complete* form.** dart, go, py-cython, py-pure and
typescript all emit `R invalid_msg` when the array is closed — they detect the violation, just
not until the array finishes. That is exactly this finding's defect (the verdict lands after the
word rather than at it), now shown on the **declared integer width** bound that documentation#32
added, alongside the `maxlen` and element-id bounds already documented above.

**`cpp` is in this camp for a different reason** and is *not* an instance of this finding: it
never detects the over-width element at all, complete or truncated, because the C++ backend
leaves `readArray`'s element-width bound unarmed — split out as
[F-0052](../F-0052-cpp-array-element-width-bound-never-armed/NOTES.md). Counting it here would
overstate this finding's camp by one.

*Not yet added to generator#267*, which is under review: the issue's own camps are unchanged
(re-verified 2026-08-03, all four clusters byte-for-byte as catalogued), and this is a new axis
rather than a correction. Worth appending once the review settles.

---

## Addendum 2026-08-03 (b) — one byte finer, and five more impls are late

The nightly-corpus review produced a cluster that is this finding's rule at a **finer truncation
offset** than any row above, and it moves five implementations from the correct camp into the
late one.

**`overindex_trunc_in_fixlen_word.bin`** = `c6 0c 2a c2` (4 B) — `string_array` opened, an
element at index 5 (`count: 5`, so over-index), and the message ends **inside** the fixlen word:
`c2` is the first byte of an unfinished varint.

| verdict | drivers |
|---|---|
| `R invalid_msg` (**correct**) | **typescript** only |
| `I` | the other 12 |

### Why typescript is the correct one here

The existing rows stop at the *coarser* offset: `ctl_overindex_trunc_at_header.bin`
(`c6 0c 2a`, ending right after the element header) is unanimous `I`, and correctly so —
corelib-cpp's own reader documents why: *"only a message ending between the element header and
its fixlen word is INCOMPLETE rather than INVALID, since there the subtype, and with it whether
the field is an element at all, is not yet decidable."*

But one byte later the subtype **is** decidable. A `fixlen_word` is
`(length << 3) | subtype`, so the subtype occupies the low three bits of its **first** byte —
`0xc2 & 7 == 2 == String` — regardless of how many bytes the varint goes on to use. At that
point the element has passed the §7.3 test (wire type Fixlen, subtype String), it *is* an
element of this array, its id is over `count`, and §7.1 makes that `INVALID` — which §5.2 says
outranks the truncation. Only the *length* is still unknown, and the verdict does not depend on
it.

`ctl_overindex_mistyped_skipped.bin` confirms the ordering is otherwise sound everywhere: an
over-index element whose wire type contradicts the schema is skipped per §7.3 by all 13, with no
reject — so nobody is applying the bound ahead of the type test.

### What it adds to this finding

The catalogued wrapper rows put **c, cpp, cpp-c-cpp, py-cython, py-pure** in the *correct*
camp. They are correct only at the coarser offset: with the truncation one byte later, all five
join the late camp, and only typescript decides at the earliest point the wire permits. The
finding's reach is therefore wider than its rows suggest — the "correct" side of the
`string_array_over_id` row is a matter of degree, not of conformance.

*Not appended to generator#267 while it is under review* — same reasoning as the width addendum:
the issue's own camps are unchanged, and this refines rather than corrects them.
