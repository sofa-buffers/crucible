# G-0006 — generated Go `types.go` uses `bytes.Equal` without importing `bytes`

**Status:** ✅ **fixed** in sofabgen 0.15.1 (PR
**Issue:** [generator#84](https://github.com/sofa-buffers/generator/issues/84)

[#90](https://github.com/sofa-buffers/generator/pull/90), fixes #84 — merged 2026-07-08
20:22 UTC, and v0.15.1 was cut 21:43 the same day, so 0.15.1 already carries it) · **Lang:**
go · **Where:** `generator/generators/golang/` (per-file import collection for
named/nested types) · **Severity:** was build-breaking

A blob field inside a **named/nested** struct lands its marshal in `types.go`,
which emits:

```go
if !bytes.Equal(m.BytesField, nil) { e.WriteBytes(3, m.BytesField) }
```

but `types.go`'s import block only has the corelib — **no `"bytes"`**. Go
imports are per-file, so `go build` fails:

```
types.go:140:6: undefined: bytes
```

`probe.go` (which also uses `bytes`) *does* import it, so the top-level message
compiles — but any schema with a blob in a nested struct (e.g. the full-scale
message's `nested.bytes_field`) breaks. Reproduced with sofabgen 0.15.0 against
the arena full-scale schema unchanged.

**Impact on Crucible:** blocked the Go driver for the full-scale schema.
Previously worked around in `drivers/go/build.sh` (inject `"bytes"` into any
generated file that referenced `bytes.` but did not import it); that workaround
was **removed** once 0.15.2 emitted the import correctly — verified: generated
`types.go` now carries its own `"bytes"` import, so the injection no longer
fires.

**Proposed fix:** collect imports per emitted file, not per message — every file
that references `bytes.` (or any std package) must import it.
