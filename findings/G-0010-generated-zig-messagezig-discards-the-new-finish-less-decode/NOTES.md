# G-0010 — generated zig `message.zig` discards the new finish-less decode `Status`

**Status:** ✅ **fixed in sofabgen 0.16.2** (generator [#120](https://github.com/sofa-buffers/generator/issues/120),
commit `26f1f4c` / PR #121) + a Crucible `drivers/zig/driver.zig` update. Surfaced
2026-07-15 pulling corelib-zig `main` (`0f861e4`, "decode: replace finish() with
feed(chunk)→status", plan §5/§6.1); fixed the same day. **Lang:** zig · **Where:**
the generator zig backend (generated `message.zig`), plus the Crucible
`drivers/zig/driver.zig`. The rest of this entry documents the original break.

**Fix as shipped:** the generated `Probe.decode` now returns `DecodeError!Probe`
where `DecodeError = sofab.Error || error{IncompleteMessage}`; it binds the corelib's
`feed(chunk)→Status` and returns `error.IncompleteMessage` when the terminal status
is `.incomplete` (generated `message.zig` L146-158). The Crucible driver maps that
error to the `I` verdict — `drivers/zig/driver.zig` changed `error.Incomplete` →
`error.IncompleteMessage` at both the verdict test and the reject-class switch.
Verified: zig builds `-OReleaseSafe`, `80` → `I`, empty → `A`, and the full
12-driver seed + limit box is green.

**What:** corelib-zig adopted the finish-less MESSAGE_SPEC §7 model — its `decode`
and `feed` now return `Error!Status` where `Status` is `{ complete, incomplete }`,
and **INCOMPLETE is a returned `Status`, not an error** (`istream.zig`: `pub fn
decode(buf, visitor) Error!Status`). sofabgen 0.16.1's zig backend predates this and
still emits:

```zig
try sofab.decode(data, &v);   // Error!Status now — the Status is ignored
```

which fails to compile: `error: value of type 'istream.Status' ignored`. And the
Crucible zig driver still switches on `error.Incomplete`, which is no longer a
member of the corelib's error set (`error: 'error.Incomplete' not a member of
destination error set`).

**Why it matters:** this is the **zig analogue of G-0008** (which fixed the same
INCOMPLETE-as-returned-status gap for C# and Java via status-surfacing
`TryDecode`/`tryDecode`). The corelib moved correctly to §7; the generated glue and
the driver must catch up or a zig consumer cannot tell COMPLETE from INCOMPLETE (and
here, cannot even build).

**Fix:** (1) generator zig backend surfaces the terminal `Status` from the generated
one-shot decode (a `tryDecode`-equivalent), mirroring the cs/java G-0008 fix; (2)
`drivers/zig/driver.zig` reads the `Status` and maps `.complete`→`A <hex>` /
`.incomplete`→`I`, dropping the `error.Incomplete` arm. Until both land, zig is held
out of `scripts/run.sh` / `run-limits.sh` (the box runs over the other 11 drivers).
