// Crucible Dart driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records from stdin
// (a stream of <u32 little-endian len><N payload bytes>), decodes each into the
// probe message via the generated corelib-dart code, and writes one canonical
// line per record (oracle/canonical.md) to stdout, in input order.
//
// Decode is status-returning (MESSAGE_SPEC §7): Probe.tryDecode fills the message
// and returns the terminal DecodeStatus, with schema-bound violations (over-count,
// over-index, over-maxlen) folded into `invalid` via the generated sticky flag.
// The mapping to the canonical verdict is 1:1 — complete→A, incomplete→I,
// invalid→R, limitExceeded→L — the same shape as the Go driver.
//
// The Dart coverage engine (dart:ffi shared lib + a C libFuzzer harness, like
// Zig) is a separate front-end; this file is the replay path only.
import 'dart:io';
import 'dart:typed_data';

import 'package:sofabuffers/sofabuffers.dart' as sofab;
import 'message.dart';

const _hexDigits = '0123456789abcdef';

String _hex(Uint8List b) {
  final sb = StringBuffer();
  for (final x in b) {
    sb.write(_hexDigits[(x >> 4) & 0xf]);
    sb.write(_hexDigits[x & 0xf]);
  }
  return sb.toString();
}

// canonical produces the one canonical line for a single candidate input
// (oracle/canonical.md: decode -> re-encode -> hex on COMPLETE).
String canonical(Uint8List data) {
  final out = Probe();
  final sofab.DecodeStatus st;
  try {
    st = Probe.tryDecode(data, out);
  } catch (_) {
    // The generated tryDecode is not expected to throw on any input; if it does
    // that is itself worth surfacing, mapped to the coarse `other` reject class.
    return 'R other';
  }

  // INCOMPLETE (MESSAGE_SPEC §7): bytes end inside a field/varint or an open
  // sequence — the third verdict, neither accept nor reject. corelib-dart returns
  // no partial value here, so emit the bare `I`.
  if (st == sofab.DecodeStatus.incomplete) return 'I';
  // LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
  // cap on a schema-unbounded field. A policy rejection distinct from INVALID.
  if (st == sofab.DecodeStatus.limitExceeded) return 'L';
  // INVALID: malformed regardless of what follows. Reject class is coarse
  // (soft axis, see oracle/policy.yaml) — the status carries no finer code.
  if (st == sofab.DecodeStatus.invalid) return 'R invalid_msg';

  // COMPLETE: re-encode the decoded value with the corelib's own sparse-canonical
  // encoder and emit its lowercase hex (schema-agnostic; folds in the round-trip
  // oracle).
  try {
    return 'A ${_hex(out.encode())}';
  } catch (_) {
    return 'R other';
  }
}

Future<void> main() async {
  // Read the whole framed stream (the comparator writes it all, then reads our
  // stdout after we exit — see oracle/comparator.py run_driver). The corpus fits
  // in memory; this mirrors the TypeScript driver.
  final bb = BytesBuilder(copy: false);
  await for (final chunk in stdin) {
    bb.add(chunk);
  }
  final data = bb.toBytes();
  final bd = ByteData.sublistView(data);

  final sb = StringBuffer();
  var off = 0;
  while (off + 4 <= data.length) {
    final n = bd.getUint32(off, Endian.little);
    off += 4;
    if (off + n > data.length) break; // incomplete trailing frame — stop cleanly
    final rec = Uint8List.sublistView(data, off, off + n);
    off += n;
    sb.writeln(canonical(rec));
  }
  stdout.write(sb.toString());
  await stdout.flush();
}
