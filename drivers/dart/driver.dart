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
import 'materialize_gen.dart';

// SOFAB_MATERIALIZE=1 selects the materialized-value dump (oracle/materialized.md)
// on a COMPLETE decode instead of the round-trip hex; unset keeps the default
// round-trip path. Only the `A` payload changes.
final bool _materialize = Platform.environment['SOFAB_MATERIALIZE'] == '1';

const _hexDigits = '0123456789abcdef';

String _hex(Uint8List b) {
  final sb = StringBuffer();
  for (final x in b) {
    sb.write(_hexDigits[(x >> 4) & 0xf]);
    sb.write(_hexDigits[x & 0xf]);
  }
  return sb.toString();
}

// ---- the streaming axes (drivers/common/CONTRACT.md) -------------------------
//
// The replay protocol hands each record over whole and re-encodes it with one call,
// so neither streaming surface of the generated API is reachable through it. Unset,
// every variable below is today's behaviour byte for byte.
//
// Dart is the backend the contract's finish() rule was written for: ProbeDecoder's
// finish() returns NULL where the others throw, so routing the verdict through it
// would put a backend difference into the canonical line. It exposes `status`, so
// the verdict comes from there.
int _envInt(String name) => int.tryParse(Platform.environment[name] ?? '') ?? 0;

final int _split = _envInt('SOFAB_SPLIT');
final int _chunk = _envInt('SOFAB_CHUNK');
final int _flush = _envInt('SOFAB_FLUSH');
final bool _scrub = (Platform.environment['SOFAB_CHUNK_SCRUB'] ?? '').isNotEmpty &&
    Platform.environment['SOFAB_CHUNK_SCRUB'] != '0';
final String _encode = (Platform.environment['SOFAB_ENCODE'] ?? '').isEmpty
    ? 'new'
    : Platform.environment['SOFAB_ENCODE']!;
final bool _chunking = _split != 0 || _chunk != 0 || _scrub;

void _checkCfg() {
  if (_encode != 'new' && _encode != 'to' && _encode != 'stream') {
    stderr.writeln('crucible-dart: unknown SOFAB_ENCODE=$_encode '
        '(this backend has new, to, stream)');
    exit(2);
  }
  // Announce on stderr (never parsed). A driver that silently ignored these would
  // be indistinguishable from one that honours them — stdout is identical either
  // way — so this makes "it really re-feeds" checkable rather than asserted.
  if (_split != 0 || _chunk != 0 || _scrub || _flush != 0 || _encode != 'new') {
    stderr.writeln('crucible-dart: streaming cfg split=$_split chunk=$_chunk '
        'scrub=${_scrub ? 1 : 0} enc=$_encode flush=$_flush');
  }
}

// How the record is cut on its way in. Never an empty chunk; a 0-byte record
// yields none at all.
List<Uint8List> _chunksOf(Uint8List data) {
  final len = data.length;
  if (len == 0) return const [];
  if (_chunk > 0) {
    final out = <Uint8List>[];
    for (var o = 0; o < len; o += _chunk) {
      out.add(Uint8List.fromList(data.sublist(o, o + _chunk > len ? len : o + _chunk)));
    }
    return out;
  }
  if (_split > 0 && _split < len) {
    return [
      Uint8List.fromList(data.sublist(0, _split)),
      Uint8List.fromList(data.sublist(_split)),
    ];
  }
  return [Uint8List.fromList(data)];
}

// Re-encode through the surface SOFAB_ENCODE selects. All three must emit identical
// bytes, and SOFAB_FLUSH must not change them either: it gives the Encoder an
// n-byte buffer draining to a sink, so the encoder crosses a buffer boundary at
// every offset.
Uint8List _encodeVia(Probe m) {
  if (_encode == 'new') return m.encode();
  final builder = BytesBuilder(copy: true);
  // corelib-dart#62 dropped `bufferSize:`: per CORELIB_PLAN §5.1 the corelib
  // allocates no output buffer, so the caller supplies one. A buffer below
  // `minOutputBuffer` is refused at the handover with `invalidArgument` — report
  // that as exit 3 ("cannot operate at this configuration") rather than letting
  // the exception escape, so the oracle sees the size the port declined.
  final cap = _flush > 0 ? _flush : 4096;
  final sofab.Encoder enc;
  try {
    enc = sofab.Encoder(builder.add, buffer: Uint8List(cap));
  } on sofab.SofabException catch (e) {
    stderr.writeln('crucible-dart: Encoder refused a $cap-byte buffer '
        '(MIN_OUTPUT_BUFFER=${sofab.minOutputBuffer}): $e');
    exit(3);
  }
  if (_encode == 'to') {
    m.encodeTo(enc);
  } else {
    m.serialize(enc);
  }
  enc.flush();
  return builder.toBytes();
}

// canonical produces the one canonical line for a single candidate input
// (oracle/canonical.md: decode -> re-encode -> hex on COMPLETE).
String canonical(Uint8List data) {
  final out = Probe();
  final sofab.DecodeStatus st;
  try {
    if (_chunking) {
      // Chunked decode via the generated ProbeDecoder, taken ONLY when a chunking
      // variable is set — the default stays the one-shot tryDecode byte for byte,
      // which is what makes the gate meaningful: it then compares two genuinely
      // different code paths. Verdict from `status`, never from finish().
      final d = Probe.decoder(out);
      for (final c in _chunksOf(data)) {
        d.feed(c);
        // Scrub: the chunk is a copy the driver owns, so overwriting it after feed
        // exposes a decoder that borrowed instead of copying.
        if (_scrub) c.fillRange(0, c.length, 0xA5);
      }
      st = d.status;
    } else {
      st = Probe.tryDecode(data, out);
    }
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

  // COMPLETE. In materialize mode, dump the decoded value (oracle/materialized.md);
  // otherwise re-encode with the corelib's own sparse-canonical encoder and emit the
  // lowercase hex (schema-agnostic; folds in the round-trip oracle).
  if (_materialize) return 'A ${materialize(out)}';
  try {
    return 'A ${_hex(_encodeVia(out))}';
  } catch (_) {
    return 'R other';
  }
}

Future<void> main() async {
  _checkCfg();
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
