// Zig coverage target for the probe decoder — PLACEHOLDER.
//
// Zig 0.16's built-in fuzzer is not yet exposed via a stable std API (no
// std.testing.fuzz here), so coverage-guided fuzzing of the Zig corelib is still
// open (PLAN §14): the likely path is libFuzzer via C interop (compile the
// decode core as a staticlib exposing LLVMFuzzerTestOneInput, link libFuzzer),
// resolved in the devcontainer where clang is present. build.sh does NOT build
// this file.
//
// Until then, this smoke test at least exercises the decode core under `zig test`
// so it must not crash on the seed inputs.
const std = @import("std");
const message = @import("message.zig");

test "probe decode accepts the empty (all-defaults) message" {
    const a = std.testing.allocator;
    const m = try message.Probe.decode(a, &.{});
    try std.testing.expectEqual(@as(u32, 0), m.u);
}

test "probe decode rejects a truncated trailing varint (F-0001)" {
    const a = std.testing.allocator;
    const bad = [_]u8{0x80};
    try std.testing.expectError(error.InvalidMessage, message.Probe.decode(a, &bad));
}
