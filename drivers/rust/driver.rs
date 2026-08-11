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

// ---- the streaming axes (drivers/common/CONTRACT.md, "The streaming axes") -------
//
// The replay protocol hands each record over whole and re-encodes it with one call, so
// neither streaming surface of the generated API is reachable through it. Unset, every
// variable below is today's behaviour byte for byte.
//
// Rust's generated `Decoder` has **no `status`** — crucible#132's API table says every
// chunked decoder exposes one, and at sofabgen cfe5250b this backend does not. So the
// verdict comes from `finish()`, which is sound here for the reason the contract gives:
// `finish()` returns `Result<Probe, sofab::Error>`, the *same* three-valued outcome
// `try_decode` returns, so routing through it introduces no API-shape difference. It is
// also more than a formality — `finish()` feeds an empty chunk to probe end-of-input,
// which is exactly what makes a truncated stream an error rather than a half-filled
// value.
//
// This backend has no `encodeTo`, so `SOFAB_ENCODE=to` is a hard error rather than a
// fallback (meta: encode_surfaces=new,stream).
#[derive(Clone, Copy, PartialEq)]
enum EncSurface {
    New,
    Stream,
}

struct StreamCfg {
    split: usize,
    chunk: usize,
    scrub: bool,
    enc: EncSurface,
    flush: usize,
}

fn env_usize(name: &str) -> usize {
    std::env::var(name).ok().and_then(|v| v.parse().ok()).unwrap_or(0)
}

fn read_stream_cfg() -> StreamCfg {
    let enc = match std::env::var("SOFAB_ENCODE").as_deref() {
        Ok("to") => {
            eprintln!(
                "crucible-rust: SOFAB_ENCODE=to — this backend has no encodeTo \
                 (it has new, stream)"
            );
            std::process::exit(2);
        }
        Ok("stream") => EncSurface::Stream,
        Ok("new") | Err(_) => EncSurface::New,
        Ok("") => EncSurface::New,
        Ok(other) => {
            eprintln!(
                "crucible-rust: unknown SOFAB_ENCODE={other} (this backend has new, stream)"
            );
            std::process::exit(2);
        }
    };
    let cfg = StreamCfg {
        split: env_usize("SOFAB_SPLIT"),
        chunk: env_usize("SOFAB_CHUNK"),
        scrub: matches!(std::env::var("SOFAB_CHUNK_SCRUB").as_deref(), Ok(v) if !v.is_empty() && v != "0"),
        enc,
        flush: env_usize("SOFAB_FLUSH"),
    };
    // Announce on stderr (never parsed). A driver that silently ignored these would be
    // indistinguishable from one that honours them — identical stdout either way — so
    // this is what makes "it really re-feeds" checkable rather than asserted.
    if cfg.split != 0 || cfg.chunk != 0 || cfg.scrub || cfg.flush != 0
        || cfg.enc != EncSurface::New
    {
        eprintln!(
            "crucible-rust: streaming cfg split={} chunk={} scrub={} enc={} flush={}",
            cfg.split,
            cfg.chunk,
            cfg.scrub as u8,
            if cfg.enc == EncSurface::New { "new" } else { "stream" },
            cfg.flush
        );
    }
    cfg
}

// How the record is cut on its way into the decoder. Never an empty chunk: k<=0,
// k>=len and n>=len all mean one chunk holding the whole record. A zero-length record
// yields no chunks at all.
fn slices(cfg: &StreamCfg, len: usize) -> Vec<(usize, usize)> {
    if len == 0 {
        return Vec::new();
    }
    if cfg.chunk > 0 {
        return (0..len)
            .step_by(cfg.chunk)
            .map(|o| (o, std::cmp::min(cfg.chunk, len - o)))
            .collect();
    }
    if cfg.split > 0 && cfg.split < len {
        return vec![(0, cfg.split), (cfg.split, len - cfg.split)];
    }
    vec![(0, len)]
}

