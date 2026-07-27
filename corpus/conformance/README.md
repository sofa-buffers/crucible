# corpus/conformance — §2/§3 canonicality conformance seeds (WP-08)

Small hand-built seed set pinning the MESSAGE_SPEC §2/§3 canonicality rules by name
(rather than incidentally, as every value corpus does). Run as a blocking gate:
`CORPUS=corpus/conformance ./scripts/run.sh` — all 13 drivers must agree, and the
round-trip re-encode must be canonical.

Written against the **POC `omit-all-default-sequences` spec** (§2 uniform ≠-default
rule: an all-default sequence-typed *field* is **omitted**; an empty frame there is a
non-canonical encoding of the omitted field, accepted and normalized away). The `a`
vector asserted the opposite — "always framed" — under the pre-POC spec; its bytes
are unchanged, its meaning flipped with the spec.

| seed | rule | assertion |
|---|---|---|
| `a_nested_all_default_empty_frame.bin` | **§2** — a decoder MUST accept a present-but-childless sequence at a field position and treat it as the omitted field; a re-encode normalizes the frame away. | the message sets `u8=1` and carries **every** sequence field as an explicit empty frame (`nested`, `arrays` + its nested chain, `string_array`, `blob_array`). All 13 accept and re-encode to `0001` — byte-identical to `a_ctl_omitted.bin`. A driver that keeps any frame (the pre-POC canonical) diverges. |
| `a_ctl_omitted.bin` | control | the canonical form of `a`'s value: `u8=1`, every all-default sequence omitted (`0001`). Round-trips identically and equals `a`'s re-encode, proving the normalization. |
| `b_array_trailing_defaults_noncanonical.bin` | **§3** — a decoder MUST accept a non-canonical trailing-default array run (encoders MUST NOT emit it), and re-encode it canonically (trailing run trimmed — the F-0010 rule). | `arrays.u8` = `[1,2,3,0,0]` (count 5, two trailing defaults) → all 13 accept and re-encode to **count 3 `[1,2,3]`** (identical to `b_array_canonical_ctl.bin`). |
| `b_array_canonical_ctl.bin` | control | the canonical `[1,2,3]` form — round-trips identically and equals `b`'s re-encode, proving the trim. |
| `d_empty_frame_only.bin` | **§2 consequence** — the all-default message encodes to **zero bytes**. | the input is nothing but one empty frame (`seq[10]()`, bytes `5607`); it decodes to the all-default message and all 13 re-encode it to the **empty byte string** (`A` with empty hex). The inverse of the `01_empty.bin` seed (0-byte input → all-default value): here a non-empty input must *produce* the 0-byte canonical form. |

The per-position / per-shape enumeration of the §2 empty-frame rules (every sequence
position, zero-count compact arrays, merged and chained empty frames, the union §4.2
identity-loss corners) is `engine/structured/sweep_empty_frame.py` — a blocking sweep
axis. This corpus keeps the byte-exact input/control pairs a human can diff.

**Not here yet — (c), blocked on WP-05.** §2's *only* conformant empty frame — an
explicit `[]` overriding a **non-empty** declared field `default` — is untestable
today: no `probe` field declares a non-zero `default:`. It lands with WP-05
(`struct_array`, whose `struct{k,v}` element can carry a non-empty default) — see
docs/TODO.md.
