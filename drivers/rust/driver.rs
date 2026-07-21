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
// This is a MANUAL walker over the generated `Probe` struct (no serde/reflection),
// so it compiles for BOTH corelibs: the string/blob/wrapper fields are `String`/`Vec`
// under std and `heapless::String`/`heapless::Vec` under no_std, but both expose
// `.as_bytes()` (strings) and slice-deref `&x[..]` (blobs), and `.iter()` over the
// wrappers — the numeric/fp scalar and array fields are identical in both. The driver
// binary itself is always std (main.rs uses std::io), so we write straight to the
// std::io::Write sink exactly as the round-trip path does.
fn md_hex(out: &mut impl Write, b: &[u8]) {
    for x in b {
        let _ = write!(out, "{:02x}", x);
    }
}
fn md_text(out: &mut impl Write, b: &[u8]) {
    let _ = write!(out, "t{}:", b.len());
    md_hex(out, b);
}
fn md_blob(out: &mut impl Write, b: &[u8]) {
    let _ = write!(out, "b{}:", b.len());
    md_hex(out, b);
}
fn md_arr_u<T: core::fmt::Display>(out: &mut impl Write, a: &[T]) {
    let _ = write!(out, "[");
    for (i, v) in a.iter().enumerate() {
        let _ = write!(out, "{}u{}", if i > 0 { "," } else { "" }, v);
    }
    let _ = write!(out, "]");
}
fn md_arr_s<T: core::fmt::Display>(out: &mut impl Write, a: &[T]) {
    let _ = write!(out, "[");
    for (i, v) in a.iter().enumerate() {
        let _ = write!(out, "{}s{}", if i > 0 { "," } else { "" }, v);
    }
    let _ = write!(out, "]");
}
fn md_arr_f32(out: &mut impl Write, a: &[f32]) {
    let _ = write!(out, "[");
    for (i, v) in a.iter().enumerate() {
        let _ = write!(out, "{}f{:08x}", if i > 0 { "," } else { "" }, v.to_bits());
    }
    let _ = write!(out, "]");
}
fn md_arr_f64(out: &mut impl Write, a: &[f64]) {
    let _ = write!(out, "[");
    for (i, v) in a.iter().enumerate() {
        let _ = write!(out, "{}F{:016x}", if i > 0 { "," } else { "" }, v.to_bits());
    }
    let _ = write!(out, "]");
}

fn materialize(out: &mut impl Write, m: &Probe) {
    // top-level scalars (ids 0..7)
    let _ = write!(
        out,
        "{{0:u{};1:s{};2:u{};3:s{};4:u{};5:s{};6:u{};7:s{};",
        m.u8, m.i8, m.u16, m.i16, m.u32, m.i32, m.u64, m.i64
    );
    // nested struct (id 10): f32(0) f64(1) str(2) blob(3)
    let _ = write!(
        out,
        "10:{{0:f{:08x};1:F{:016x};2:",
        m.nested.f32.to_bits(),
        m.nested.f64.to_bits()
    );
    md_text(out, m.nested.str.as_bytes());
    let _ = write!(out, ";3:");
    md_blob(out, &m.nested.bytes_field[..]);
    let _ = write!(out, "}};");
    // arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10)
    let _ = write!(out, "100:{{0:");
    md_arr_u(out, &m.arrays.u8[..]);
    let _ = write!(out, ";1:");
    md_arr_s(out, &m.arrays.i8[..]);
    let _ = write!(out, ";2:");
    md_arr_u(out, &m.arrays.u16[..]);
    let _ = write!(out, ";3:");
    md_arr_s(out, &m.arrays.i16[..]);
    let _ = write!(out, ";4:");
    md_arr_u(out, &m.arrays.u32[..]);
    let _ = write!(out, ";5:");
    md_arr_s(out, &m.arrays.i32[..]);
    let _ = write!(out, ";6:");
    md_arr_u(out, &m.arrays.u64[..]);
    let _ = write!(out, ";7:");
    md_arr_s(out, &m.arrays.i64[..]);
    let _ = write!(out, ";10:{{0:");
    md_arr_f32(out, &m.arrays.nested.fp32[..]);
    let _ = write!(out, ";1:");
    md_arr_f64(out, &m.arrays.nested.fp64[..]);
    let _ = write!(out, "}}}};");
    // wrapper arrays: string_array (id 200), blob_array (id 201). The decoded Vec
    // length is already highest-populated-index + 1 (interior gaps as empty), so we
    // emit every element in index order.
    let _ = write!(out, "200:[");
    for (i, s) in m.string_array.iter().enumerate() {
        if i > 0 {
            let _ = write!(out, ",");
        }
        md_text(out, s.as_bytes());
    }
    let _ = write!(out, "];201:[");
    for (i, b) in m.blob_array.iter().enumerate() {
        if i > 0 {
            let _ = write!(out, ",");
        }
        md_blob(out, &b[..]);
    }
    let _ = write!(out, "]}}");
}

fn canonical(out: &mut impl Write, data: &[u8], materialize_mode: bool) {
    match Probe::try_decode(data) {
        Ok(m) => {
            if materialize_mode {
                // COMPLETE, materialize mode: dump the decoded value (materialized.md).
                let _ = write!(out, "A ");
                materialize(out, &m);
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
