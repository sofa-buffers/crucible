// Crucible Rust driver — shared body for BOTH corelibs (corelib-rs / corelib-rs-no-std).
//
// build.sh prepends a per-variant preamble that brings `Probe` into scope:
//   std     : `mod message; use message::Probe;`
//   no-std  : `use sofabuffers_generated::Probe;`
// The `sofab` crate (either corelib) is a dependency of both, so the imports
// below resolve unchanged.
//
// Single-pass decode via the generated fallible `Probe::try_decode` (sofabgen
// 0.16.0 — G-0001 fixed, see docs/SOFABGEN.md): it runs the real generated visitor
// AND returns the §7 outcome as a `Result`, so one call yields both the verdict
// and the value. This replaced the earlier two-pass workaround, which recovered
// the verdict by re-running `IStream::feed` against a null visitor because the old
// infallible `Probe::decode` discarded feed's Result. Because the null visitor
// skipped the generated per-field checks, that workaround also missed the
// over-count-array rejection (generator#100); try_decode runs them, so rust now
// converges with the family on those inputs (was the F-0003 residual divergence).
//
// LimitExceeded (generator#102) maps to a fourth verdict `L`, gated behind the
// `limit` cargo feature: the arm is std-only (corelib-rs-no-std's Error has no
// LimitExceeded variant), so build.sh enables `limit` for the `rs` variant only.
// It fires solely under a configured cap (limit mode); with no cap it never occurs,
// so the default conformance run is unchanged.
//
// Emits the canonical form (oracle/canonical.md) over the replay protocol
// (drivers/common/CONTRACT.md).
use sofab::Error;
use std::io::{Read, Write};

fn reject_class(e: Error) -> &'static str {
    match e {
        Error::InvalidMsg => "invalid_msg",
        Error::Argument => "argument",
        Error::Usage => "usage",
        Error::BufferFull => "buffer_full",
        _ => "other", // Error is #[non_exhaustive]
    }
}

// ---- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 -------
//
// The default accept path re-encodes the decoded value to wire (schema-agnostic,
// but blind to a decode that differs only where the sparse-canonical wire elides —
// canonical.md §Tradeoff). This path instead walks the DECODED value and dumps every
// field + every array element explicitly, matching engine/structured/materialize.py
// byte-for-byte. The value is already faithful (the decoder fills numeric/fp arrays
// to N, grows the wrapper Vecs to highest-populated-index + 1, and omitted scalar
// fp fields decode to their +0.0 default), so we dump it as-is with no normalization.
//
// The walker itself is NOT hand-written: `materialize_gen.py` unrolls the schema
// descriptor (oracle/materialized-schema.json) into straight-line field-access code
// at build time, and build.sh drops it beside this file as `materialize_gen.rs`
// (Rust has no runtime reflection, so a runtime table cannot drive it — the source is
// generated instead). A schema change regenerates the walker with zero edits here.
//
// The generated `pub fn materialize(m: &Probe) -> String` compiles for BOTH corelibs:
// it touches only member APIs shared by the std and no_std container flavors
// (`.as_bytes()` on strings, slice-deref `&x[..]` on blobs, `.iter()` over the
// wrappers — the numeric/fp scalar and array fields are identical in both) and builds
// its output with `core::fmt::Write` into a `String` (the driver binary is always std
// for both corelib variants). We then write those bytes to the std::io sink exactly as
// the round-trip path does.
include!("materialize_gen.rs");

fn canonical(out: &mut impl Write, data: &[u8], materialize_mode: bool) {
    match Probe::try_decode(data) {
        Ok(m) => {
            if materialize_mode {
                // COMPLETE, materialize mode: dump the decoded value (materialized.md).
                let _ = write!(out, "A ");
                let _ = out.write_all(materialize(&m).as_bytes());
                let _ = writeln!(out);
                return;
            }
            // COMPLETE: re-encode the decoded value -> hex.
            let bytes = m.encode();
            let _ = write!(out, "A ");
            for b in bytes.iter() {
                let _ = write!(out, "{:02x}", b);
            }
            let _ = writeln!(out);
        }
        Err(Error::Incomplete) => {
            // INCOMPLETE (MESSAGE_SPEC §7): the bytes end mid-message — the third
            // canonical verdict, neither accept (A) nor reject (R). Not an error.
            let _ = writeln!(out, "I");
        }
        #[cfg(feature = "limit")]
        Err(Error::LimitExceeded) => {
            // LIMIT_EXCEEDED (generator#102, limit mode only): a configured
            // receiver-side cap on a schema-unbounded field was exceeded. A policy
            // rejection distinct from INVALID — its own verdict `L`, not `R`.
            let _ = writeln!(out, "L");
        }
        Err(e) => {
            let _ = writeln!(out, "R {}", reject_class(e));
        }
    }
}

fn main() {
    // Materialize mode (oracle/materialized.md): on a COMPLETE decode, emit a value
    // dump instead of the re-encoded wire hex. Read once at startup; every other
    // verdict path is unaffected. The driver binary is std for both corelib variants,
    // so std::env is available under the no_std corelib too.
    let materialize_mode = std::env::var("SOFAB_MATERIALIZE").as_deref() == Ok("1");

    let stdin = std::io::stdin();
    let mut r = stdin.lock();
    let stdout = std::io::stdout();
    let mut w = std::io::BufWriter::new(stdout.lock());

    let mut lenbuf = [0u8; 4];
    loop {
        match r.read_exact(&mut lenbuf) {
            Err(ref e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break, // clean EOF
            Err(e) => {
                eprintln!("crucible-rust: short length prefix: {e}");
                std::process::exit(1);
            }
            Ok(()) => {}
        }
        let n = u32::from_le_bytes(lenbuf) as usize;
        let mut data = vec![0u8; n];
        if n > 0 {
            if let Err(e) = r.read_exact(&mut data) {
                eprintln!("crucible-rust: short payload: {e}");
                std::process::exit(1);
            }
        }
        canonical(&mut w, &data, materialize_mode);
        w.flush().ok();
    }
}
