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

fn canonical(out: &mut impl Write, data: &[u8]) {
    match Probe::try_decode(data) {
        Ok(m) => {
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
        canonical(&mut w, &data);
        w.flush().ok();
    }
}
