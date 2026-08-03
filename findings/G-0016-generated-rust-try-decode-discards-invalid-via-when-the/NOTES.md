# G-0016 — generated Rust `try_decode` discards INVALID via `?` when the message is also truncated

**Status:** ✅ **fixed in sofabgen 0.19.4** ([generator#190](https://github.com/sofa-buffers/generator/issues/190), 2026-07-21). Finding
[`F-0024`](../findings/F-0024-rust-trydecode-incomplete-over-invalid/NOTES.md). Generator-only
(sofabgen **Rust backend**); no corelib change. **Re-verified:** the generated `try_decode` now emits
the ordered form below (`message.rs:235/242/246`); the 4 isolates → 0 divergences across all 12, and
the malform×truncation sweep (§5.2) is green — all 18 malformed×{complete,trunc} → `R`, 0 conformance
failures. The axis was promoted from report-only to blocking and the vectors into `corpus/regression/`
(`F0024_*`). Below is the original defect (0.19.3).

The emitted `probe_dec::try_decode` (generated `message.rs`) does:

```rust
is.feed(data, &mut v)?;                          // (~234)  ← `?` returns feed's Err(Incomplete) here
invalid = v.inv;                                  // (~236)  ← skipped under truncation
…
if invalid { return Err(sofab::Error::InvalidMsg); }   // (~240)  ← skipped
```

The generated visitor sets the sticky `v.inv = true` for every **schema-bound** violation the corelib
cannot know: invalid UTF-8 (`from_utf8 => Err => self.inv = true`), over-count arrays (`else { self.inv
= true }`), over-length string/blob (`if total > N`), `string_array` element id ≥ 5. But `IStream::feed`
returns `Err(Error::Incomplete)` whenever the bytes end mid-item, and the **`?`** propagates that
*before* `v.inv` is consulted. Net effect: an input that is **both** malformed **and** truncated decodes
to `Incomplete` (`I`) instead of `InvalidMsg` (`R`) — a MESSAGE_SPEC §5.2 precedence violation (INVALID
must dominate INCOMPLETE).

**Established as codegen, not corelib:** corelib-rs `feed` correctly reports only the *structural*
outcome (`istream.rs:170-176`); `deliver_payload` returns `usize` (no error) and the `string` visitor
callback is default-empty (`istream.rs:57`) — UTF-8 and schema bounds are the generated visitor's job.
The other shared-callback backends (csharp/java/zig) and all non-callback backends emit `R` on the same
input, so the mis-ordering is specific to the Rust backend's template.

**Fix (symmetric, one template for `rs` + `rs-no-std`):**

```rust
let r = is.feed(data, &mut v);
if v.inv { return Err(sofab::Error::InvalidMsg); }   // §5.2: INVALID dominates INCOMPLETE
r?;                                                   // only then surface a clean truncation
```

Found by the 8 h pacemaker round (2.24 G execs) as the dominant divergence class (63 % of sampled
verdict-splits); delta-debugged to an 11-byte reproducer with a four-vector control set that isolates
ordering from validation.
