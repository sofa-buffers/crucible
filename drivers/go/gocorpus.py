#!/usr/bin/env python3
"""Convert between raw wire bytes and Go's fuzz-corpus text format.

Go's native fuzzer (`go test -fuzz`) does not store corpus entries as raw files —
both the seed corpus (`testdata/fuzz/<Target>/`) and the coverage corpus it grows
(`$GOCACHE/fuzz/<pkg>/<Target>/`) use a small text format:

    go test fuzz v1
    []byte("\\x56\\x02\\x20...")

Crucible's corpus is raw bytes, so wiring the Go engine in as a second steering
engine (docs/TODO.md, "Multi-impl coverage") needs a converter in both directions:
seeds in, coverage discoveries out.

Writing escapes **every** byte as `\\xNN`. That is always a valid Go string literal,
so no byte needs special-casing and no escaping bug can silently corrupt a vector.
Reading has to accept what *Go* emits, which is richer: it writes printable ASCII
literally and uses `\\x`, `\\u`, `\\U`, octal and the usual C escapes. `\\u`/`\\U`
name a code point, and since the literal is converted to `[]byte`, they contribute
that code point's **UTF-8 encoding** — several bytes, not one. Getting that wrong
would silently mangle every non-ASCII vector, so it is handled explicitly.

Usage:
    gocorpus.py encode <raw-file> <go-file>
    gocorpus.py decode <go-file> <raw-file>
"""
import sys

HEADER = "go test fuzz v1"
_SIMPLE = {"a": 0x07, "b": 0x08, "f": 0x0C, "n": 0x0A, "r": 0x0D,
           "t": 0x09, "v": 0x0B, "\\": 0x5C, '"': 0x22, "'": 0x27}


def encode(raw: bytes) -> str:
    body = "".join(f"\\x{b:02x}" for b in raw)
    return f'{HEADER}\n[]byte("{body}")\n'


def decode(text: str) -> bytes:
    """Parse a Go fuzz corpus entry back to raw bytes.

    Raises ValueError on anything that is not a single []byte("...") entry — a
    multi-argument entry belongs to a fuzz target with a different signature, and
    guessing which argument is the wire input would be worse than failing.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith(HEADER):
        raise ValueError("not a Go fuzz corpus file")
    args = lines[1:]
    if len(args) != 1:
        raise ValueError(f"expected exactly one []byte argument, got {len(args)}")
    arg = args[0].strip()
    if not (arg.startswith('[]byte("') and arg.endswith('")')):
        raise ValueError(f"unsupported argument form: {arg[:40]}")
    s = arg[len('[]byte("'):-2]

    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.extend(c.encode("utf-8"))    # literal char (may be multi-byte)
            i += 1
            continue
        esc = s[i + 1]
        if esc == "x":
            out.append(int(s[i + 2:i + 4], 16)); i += 4
        elif esc in ("u", "U"):
            n = 4 if esc == "u" else 8
            cp = int(s[i + 2:i + 2 + n], 16)
            out.extend(chr(cp).encode("utf-8"))   # code point -> its UTF-8 bytes
            i += 2 + n
        elif esc in _SIMPLE:
            out.append(_SIMPLE[esc]); i += 2
        elif esc.isdigit():                        # \NNN octal
            out.append(int(s[i + 1:i + 4], 8)); i += 4
        else:
            raise ValueError(f"unknown escape \\{esc}")
    return bytes(out)


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("encode", "decode"):
        print(__doc__.strip().splitlines()[-3], file=sys.stderr)
        return 2
    mode, src, dst = sys.argv[1:]
    if mode == "encode":
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "w") as fh:
            fh.write(encode(data))
    else:
        with open(src) as fh:
            text = fh.read()
        with open(dst, "wb") as fh:
            fh.write(decode(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
