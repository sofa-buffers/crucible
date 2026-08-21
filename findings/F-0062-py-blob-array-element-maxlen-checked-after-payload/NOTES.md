# F-0062 — generated Python checks a **blob-array element**'s `maxlen` after reading the payload, so an over-`maxlen` element that is also truncated is reported `INCOMPLETE`

**Status:** 🔴 **OPEN** — [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail; this file is the evidence.
**Guard:** the five vectors in this folder (`r0` + four controls); not yet promoted to `corpus/regression` — promote with the fix, so the gate starts green rather than red.
**Issue:** [generator#377](https://github.com/sofa-buffers/generator/issues/377)
**Codegen:** G-0039 | [generator#377](https://github.com/sofa-buffers/generator/issues/377) | the generator side of F-0062 — the Python backend emits the `blob_array` wrapper element's `maxlen` check *after* `d.bytes()` instead of at the `fixlen_word`, the one site of five in `message.py` that does not use `fixlen_len()`

**Found 2026-08-21** by the nightly ([run 32444261107](https://github.com/sofa-buffers/crucible/actions/runs/32444261107)),
which harvested it as one new camp on a five-byte input and exited non-zero. Reproduced
locally over the merged corpus (19 847 inputs) at the `main` family — corelibs at their
2026-08-21 tips, sofabgen `0.0.0-20260821072613-fdb72c0ea113`.

## The divergence

`ce 0c 22 e3 30` — five bytes, `r0_blob_array_over_maxlen_trunc.bin`:

| bytes | meaning |
|---|---|
| `ce 0c` | header varint 1614 = `(201 << 3) \| 6` — **`blob_array` (field 201), sequence start** |
| `22` | header varint 34 = `(4 << 3) \| 2` — wrapper **element index 4** (< `count` 5, in bounds), wire type fixlen |
| `e3 30` | `fixlen_word` 6243 = `(780 << 3) \| 3` — subtype **blob**, declared payload length **780** |
| — | the message ends here: **zero** of the 780 payload bytes arrive |

`blob_array` is declared `items: { type: blob, count: 5, maxlen: 64 }`, so 780 > 64 is a
schema-bound violation, established **entirely by bytes already on the wire**.

| | verdict |
|---|---|
| c, cpp, cpp-fixed, cpp-c-cpp, cpp-c-cpp-dyn, csharp, dart, go, java, kotlin-jvm, kotlin-native, rust-std, rust-nostd, typescript, zig (15) | `R invalid_msg` |
| **py-cython, py-pure (2)** | **`I`** (incomplete) |

Both Python profiles fail identically, which already rules out the Cython acceleration:
the two builds share the generated `message.py`.

## The controls — this is a defect, not a relaxation

Three of the four controls are the load-bearing part. Each changes exactly one thing.

| vector | what it changes | c / go | py-pure / py-cython |
|---|---|---|---|
| `r0` `ce 0c 22 e3 30` | — (the finding) | `R invalid_msg` | **`I`** |
| `c1` `ce 0c 22 23` | declared length **4 ≤ 64**, cut identically | `I` | `I` ✓ |
| `c2` `ce 0c 22 23 de ad be ef 07` | in-bound **and complete** | `A` (round-trips) | `A` ✓ |
| `c3` `c6 0c 22 e2 30` | same shape on **`string_array`** (id 200, `maxlen` 64) | `R invalid_msg` | `R invalid_msg` ✓ |
| `c4` `56 1a e3 30` | same over-`maxlen` blob as a **plain field** (`nested.bytes_field`, `maxlen` 4) | `R invalid_msg` | `R invalid_msg` ✓ |

`c1` is what makes the finding precise: the *same* truncation with an in-bound declared
length is unanimously `INCOMPLETE`, Python included. So Python's truncation handling is
correct and the split is specifically about **the bound being acted on**. `c2` shows the
path works end to end. And `c3`/`c4` are the sibling diff CLAUDE.md asks for, both *inside
Python*: the same wrapper-element shape one field earlier (`string_array`) and the same
`blob` type outside a wrapper (`nested.bytes_field`) are both correct. Only the
**blob element of a wrapper array** is wrong.

## The mechanism — one site of five, pinned in the generated source

`drivers/python/build/gen/message.py`, emitted by sofabgen
`0.0.0-20260821072613-fdb72c0ea113`. Four of the five `maxlen` sites peek the wire length
first; the fifth reads first and checks the materialized value after:

```python
# field 200 — string_array element (CORRECT)
d.schema_bounded()
if d.fixlen_len() > 64:
    raise SofaDecodeError("self.string_array: string element byte length above schema maxlen 64")
self.string_array[_ef0.id] = d.string()

# field 201 — blob_array element (THE DEFECT)
d.schema_bounded()
self.blob_array[_ef0.id] = d.bytes()          # <-- waits for 780 payload bytes -> INCOMPLETE
if len(self.blob_array[_ef0.id]) > 64:        # <-- never reached on a truncated message
    raise SofaDecodeError("self.blob_array: blob element byte length above schema maxlen 64")
```

`nested.str` (`maxlen` 32), `nested.bytes_field` (`maxlen` 4) and `struct_array.v`
(`maxlen` 16) all use the `fixlen_len()` form too. The fix is to emit the same two lines
for the blob wrapper element — the mechanism is already present in the same file, and
`fixlen_len()` is documented as a pure peek that does not consume the field.

### The `schema_bounded()` call makes it worse than an ordering nit

The generated code *does* call `d.schema_bounded()` on this element. That is not a no-op:
per `vendor/corelib-py/src/sofab/decoder.py:635`, it declares the field schema-bounded so
the **receiver-side cap is not applied** to it (CORELIB_PLAN §6.2.1), and its docstring
states the resulting obligation outright —

> "Declaring is therefore a **promise to enforce**: with the cap off, nothing else stands
> between an untrusted length word and the allocation it implies, so the caller must
> reject a count/length past its declared bound itself (`fixlen_len` gives the wire byte
> length for that, without consuming the field)."

So this site switches `max_blob_len` off and then does not enforce the schema bound at the
word. Besides the wrong verdict, that leaves a sender-declared blob length — up to the
§4.6 ceiling of 2 147 483 647 — with **no bound in force** while the decoder waits for the
payload. The wrong verdict is what the oracle sees; the removed cap is the reason this is
worth fixing promptly rather than filing as a cosmetic ordering issue.

## The spec, verified at the documentation tip (`main@dd2866b`, re-read 2026-08-21)

- **MESSAGE_SPEC §7 preamble** — "*Enforce schema bounds as `INVALID`.* The corelib cannot
  know the schema, so schema-bound violations are detected — and reported — by generated
  code: … a `string`/`blob` whose wire byte length exceeds its schema `maxlen` (§1) … Each
  is malformed input and **MUST** be reported as `INVALID` … **never as `INCOMPLETE`**."
- **MESSAGE_SPEC §7.1** — the bound binds every target; whether it is enforced "**must not
  be an emergent property of the memory model**", and two conformant implementations MUST
  agree on which messages are valid.
- **CORELIB_PLAN §5.2** — `INVALID` wins over `INCOMPLETE`, and, decisively for the
  ordering: "a decoder **MUST** validate a construct's well-formedness **at the point its
  describing bytes are read** — the field header, `fixlen_word`, or count — **before
  consuming, buffering, or waiting for the payload those bytes describe**. A decoder that
  defers the check until the payload has arrived can reach end-of-input first and
  mis-report malformed input as `INCOMPLETE`." That sentence describes this defect exactly.

### Pre-empting the clause that looks like a counter-argument

**CORELIB_PLAN §4.1** says a message ending *inside* a `fixlen_word` is `INCOMPLETE` "even
when the settled low bits already carry a reserved subtype … and even when the field's id
would violate a schema bound (MESSAGE_SPEC §7.1)". That carve-out **does not apply here**:
in `r0` the word is `e3 30` and `0x30` has its continuation flag clear, so the varint
*ends* — the word is wholly present and yields `(length = 780, subtype = blob)`. The
message ends *after* the word, not inside it. §4.1's own rationale draws the same line:
"The `INVALID`-over-`INCOMPLETE` precedence of §5.2 is unaffected: it ranks constructs the
decoder has actually read", and this decoder has read the whole word.

That distinction is also what separates this finding from **F-0061**, whose `r3` ends
*inside* the word and where `INCOMPLETE` is therefore the correct answer.

## Attribution — the generator (sofabgen), Python backend

`maxlen: 64` is a **schema** fact. The corelib is schema-agnostic by design: handed a
fixlen blob declaring 780 bytes with none present, `INCOMPLETE` is the correct and only
answer it can give, and corelib-py gives it. The bound, and the decision to check it at the
`fixlen_word`, belong to generated code — MESSAGE_SPEC §7 says so in as many words, and
corelib-py's `schema_bounded()` docstring hands the obligation to the caller explicitly.

Established, not inferred, by the four steps CLAUDE.md prescribes:

1. **Read both sides** — the generated `message.py` (above) and `corelib-py`'s `bytes()` /
   `fixlen_len()` / `schema_bounded()` (`vendor/corelib-py/src/sofab/decoder.py:635,892,940`).
2. **Who could have rejected** — only the caller knows 64; the corelib was handed a length
   and faithfully waited for it. The corelib is correct and its caller is the bug.
3. **Sibling profiles** — `py-cython` vs `py-pure` agree (so: not the accelerated path),
   and within one language `string_array` (`c3`) and `nested.bytes_field` (`c4`) are both
   correct while `blob_array` is not. A split *inside* one language, at one emitter site.
4. **Cross-backend** — TypeScript emits `c.readBlob(64)`, passing the bound into the reader
   so it decides at the word. Python's `d.bytes()` takes no bound, and the peek it should
   have used sits unused at this one site.

This is the **F-0043 / G-0018 class** (schema-bound `INVALID` decided after the payload).
That class was closed for the plain-field path — `c4` proves Python is fixed there — but
[generator#267](https://github.com/sofa-buffers/generator/issues/267), the ticket that
closed F-0043, is scoped `[rust, rust-no-std, java, csharp, zig]` in its title and never
covered Python's **blob wrapper-element** emitter. So this is a missed site of a fixed
class, not a regression.

## Suggested fix

In the Python backend's wrapper-array element emitter, use the `fixlen_len()` form for the
`blob` case exactly as the `string` case already does:

```python
d.schema_bounded()
if d.fixlen_len() > 64:
    raise SofaDecodeError("self.blob_array: blob element byte length above schema maxlen 64")
self.blob_array[_ef0.id] = d.bytes()
```

`r0` then rejects at the word, and `c1`–`c4` must stay exactly as they are — `c1` in
particular, since a fix that merely dropped the bound would also turn `r0` green.

## Measurement

| | |
|---|---|
| corpus | `corpus/interesting`, 19 847 inputs (CI's 10 969 merged into the local 19 157) |
| result | 9 127 agree, 10 720 diverge → **2 camps**, 1 accounted for, **1 new** (this one) |
| roster | all 17 — first measured on 16 (no Kotlin/Native toolchain in this workspace), then re-measured with `kotlin-native` built locally: **identical counts**, and it rejects `r0` as CI reported |
| family | corelibs @ `main` 2026-08-21, sofabgen `0.0.0-20260821072613-fdb72c0ea113` |