// Feed the record in the configured pieces through ONE decoder, then take the verdict
// from `finish()`. An `Incomplete` from a mid-stream `feed` is not terminal — it says
// only that *those bytes* ended mid-field; any other error is.
fn decode_streamed(cfg: &StreamCfg, data: &[u8]) -> Result<Probe, Error> {
    let mut d = Probe::decoder();
    let mut scratch: Vec<u8> = Vec::new();
    for (off, n) in slices(cfg, data.len()) {
        let r = if cfg.scrub {
            // Scrub needs a buffer the driver owns: feed it, then overwrite. A decoder
            // that borrowed from the chunk rather than copying out of it reads 0xA5.
            scratch.clear();
            scratch.extend_from_slice(&data[off..off + n]);
            let r = d.feed(&scratch);
            scratch.fill(0xA5);
            r
        } else {
            d.feed(&data[off..off + n])
        };
        match r {
            Ok(()) => {}
            Err(Error::Incomplete) => {}      // mid-field between chunks: expected
            Err(e) => return Err(e),          // terminal
        }
    }
    d.finish()
}

// Which generated call produces the `A <hex>` payload. Both surfaces must emit
// identical bytes for one decoded value, and SOFAB_FLUSH must not change that: it hands
// the OStream an n-byte buffer with a sink, so the encoder crosses a buffer boundary at
// every offset — the encode-side mirror of SOFAB_CHUNK=1.
fn encode_via(cfg: &StreamCfg, m: &Probe) -> Vec<u8> {
    if cfg.enc == EncSurface::New {
        // `encode()` is Vec<u8> on std and heapless::Vec<u8, MAX_SIZE> on no-std;
        // iterate rather than convert, so this one line compiles for both.
        return m.encode().iter().copied().collect();
    }
    let cap = if cfg.flush > 0 { cfg.flush } else { Probe::MAX_SIZE };
    let mut buf = vec![0u8; std::cmp::max(cap, 1)];
    let mut out: Vec<u8> = Vec::new();
    {
        let sink = |data: &[u8]| out.extend_from_slice(data);
        // `with_flush` is fallible since corelib-rs#86 (it always was on
        // corelib-rs-no-std): it enforces the CORELIB_PLAN §5.1 streaming minimum,
        // `buflen - offset >= MIN_OUTPUT_BUFFER`, and refuses a smaller buffer at the
        // installation. Report that refusal as exit 3 — "this backend cannot operate at
        // this configuration" — rather than unwrapping, so the oracle sees the buffer
        // size the port declined instead of a panic.
        let mut os = match sofab::OStream::with_flush(&mut buf, 0, sink) {
            Ok(os) => os,
            Err(e) => {
                eprintln!(
                    "crucible-rust: OStream::with_flush refused a {}-byte buffer \
                     (MIN_OUTPUT_BUFFER={}): {:?}",
                    buf.len(),
                    sofab::MIN_OUTPUT_BUFFER,
                    e
                );
                std::process::exit(3);
            }
        };
        m.serialize(&mut os);
        os.flush();
    }
    out
}

fn reject_class(e: Error) -> &'static str {
    match e {
        Error::InvalidMsg => "invalid_msg",
        Error::Argument => "argument",
        // Error::Usage was removed in corelib-rs#35 / corelib-rs-no-std#55; the
        // canonical "usage" class stays in oracle/canonical.md for the corelibs
        // that still have it. Anything unmapped falls through to "other".
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

fn canonical(out: &mut impl Write, data: &[u8], materialize_mode: bool, cfg: &StreamCfg) {
    // The chunked path is taken ONLY when a chunking variable is set, so the default
    // stays the one-shot try_decode byte for byte — which is also what makes the gate
    // meaningful: it then compares two genuinely different code paths.
    let decoded = if cfg.split != 0 || cfg.chunk != 0 || cfg.scrub {
        decode_streamed(cfg, data)
    } else {
        Probe::try_decode(data)
    };
    match decoded {
        Ok(m) => {
            if materialize_mode {
                // COMPLETE, materialize mode: dump the decoded value (materialized.md).
                let _ = write!(out, "A ");
                let _ = out.write_all(materialize(&m).as_bytes());
                let _ = writeln!(out);
                return;
            }
            // COMPLETE: re-encode the decoded value -> hex, through whichever encode
            // surface SOFAB_ENCODE selects (default: the allocating encode()).
            let bytes = encode_via(cfg, &m);
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
    let cfg = read_stream_cfg();

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
        canonical(&mut w, &data, materialize_mode, &cfg);
        w.flush().ok();
    }
}
