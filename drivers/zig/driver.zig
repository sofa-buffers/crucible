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

// --- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 ------
//
// The default accept path re-encodes the decoded value to wire (schema-agnostic,
// but blind to a decode that differs only where the sparse-canonical wire elides —
// see canonical.md §Tradeoff). This second path instead walks the decoded Probe
// value directly and dumps every field + every array element explicitly, matching
// engine/structured/materialize.py byte-for-byte. Zig knows each field's schema
// type statically, so no descriptor/table is needed. Strings/blobs borrow `data`
// (zero-copy), so the dump is written while `data` is still alive (before reset).
fn matFp32(out: anytype, v: f32) !void {
    const bits: u32 = @bitCast(v);
    try out.print("f{x:0>8}", .{bits});
}
fn matFp64(out: anytype, v: f64) !void {
    const bits: u64 = @bitCast(v);
    try out.print("F{x:0>16}", .{bits});
}
fn matBytes(out: anytype, tag: u8, s: []const u8) !void {
    try out.print("{c}{d}:", .{ tag, s.len });
    for (s) |b| try out.print("{x:0>2}", .{b});
}
fn matArrUnsigned(out: anytype, arr: anytype) !void {
    try out.writeAll("[");
    for (arr, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try out.print("u{d}", .{e});
    }
    try out.writeAll("]");
}
fn matArrSigned(out: anytype, arr: anytype) !void {
    try out.writeAll("[");
    for (arr, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try out.print("s{d}", .{e});
    }
    try out.writeAll("]");
}
fn matArrFp32(out: anytype, arr: anytype) !void {
    try out.writeAll("[");
    for (arr, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try matFp32(out, e);
    }
    try out.writeAll("]");
}
fn matArrFp64(out: anytype, arr: anytype) !void {
    try out.writeAll("[");
    for (arr, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try matFp64(out, e);
    }
    try out.writeAll("]");
}
fn matMessage(out: anytype, m: *const message.Probe) !void {
    try out.writeAll("{");
    // top-level scalars (ids 0..7)
    try out.print("0:u{d};", .{m.u8});
    try out.print("1:s{d};", .{m.i8});
    try out.print("2:u{d};", .{m.u16});
    try out.print("3:s{d};", .{m.i16});
    try out.print("4:u{d};", .{m.u32});
    try out.print("5:s{d};", .{m.i32});
    try out.print("6:u{d};", .{m.u64});
    try out.print("7:s{d};", .{m.i64});
    // nested struct (id 10): f32(0) f64(1) str(2) blob(3)
    try out.writeAll("10:{0:");
    try matFp32(out, m.nested.f32);
    try out.writeAll(";1:");
    try matFp64(out, m.nested.f64);
    try out.writeAll(";2:");
    try matBytes(out, 't', m.nested.str);
    try out.writeAll(";3:");
    try matBytes(out, 'b', m.nested.bytes_field);
    try out.writeAll("};");
    // arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10)
    try out.writeAll("100:{0:");
    try matArrUnsigned(out, m.arrays.u8[0..]);
    try out.writeAll(";1:");
    try matArrSigned(out, m.arrays.i8[0..]);
    try out.writeAll(";2:");
    try matArrUnsigned(out, m.arrays.u16[0..]);
    try out.writeAll(";3:");
    try matArrSigned(out, m.arrays.i16[0..]);
    try out.writeAll(";4:");
    try matArrUnsigned(out, m.arrays.u32[0..]);
    try out.writeAll(";5:");
    try matArrSigned(out, m.arrays.i32[0..]);
    try out.writeAll(";6:");
    try matArrUnsigned(out, m.arrays.u64[0..]);
    try out.writeAll(";7:");
    try matArrSigned(out, m.arrays.i64[0..]);
    try out.writeAll(";10:{0:");
    try matArrFp32(out, m.arrays.nested.fp32[0..]);
    try out.writeAll(";1:");
    try matArrFp64(out, m.arrays.nested.fp64[0..]);
    try out.writeAll("}};");
    // wrapper arrays: string_array (id 200), blob_array (id 201)
    try out.writeAll("200:[");
    for (m.string_array, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try matBytes(out, 't', e);
    }
    try out.writeAll("];201:[");
    for (m.blob_array, 0..) |e, i| {
        if (i != 0) try out.writeAll(",");
        try matBytes(out, 'b', e);
    }
    try out.writeAll("]}");
}

pub fn main(init: std.process.Init) !void {
    const io = init.io;

    // SOFAB_MATERIALIZE=1 selects the materialized-value dump on accept
    // (oracle/materialized.md); unset keeps the default round-trip hex path.
    const materialize_mode = if (init.environ_map.get("SOFAB_MATERIALIZE")) |v|
        std.mem.eql(u8, v, "1")
    else
        false;

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
                error.UsageError => "usage",
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
            try matMessage(out, &m);
            try out.writeAll("\n");
            try out.flush();
            continue;
        }

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
