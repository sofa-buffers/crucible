# F-0047 — a §7.3-mistyped **sequence** at a string-element position is entered, not skipped — but only when it has content

**Found 2026-08-01** by delta-minimizing cluster 10 of the 3-hour pacemaker round
(corelibs **0.10.0** + sofabgen **0.22.0**): **136 bytes → 8 bytes**.

The §7.3 analogue of **F-0044**. F-0044 is an *unknown id* sequence whose children leak into
the enclosing scope; this is a *declared element position* receiving a sequence where a
`string` is declared — the field must be skipped whole, but its children are still bound.

## Why F-0023's regression vector does not catch it

**F-0023 covers this exact construct** (`F0023_strelem_recv_sequence.bin`, in
`corpus/regression/`, green) — a `string_array` element receiving a sequence, skipped per
§7.3 on all 13. The difference is one thing only: **that vector's sequence is empty.**

| element | result |
|---|---|
| mistyped sequence element, **empty** | all 13 agree — skipped correctly (this is F-0023's vector) |
| mistyped sequence element, **with a child** | **6 impls enter it and bind the child** |

An empty frame has no children to leak, so the defect is invisible to it. This is the same
blind spot F-0044 exposed for unknown ids, and it is why the finding survived a green gate.

## The reproducers

**`seq_elem_with_content.bin`** = `c6 0c c6 0c 02 12 4b ff` — `string_array` opened, an
element at index 200 opened as a **sequence**, carrying a `string` `4b ff` ("K" + a lone
`0xFF`), message ends there.

| verdict | drivers |
|---|---|
| `I` (**correct** — element skipped, message merely truncated) | c, cpp, cpp-c-cpp, go, py-cython, py-pure, typescript (7) |
| `R invalid_msg` | **csharp, dart, java, rust-std, rust-no-std, zig** (6) |

**`seq_elem_valid_index.bin`** = `c6 0c 06 02 12 4b ff` — the same, at element index **0**
(well within `count: 5`). Same split. So the over-index is **not** the trigger; the fuzzer's
input merely happened to carry one.

**`seq_elem_value_bound.bin`** = `c6 0c c6 0c 02 12 4b 41 07 07` — the same shape with a
**valid, complete** string "KA" and both frames closed. All 13 accept, but:

| re-encodes to | drivers |
|---|---|
| *(empty — the element was skipped)* | c, cpp, cpp-c-cpp, go, py-cython, py-pure, typescript (7) |
| `c6 0c 02 12 4b 41 07` — i.e. `string_array[0] = "KA"` | csharp, dart, java, rust-std, rust-no-std, zig (6) |

This is the clearest statement of the bug: the child of a skipped element is **bound into the
array**. The `R` verdicts above are the same defect meeting an invalid/truncated payload —
once you have descended into the sequence, its string is materialized and validated, so the
verdict flips too.

## Controls

| control | bytes | result |
|---|---|---|
| `ctl_empty_seq_elem` | `c6 0c c6 0c 07 07` | **all 13 agree** — an empty mistyped element is skipped (F-0023 still holds) |
| `ctl_valid_string_elem` | `c6 0c 02 12 4b 41 07` | **all 13 agree** — a correctly typed string element decodes normally |

So it is neither the mistyped element as such nor the string as such: it is a mistyped
sequence element **that has content**.

## Attribution — generated code

Which wire type a declared element position expects is a schema fact; the corelib reports the
frame faithfully. Per CLAUDE.md's triage this is `generator`.

Same shape as **G-0028 / generator#268** (F-0044): a scope that should have been switched to
"skipping" is not, so children continue to be dispatched against the enclosing destination.
There it is an unknown id at any sequence position; here it is a §7.3-mistyped element inside
a wrapper array. The camps are nearly the same — F-0044's five plus **dart**.

**The fix** is the same as #268's: entering a sequence that must be skipped has to set a
skipping scope that every child hook honours until the matching `SEQ_END`, rather than
leaving the destination pointed at the enclosing array.

## Spec basis

MESSAGE_SPEC §7.3: a field whose header wire type contradicts its declared type **MUST** be
skipped *"exactly as a field with an unknown id is skipped"*, and a decoder **MUST NOT**
decode its payload into the declared field. CORELIB_PLAN §5.2 spells out what skipping a
sequence means: *"Skip — do nothing; the field's remaining bytes, **or the entire
sub-sequence**, are consumed and discarded"*; §4.9 gives the mechanism (*"walk it to its
matching end, descending into nested sequences and tracking depth"*).

## Coverage gap

`sweep_empty_frame` and F-0023's vector both exercise the mistyped/empty sequence element.
Nothing exercises a skipped sequence **carrying a child** — the same gap F-0044 exposed for
unknown ids. One axis covers both: *skipped sequence × {empty, scalar child, string child,
nested sequence child}*, at every sequence position. See `docs/TODO.md`.

## Repro

```
CORPUS=findings/F-0047-mistyped-sequence-element-is-entered-not-skipped ./scripts/run.sh
```

---

## Addendum 2026-08-02 — a second symptom, and a **seventh** affected impl

The **Go steering engine**'s first run produced a cluster that minimized (374 B → **5 B**) to
this finding's construct with a different symptom and a wider camp.

**`seq_elem_child_overindex.bin`** = `c6 0c 26 2a 02` — `string_array` opened, element index 4
opened as a **sequence** (mistyped, §7.3 says skip), and inside it a child at id **5**.

| verdict | drivers |
|---|---|
| `I` (**correct** — element skipped, message merely truncated) | c, cpp-c-cpp, go, py-cython, py-pure, typescript (6) |
| `R invalid_msg` | **cpp**, csharp, dart, java, rust-no-std, rust-std, zig (**7**) |

### The mechanism, pinned by a threshold

`string_array` declares `count: 5`, so valid element indices are 0–4. Sweeping the child id:

```
child id  0 1 2 3 4 | 5 6 7
verdict   all agree | 7 reject
```

The break is **exactly at 5**. A decoder that leaks the child into the enclosing *wrapper*
scope makes it element index 5, over the `count` bound, and §7.1's over-index check fires —
flipping the verdict. `ctl_child_id_in_range.bin` (id 4) and
`ctl_child_overindex_struct_scope.bin` (the same id 6 inside `nested`, a struct with no `count`)
both agree on all 13, so it is the wrapper's bound and nothing else.

This is the same defect as the body of this finding — the child of a skipped element is bound
into the array — but where the original vectors show it as a *value* (`string_array[0] = "KA"`),
this shows it as a *verdict flip*. Same shape as F-0044's second symptom.

### `cpp` is new, and may have a different owner

The original vectors put **cpp in the correct (`I`) camp**; re-verified 2026-08-02, they still
do. This vector puts it in the rejecting camp, so **cpp is affected and generator#272's impl
list is incomplete**.

But cpp's half may not be codegen. Its generated code does not walk the wrapper itself — it
hands the whole thing to the corelib:

```cpp
case 200: { sofab::StringSeq _r0{string_array, 5, 64}; is.read(_r0); }
```

The count bound is passed *in*, and enforcement lives in **corelib-cpp**'s `StringSeq` reader.
So for the six flat-visitor backends this remains G-0031 / generator#272, while cpp's inclusion
should be confirmed against corelib-cpp's reader before it is added there — the "occasionally
both" case CLAUDE.md warns about. **Not yet filed** pending that check.
