# [dart backend] generated `onFixlenHeader` enforces a field's `maxlen` without checking the wire subtype — rejects a §7.3-skippable field

**Repo:** `sofa-buffers/generator` (sofabgen, dart backend)
**Severity:** correctness — a spec-conformant (§7.3) message is rejected as `INVALID`
**Version:** reproduced on CI build `0.0.0-20260723154129-241dc8f44efb` with corelib-dart `f9e64ec`

## Summary

The dart backend now emits a `MessageVisitor.onFixlenHeader(id, subtype, length)` override
(to enforce `maxlen` at the header, per the corelib's new §5.2 INVALID-dominates-truncation
callback). The generated guard checks `length > maxlen` but **does not check `subtype`**, so
a fixlen value whose subtype does **not** match the field's declared type — which
MESSAGE_SPEC §7.3 requires be **skipped** — is instead measured against that field's `maxlen`
and rejected when its payload happens to be longer.

## Reproducer

Schema (excerpt) — a nested struct with a `blob` field, `maxlen 4`:

```yaml
nested:
  id: 10
  fields:
    str:         { id: 2, type: string, maxlen: 32 }
    bytes_field: { id: 3, type: blob,   maxlen: 4 }
```

Wire input (12 bytes) — a **fp64** fixlen value at field id 3 (declared `blob`):

```
56 1a 41 00 00 00 00 00 00 f8 3f 07
```

(`56` open seq id 10 · `1a` fixlen header id 3 / subtype fp64 · length `41`→8 · 8-byte f64
`1.5` · `07` close seq)

- **Expected (§7.3):** subtype fp64 ≠ declared blob → skip the field → decode all-default →
  **accept**. Every other backend (c, cpp, cpp-c-cpp, go, rust×2, py×2, java, ts, cs, zig)
  does this.
- **Actual (dart):** `R invalid_msg`.

A **fp32** at the same slot (`56 1a 20 00 00 c0 3f 07`, 4-byte payload) is accepted by dart
too — the reject only appears when the mismatched payload length exceeds `maxlen`, pinning it
to the `maxlen` guard.

## Root cause

Generated `message.dart`, the `ProbeNested` visitor:

```dart
@override
void onFixlenHeader(int id, int subtype, int length) {
  switch (id) {
    case 2: if (length > 32) e.inv = true; return;   // str,  maxlen 32
    case 3: if (length > 4)  e.inv = true; return;   // blob, maxlen 4
  }
}
```

`onFixlenHeader` fires for **any** fixlen subtype at a field id (the corelib cannot know the
declared subtype — that is schema knowledge only the generated code has). The guard must only
enforce the declared `maxlen` when the wire subtype matches the field's declared fixlen
subtype.

## Suggested fix

Gate each `maxlen` check on the field's declared subtype:

```dart
case 2: if (subtype == FixlenType.string && length > 32) e.inv = true; return;
case 3: if (subtype == FixlenType.blob   && length > 4)  e.inv = true; return;
```

(Only `string` and `blob` fixlen fields carry a `maxlen`; `fp32`/`fp64` fixlen fields have a
fixed width and no `maxlen` guard, so a mismatched fp construct landing on them is already
handled by the width check / skip path.) The same un-gated pattern affects the `string`
field at id 2 — latent only because no test construct's payload exceeds 32 — so the subtype
gate should be applied to every generated `onFixlenHeader` arm.
