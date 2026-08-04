// Crucible Zig driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-zig code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// Like Go/Python/Java/TS/C# (and unlike Rust/C++), the generated Zig decode is
// fallible: `Probe.decode` returns `sofab.Error!Probe`, so the verdict is a
// `catch`. Zig 0.16 std.Io: main takes `std.process.Init` (for `io`/`gpa`),
// stdin/stdout go through `std.Io.File` reader/writer interfaces.
//
// The generated decode is zero-copy: `m.s` borrows from `data`, so the canonical
// line is emitted while `data` is still alive (before it is freed).
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
// runtime.) Strings/blobs borrow `data` (zero-copy), so the dump is written while
// `data` is still alive (before reset).
const matgen = @import("materialize_gen.zig");

// ---- the streaming axes (drivers/common/CONTRACT.md) --------------------------
//
// The replay protocol hands each record over whole and re-encodes it with one call,
// so neither streaming surface of the generated API is reachable through it. Unset,
// every variable below is today's behaviour byte for byte.
//
// Zig's generated Decoder exposes status(), so the verdict comes from there rather
// than from finish() (which returns an error mid-field).
//
// SOFAB_CHUNK_SCRUB is NOT APPLICABLE here, and that is documented backend
// behaviour rather than a defect. The generated Decoder states it outright: "a
// string or blob that arrives whole inside one chunk is borrowed from that chunk
// ... so a fed chunk must outlive the message." Scrubbing a chunk after feed
// therefore violates this backend's contract instead of testing it, and the driver
// exits 3 (the same "not applicable at this setting" code the encode axis uses for
// an unusable SOFAB_FLUSH) rather than manufacturing a mismatch. That the
// chunk-lifetime contract differs across backends at all — corelib-cpp, -rs, -c-cpp
// and the managed runtimes all copy — is worth a family-level answer; recorded in
// docs/TODO.md.
const StreamCfg = struct {
    split: usize = 0,
    chunk: usize = 0,
    enc_stream: bool = false,
    flush: usize = 0,
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
    if (init.environ_map.get("SOFAB_CHUNK_SCRUB")) |v| {
        if (v.len != 0 and !std.mem.eql(u8, v, "0")) {
            std.debug.print("crucible-zig: SOFAB_CHUNK_SCRUB is not applicable — this " ++
                "backend borrows string/blob payloads that arrive whole in one chunk, " ++
                "and documents that a fed chunk must outlive the message\n", .{});
            std.process.exit(3);
        }
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
    if (cfg.split != 0 or cfg.chunk != 0 or cfg.flush != 0 or cfg.enc_stream) {
        std.debug.print("crucible-zig: streaming cfg split={d} chunk={d} enc={s} " ++
            "flush={d}\n", .{
            cfg.split, cfg.chunk,
            if (cfg.enc_stream) @as([]const u8, "stream") else @as([]const u8, "new"),
            cfg.flush,
        });
    }
    return cfg;
}

// Sink for the streaming encode: collect what the OStream flushes.
const EncAcc = struct {
    list: std.ArrayListUnmanaged(u8) = .empty,
    alloc: std.mem.Allocator,

    fn sink(ctx: ?*anyopaque, data: []const u8) void {
        const self: *EncAcc = @ptrCast(@alignCast(ctx.?));
        self.list.appendSlice(self.alloc, data) catch {};
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
    const chunking = cfg.split != 0 or cfg.chunk != 0;

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

        // decode -> re-encode -> hex (oracle/canonical.md). m borrows string bytes
        // from `data` (kept alive until the next reset), so encode can read them.
        //
        // The chunked path is taken ONLY when a chunking variable is set, so the
        // default stays the one-shot Probe.decode byte for byte — which is what
        // makes the gate meaningful: it then compares two genuinely different code
        // paths. `data` outlives the message either way (arena reset per record),
        // which is exactly the lifetime this backend documents as required.
        const m = (if (chunking) blk: {
            var acc: message.Probe = .{};
            var d = message.Probe.decoder(&acc, a);
            var off: usize = 0;
            while (off < n) {
                var step: usize = if (cfg.chunk > 0) cfg.chunk else n;
                if (cfg.chunk == 0 and cfg.split > 0 and cfg.split < n and off == 0)
                    step = cfg.split;
                if (off + step > n) step = n - off;
                _ = d.feed(data[off .. off + step]) catch |e| break :blk @as(
                    message.DecodeError!message.Probe, e);
                off += step;
            }
            // Verdict from status(), never from finish() (CONTRACT.md).
            if (d.status() == .incomplete)
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
        // value's fields/elements explicitly instead of re-encoding to wire. m
        // borrows string/blob bytes from `data` (alive until the next reset), so
        // the whole dump is written now, before the loop resets the arena.
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
        const enc = (if (cfg.enc_stream) blk: {
            const cap = if (cfg.flush > 0) cfg.flush else message.Probe.MAX_SIZE;
            const sbuf = a.alloc(u8, cap) catch break :blk error.BufferFull;
            var acc = EncAcc{ .alloc = a };
            var os = sofab.OStream.initFlush(sbuf, 0, &acc, EncAcc.sink);
            m.serialize(&os) catch break :blk error.BufferFull;
            _ = os.flush();
            break :blk @as(anyerror![]u8, acc.list.items);
        } else m.encode(a)) catch {
            try out.writeAll("R other\n");
            try out.flush();
            continue;
        };
        try out.writeAll("A ");
        for (enc) |b| try out.print("{x:0>2}", .{b});
        try out.writeAll("\n");
        try out.flush();
    }
}
