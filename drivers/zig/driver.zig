// Crucible Zig driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-zig code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// The generated Zig decode is fallible: `Probe.decode` returns
// `DecodeError!Probe` (the corelib's error set plus IncompleteMessage), so the
// verdict is a `catch`. Zig 0.16 std.Io: main takes `std.process.Init` (for
// `io`/`gpa`), stdin/stdout go through `std.Io.File` reader/writer interfaces.
//
// A decoded message owns its bytes (generated message.zig header): strings, blobs
// and array storage are copied into the allocator passed to decode, on the one-shot
// path as on the streaming one. That allocator is the per-record arena, so the
// message lives until the next record resets it.
const std = @import("std");
const message = @import("message.zig");
const sofab = @import("sofab");

// --- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 ------
//
// The default accept path re-encodes the decoded value to wire (schema-agnostic,
// but blind to a decode that differs only where the sparse-canonical wire elides —
// see canonical.md §Tradeoff). This second path instead walks the decoded Probe
// value directly and dumps every field + every array element explicitly, matching
// engine/structured/materialize.py byte-for-byte.
//
// The walker is SCHEMA-AGNOSTIC: it is generated at build time from the descriptor
// oracle/materialized-schema.json by materialize_gen.py (run by build.sh), which
// unrolls the descriptor into straight-line field-access code. A schema change
// reshapes materialize_gen.zig with zero hand-editing here. (Zig 0.16 comptime
// field access needs field names at compile time, and string vs blob are both
// []const u8 — so the descriptor is unrolled to source rather than walked at
// runtime.) Strings/blobs live in the per-record arena, so the dump is written
// before the next record resets it.
const matgen = @import("materialize_gen.zig");

// ---- the streaming axes (drivers/common/CONTRACT.md) --------------------------
//
// The replay protocol hands each record over whole and re-encodes it with one call,
// so neither streaming surface of the generated API is reachable through it. Unset,
// every variable below is today's behaviour byte for byte.
//
// The verdict is the sofab.Status the last feed() returned: in this backend that
// return value IS the decoder's status, which CONTRACT.md streaming rule 3 says to
// read where a backend exposes one (CORELIB_PLAN §5.2.1 makes it the only place to
// ask -- there is no separate status() accessor). finish() is not used for the
// verdict: rule 3 routes it through finish() only for backends with no status.
//
// SOFAB_CHUNK_SCRUB applies here like everywhere else: the generated Decoder copies
// every string and blob out of the chunk (generator#295; message.zig: "a fed chunk
// does not have to outlive the message"), so a scrubbed chunk must not change the
// line. There is no exit-3 carve-out for it.
const StreamCfg = struct {
    split: usize = 0,
    chunk: usize = 0,
    scrub: bool = false,
    enc_stream: bool = false,
    flush: usize = 0,
    /// SOFAB_ENCODE_FAIL=n: the destination handed to the encoder takes n bytes.
    fail: usize = 0,
};

fn envUsize(init: std.process.Init, name: []const u8) usize {
    const v = init.environ_map.get(name) orelse return 0;
    return std.fmt.parseInt(usize, v, 10) catch 0;
}

fn readStreamCfg(init: std.process.Init) StreamCfg {
    var cfg = StreamCfg{};
    cfg.split = envUsize(init, "SOFAB_SPLIT");
    cfg.chunk = envUsize(init, "SOFAB_CHUNK");
    cfg.flush = envUsize(init, "SOFAB_FLUSH");
    cfg.fail = envUsize(init, "SOFAB_ENCODE_FAIL");
    if (init.environ_map.get("SOFAB_CHUNK_SCRUB")) |v| {
        cfg.scrub = v.len != 0 and !std.mem.eql(u8, v, "0");
    }
    if (init.environ_map.get("SOFAB_ENCODE")) |e| {
        if (std.mem.eql(u8, e, "stream")) {
            cfg.enc_stream = true;
        } else if (std.mem.eql(u8, e, "to")) {
            std.debug.print("crucible-zig: SOFAB_ENCODE=to — this backend has no " ++
                "encodeTo (it has new, stream)\n", .{});
            std.process.exit(2);
        } else if (e.len != 0 and !std.mem.eql(u8, e, "new")) {
            std.debug.print("crucible-zig: unknown SOFAB_ENCODE (this backend has " ++
                "new, stream)\n", .{});
            std.process.exit(2);
        }
    }
    // Announce on stderr (never parsed). A driver that silently ignored these would
    // be indistinguishable from one that honours them — stdout is identical either
    // way — so this makes "it really re-feeds" checkable rather than asserted.
    if (cfg.split != 0 or cfg.chunk != 0 or cfg.scrub or cfg.flush != 0 or
        cfg.enc_stream or cfg.fail != 0)
    {
        std.debug.print("crucible-zig: streaming cfg split={d} chunk={d} scrub={d} " ++
            "enc={s} flush={d} fail={d}\n", .{
            cfg.split, cfg.chunk, @intFromBool(cfg.scrub),
            if (cfg.enc_stream) @as([]const u8, "stream") else @as([]const u8, "new"),
            cfg.flush, cfg.fail,
        });
    }
    return cfg;
}

