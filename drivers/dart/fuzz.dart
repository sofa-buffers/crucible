// Dart coverage target for the probe decoder — PLACEHOLDER.
//
// Dart has no first-party coverage-guided fuzzer (libFuzzer/AFL). The intended
// path (see .devcontainer/Dockerfile) mirrors Zig's C-interop plan: expose the
// decode core from an AOT-compiled Dart shared library via dart:ffi
// (@Native / native-assets) and drive it from a C libFuzzer harness
// (LLVMFuzzerTestOneInput -> the FFI decode entrypoint), resolved in the
// devcontainer where clang + libFuzzer are present. This stays AOT/native
// end-to-end — never the Dart VM/JIT. `build.sh` does NOT build this file; it
// builds only the replay driver (the differential path). The C corelib remains
// the coverage pacemaker (PLAN §3); a Dart coverage engine is a stretch goal, and
// like Zig's it is unresolved (PLAN §14).
//
// Until then, this smoke check exercises the decode core so the skeleton stays
// valid: it must not crash on arbitrary bytes and must map the three verdicts
// correctly. Run it AOT: `dart compile exe fuzz.dart -o fuzz && ./fuzz` from the
// built package dir (beside the generated message.dart).
import 'dart:typed_data';

import 'package:sofabuffers/sofabuffers.dart' as sofab;
import 'message.dart';

void _expect(bool cond, String msg) {
  if (!cond) throw StateError('dart fuzz smoke check failed: $msg');
}

void main() {
  // COMPLETE: the empty input is the valid all-defaults message.
  _expect(Probe.tryDecode(Uint8List(0), Probe()) == sofab.DecodeStatus.complete,
      'empty -> complete');

  // INCOMPLETE (F-0001): a lone 0x80 is a truncated trailing varint — the third
  // verdict, neither accept nor reject.
  _expect(
      Probe.tryDecode(Uint8List.fromList([0x80]), Probe()) ==
          sofab.DecodeStatus.incomplete,
      '0x80 -> incomplete');

  // The decode core must never throw/crash on arbitrary bytes — the property the
  // real coverage engine + sanitizers exist to stress. Sweep every 1- and 4-byte
  // prefix as a minimal crash-freedom smoke.
  for (var b = 0; b < 256; b++) {
    Probe.tryDecode(Uint8List.fromList([b]), Probe());
    Probe.tryDecode(Uint8List.fromList([b, b, b, b]), Probe());
  }

  // ignore: avoid_print
  print('dart fuzz smoke: OK');
}
