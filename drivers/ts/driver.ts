// Crucible TypeScript driver — persistent replay front-end for the differential loop.
//
// Speaks drivers/common/CONTRACT.md: reads length-prefixed records on stdin,
// decodes each into the probe message via the generated corelib-ts code, and
// writes one canonical line (oracle/canonical.md) per record to stdout.
//
// build.sh bundles this + the generated message.ts + corelib-ts SOURCE into one
// CJS file via esbuild (aliasing @sofa-buffers/corelib to the corelib's
// src/index.ts), so the run needs no separate corelib build and does not depend
// on the corelib's committed dist.
//
// Like Python/Java (and unlike Rust/C++), the generated TS decode throws on
// non-COMPLETE input (SofabError), so the verdict is a plain try/catch. The
// one-shot Probe.decode path (MESSAGE_SPEC §7) throws a SofabError whose .code
// distinguishes the two non-COMPLETE outcomes: Incomplete (truncation — decode
// ended mid-field, not an error → canonical "I") vs InvalidMsg (malformed →
// "R invalid_msg"). COMPLETE returns normally (→ "A <hex>").
import { readFileSync } from "node:fs";

import { Probe } from "./message";
import { OStream, SofabError, SofabErrorCode } from "@sofa-buffers/corelib";

function rejectClass(e: unknown): string {
  // Coarse in Phase 2 (reject-class comparison is soft per policy). A SofabError
  // is a decode-level failure; anything else is surfaced as "other" rather than
  // hidden.
  return e instanceof SofabError ? "invalid_msg" : "other";
}

function canonical(data: Uint8Array): string {
  // decode -> re-encode -> hex (oracle/canonical.md). The generated TS message
  // has no encode(), so marshal into an in-memory OStream and read its bytes.
  let bytes: Uint8Array;
  try {
    const m = Probe.decode(data);
    const os = new OStream();
    m.marshal(os);
    bytes = os.bytes();
  } catch (e) {
    // INCOMPLETE (truncation) is a distinct hard verdict, not a reject: the
    // stream ended inside a field. Detect it first (canonical.md: never collapse
    // it into A or R). The optional partial-value hex payload is not emitted —
    // the throwing one-shot path yields no partial value, and the payload axis is
    // soft in Phase 2.
    if (e instanceof SofabError && e.code === SofabErrorCode.Incomplete) {
      return "I";
    }
    if (e instanceof SofabError && e.code === SofabErrorCode.LimitExceeded) {
      // LIMIT_EXCEEDED (generator#102, limit mode only): a configured receiver-side
      // cap on a schema-unbounded field. A policy rejection distinct from INVALID —
      // its own verdict `L`, not `R`.
      return "L";
    }
    return "R " + rejectClass(e);
  }
  const hex = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return "A " + hex;
}

function main(): void {
  const input = readFileSync(0); // whole stdin (comparator writes all frames, then EOF)
  const lines: string[] = [];
  let off = 0;
  while (off + 4 <= input.length) {
    const n = input.readUInt32LE(off);
    off += 4;
    if (off + n > input.length) {
      process.stderr.write("crucible-ts: short payload\n");
      process.exit(1);
    }
    lines.push(canonical(input.subarray(off, off + n)));
    off += n;
  }
  process.stdout.write(lines.length ? lines.join("\n") + "\n" : "");
}

main();
