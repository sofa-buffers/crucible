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
// malformed input (SofabError), so the verdict is a plain try/catch.
import { readFileSync } from "node:fs";

import { Probe } from "./message";
import { SofabError } from "@sofa-buffers/corelib";

function rejectClass(e: unknown): string {
  // Coarse in Phase 2 (reject-class comparison is soft per policy). A SofabError
  // is a decode-level failure; anything else is surfaced as "other" rather than
  // hidden.
  return e instanceof SofabError ? "invalid_msg" : "other";
}

function canonical(data: Uint8Array): string {
  let m: Probe;
  try {
    m = Probe.decode(data);
  } catch (e) {
    return "R " + rejectClass(e);
  }
  // fp32 bits (matches the other drivers' raw IEEE-754 encoding).
  const fbits = new DataView(new Float32Array([m.f]).buffer).getUint32(0, true);
  const fhex = fbits.toString(16).padStart(8, "0");
  const shex = Array.from(Buffer.from(m.s, "utf8"))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `A u=${m.u} i=${m.i} f=${fhex} s=${shex}`;
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
