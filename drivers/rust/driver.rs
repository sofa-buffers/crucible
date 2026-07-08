// Crucible Rust driver — shared body for BOTH corelibs (corelib-rs / corelib-rs-no-std).
//
// build.sh prepends a per-variant preamble that brings `Probe` into scope:
//   std     : `mod message; use message::Probe;`
//   no-std  : `use sofabuffers_generated::Probe;`
// The `sofab` crate (either corelib) is a dependency of both, so the imports
// below resolve unchanged.
//
// Two-pass decode (see docs/SOFABGEN.md G-0001): the generated `Probe::decode`
// is infallible — it discards feed's Result — so we get the VALUE from it and
// recover the faithful ACCEPT/REJECT VERDICT by re-running IStream::feed against
// a null visitor. Visitor callbacks cannot affect feed's Result (they return
// unit), so the null-pass verdict equals the one inside `decode`.
//
// Emits the canonical form (oracle/canonical.md) over the replay protocol
// (drivers/common/CONTRACT.md).
use sofab::{Error, IStream, Visitor};
use std::io::{Read, Write};

struct Null;
impl Visitor for Null {}

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
    // Verdict: the corelib's real accept/reject decision (visitor-independent).
    let mut is = IStream::new();
    let mut null = Null;
    match is.feed(data, &mut null) {
        Err(e) => {
            let _ = writeln!(out, "R {}", reject_class(e));
        }
        Ok(()) => {
            // Value: faithful decode via generated code; re-encode -> hex.
            let m = Probe::decode(data);
            let bytes = m.encode();
            let _ = write!(out, "A ");
            for b in bytes.iter() {
                let _ = write!(out, "{:02x}", b);
            }
            let _ = writeln!(out);
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