// A driver-side allocation failure is the driver's own problem, never a corelib
// verdict: it must not be dressed up as `R`/`E <class>`. Fail the run loudly instead.
fn driverOom() noreturn {
    std.debug.print("crucible-zig: driver allocation failed (out of memory)\n", .{});
    std.process.exit(1);
}

// The class a refused RE-ENCODE carries. `anyerror` rather than the corelib's error
// set, because the allocating encode() also carries std.mem.Allocator.Error; that
// one is handled (as driverOom) before this mapping is reached.
fn encode_class(e: anyerror) []const u8 {
    return switch (e) {
        error.InvalidArgument => "argument",
        error.BufferFull => "buffer_full",
        else => "other",
    };
}

// Sink for the streaming encode: collect what the OStream flushes. The sink cannot
// return an error, and silently dropping bytes would forge a short `A <hex>`, so an
// allocation failure here ends the run.
const EncAcc = struct {
    list: std.ArrayListUnmanaged(u8) = .empty,
    alloc: std.mem.Allocator,

    fn sink(ctx: ?*anyopaque, data: []const u8) void {
        const self: *EncAcc = @ptrCast(@alignCast(ctx.?));
        self.list.appendSlice(self.alloc, data) catch driverOom();
    }
};

pub fn main(init: std.process.Init) !void {
    const io = init.io;

    // SOFAB_MATERIALIZE=1 selects the materialized-value dump on accept
    // (oracle/materialized.md); unset keeps the default round-trip hex path.
    const materialize_mode = if (init.environ_map.get("SOFAB_MATERIALIZE")) |v|
        std.mem.eql(u8, v, "1")
    else
        false;

    const cfg = readStreamCfg(init);
    // SOFAB_CHUNK_SCRUB alone also takes the decoder path (one whole chunk, scrubbed
    // after feed), so the lifetime oracle runs even without a split.
    const chunking = cfg.split != 0 or cfg.chunk != 0 or cfg.scrub;

    var inbuf: [8192]u8 = undefined;
    var stdin_reader = std.Io.File.stdin().readerStreaming(io, &inbuf);
    const in = &stdin_reader.interface;

    var outbuf: [8192]u8 = undefined;
    var stdout_writer = std.Io.File.stdout().writer(io, &outbuf);
    const out = &stdout_writer.interface;

    // Per-record arena: the full message decodes array storage from it and
    // re-encode allocates from it; reset per record so nothing leaks across the
    // (potentially millions of) inputs.
    var arena = std.heap.ArenaAllocator.init(init.gpa);
    defer arena.deinit();

    while (true) {
        const lenb = in.takeArray(4) catch |e| switch (e) {
            error.EndOfStream => break, // clean EOF at record boundary
            else => return e,
        };
        const n: usize = @as(usize, lenb[0]) | (@as(usize, lenb[1]) << 8) |
            (@as(usize, lenb[2]) << 16) | (@as(usize, lenb[3]) << 24);

        _ = arena.reset(.retain_capacity);
        const a = arena.allocator();

        const data = try a.alloc(u8, n);
        if (n > 0) try in.readSliceAll(data);

        // decode -> re-encode -> hex (oracle/canonical.md). The decoded message owns
        // its bytes (copied into the arena), so `data` plays no part after decode.
        //
        // The chunked path is taken ONLY when a chunking variable is set, so the
        // default stays the one-shot Probe.decode byte for byte — which is what
        // makes the gate meaningful: it then compares two genuinely different code
        // paths.
        const m = (if (chunking) blk: {
            var acc: message.Probe = .{};
            var d = message.Probe.decoder(&acc, a);
            var off: usize = 0;
            var st: sofab.Status = undefined;
            // A zero-length record is ONE empty chunk, fed once (CONTRACT.md
            // streaming rule 4): the decoder answers the empty message, not the
            // driver. Otherwise no chunk is ever empty.
            while (true) {
                var step: usize = if (cfg.chunk > 0) cfg.chunk else n;
                if (cfg.chunk == 0 and cfg.split > 0 and cfg.split < n and off == 0)
                    step = cfg.split;
                if (off + step > n) step = n - off;
                // Scrub needs a buffer the driver owns: feed it, then overwrite. A
                // decoder that borrowed from the chunk instead of copying out of it
                // reads back 0xA5.
                const piece = if (cfg.scrub) blk2: {
                    const copy = a.alloc(u8, step) catch driverOom();
                    @memcpy(copy, data[off .. off + step]);
                    break :blk2 copy;
                } else data[off .. off + step];
                st = d.feed(piece) catch |e| break :blk @as(
                    message.DecodeError!message.Probe, e);
                if (cfg.scrub) @memset(@constCast(piece), 0xA5);
                off += step;
                if (off >= n) break;
            }
            // Verdict from the status the last feed returned (CONTRACT.md streaming
            // rule 3); `.complete` there means the record ended on a field boundary.
            if (st == .incomplete)
                break :blk @as(message.DecodeError!message.Probe, error.IncompleteMessage);
            break :blk @as(message.DecodeError!message.Probe, acc);
        } else message.Probe.decode(a, data)) catch |err| {
            // INCOMPLETE (§7) is a distinct verdict, not an error: the bytes end
            // inside a field/varint or an open sequence. Emit `I` — never collapse
            // it into A (accept-as-done) or R (reject-as-malformed).
            if (err == error.IncompleteMessage) {
                try out.writeAll("I\n");
                try out.flush();
                continue;
            }
            if (err == error.LimitExceeded) {
                // LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
                // cap on a schema-unbounded field. A policy rejection distinct from INVALID —
                // its own verdict `L`, not `R`.
                try out.writeAll("L\n");
                try out.flush();
                continue;
            }
            const cls = switch (err) {
                error.InvalidMessage => "invalid_msg",
                error.InvalidArgument => "argument",
                // error.UsageError was removed in corelib-zig#23; the canonical
                // "usage" class stays in oracle/canonical.md for the corelibs that
                // still have it. This switch is exhaustive over the error set, so
                // the arm has to go rather than fall through.
                error.BufferFull => "buffer_full",
                error.IncompleteMessage => unreachable, // handled above
                error.LimitExceeded => unreachable, // handled above
            };
            try out.print("R {s}\n", .{cls});
            try out.flush();
            continue;
        };
        // Accept. In materialize mode (oracle/materialized.md) dump the decoded
        // value's fields/elements explicitly instead of re-encoding to wire. m's
        // string/blob bytes live in the arena, so the whole dump is written now,
        // before the loop resets it.
        if (materialize_mode) {
            try out.writeAll("A ");
            try matgen.materialize(out, &m);
            try out.writeAll("\n");
            try out.flush();
            continue;
        }

        // Re-encode through the surface SOFAB_ENCODE selects. Both must emit
        // identical bytes, and SOFAB_FLUSH must not change them either: it gives the
        // OStream an n-byte buffer with a sink, so the encoder crosses a buffer
        // boundary at every offset — the encode-side mirror of SOFAB_CHUNK=1.
        // SOFAB_ENCODE_FAIL=n (CONTRACT.md): a destination of n bytes with NO sink, so
        // a message that does not fit is REFUSED (error.BufferFull) rather than
        // truncated, and the `E` mapping below runs for real — from the wire that
        // branch is unreachable, because every value re-encoded here came out of this
        // driver's own decoder and is in-bounds by construction.
        const enc = (if (cfg.fail > 0) blk: {
            const sbuf = a.alloc(u8, cfg.fail) catch driverOom();
            var os = sofab.OStream.init(sbuf);
            m.serialize(&os) catch |e| break :blk @as(anyerror![]u8, e);
            break :blk @as(anyerror![]u8, sbuf[0..os.bytesUsed()]);
        } else if (cfg.enc_stream) blk: {
            const cap = if (cfg.flush > 0) cfg.flush else message.Probe.MAX_SIZE;
            const sbuf = a.alloc(u8, cap) catch driverOom();
            var acc = EncAcc{ .alloc = a };
            var os = sofab.OStream.initFlush(sbuf, 0, &acc, EncAcc.sink);
            // Hand the encoder's OWN error up instead of relabelling it: this arm
            // read `catch break :blk error.BufferFull` and so reported a REFUSAL
            // (error.InvalidArgument, generator#656) as a full buffer, which then
            // became `R other`. Two facts lost in one line.
            m.serialize(&os) catch |e| break :blk @as(anyerror![]u8, e);
            _ = os.flush();
            break :blk @as(anyerror![]u8, acc.list.items);
        } else m.encode(a)) catch |e| {
            // The decode ACCEPTED and the re-encode of that value was REFUSED: its
            // own verdict, never a reject class — the bytes were not malformed
            // (oracle/canonical.md "The fifth verdict `E`"). An allocation failure
            // in encode() is the driver's arena failing, not a refusal.
            if (e == error.OutOfMemory) driverOom();
            try out.print("E {s}\n", .{encode_class(e)});
            try out.flush();
            continue;
        };
        try out.writeAll("A ");
        for (enc) |b| try out.print("{x:0>2}", .{b});
        try out.writeAll("\n");
        try out.flush();
    }
}
