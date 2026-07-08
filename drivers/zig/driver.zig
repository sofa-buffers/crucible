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

pub fn main(init: std.process.Init) !void {
    const io = init.io;

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
        const m = message.Probe.decode(a, data) catch |err| {
            const cls = switch (err) {
                error.InvalidMessage => "invalid_msg",
                error.InvalidArgument => "argument",
                error.UsageError => "usage",
                error.BufferFull => "buffer_full",
            };
            try out.print("R {s}\n", .{cls});
            try out.flush();
            continue;
        };
        const enc = m.encode(a) catch {
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
