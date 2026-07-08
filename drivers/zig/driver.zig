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
    const a = init.gpa;

    var inbuf: [8192]u8 = undefined;
    var stdin_reader = std.Io.File.stdin().readerStreaming(io, &inbuf);
    const in = &stdin_reader.interface;

    var outbuf: [8192]u8 = undefined;
    var stdout_writer = std.Io.File.stdout().writer(io, &outbuf);
    const out = &stdout_writer.interface;

    while (true) {
        const lenb = in.takeArray(4) catch |e| switch (e) {
            error.EndOfStream => break, // clean EOF at record boundary
            else => return e,
        };
        const n: usize = @as(usize, lenb[0]) | (@as(usize, lenb[1]) << 8) |
            (@as(usize, lenb[2]) << 16) | (@as(usize, lenb[3]) << 24);

        const data = try a.alloc(u8, n);
        defer a.free(data);
        if (n > 0) try in.readSliceAll(data);

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

        const fbits: u32 = @bitCast(m.f);
        try out.print("A u={d} i={d} f={x:0>8} s=", .{ m.u, m.i, fbits });
        for (m.s) |b| try out.print("{x:0>2}", .{b});
        try out.writeAll("\n");
        try out.flush();
    }
}
