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

FuzzProbeStream (crucible#178) has TWO more arguments after the []byte, a mode
byte and a param uint16 (drivers/go/fuzz_test.go). Go ALWAYS prints a uint8
argument as `byte('c')` — a quoted rune, printable code point or escape — and a
uint16 as plain `uint16(N)`; its own parser doesn't care about the type-name
prefix or which of the two numeric forms follows, though, and accepts a
hand-written `uint8(1)` line just as readily (verified empirically), so this
module only ever WRITES the plain decimal form (`uint8(N)`) and reads both
that and Go's own `byte('c')`.

Usage:
    gocorpus.py encode <raw-file> <go-file> [--mode M --param P]
    gocorpus.py decode <go-file> <raw-file>
    gocorpus.py decode --first-bytes <go-file> <raw-file> [<args-file>]

`decode` (no flag) is strict: exactly one []byte argument, as FuzzProbe's
corpus entries are — a multi-argument entry there would mean guessing which
argument is the wire input, worse than failing. `decode --first-bytes` is for
FuzzProbeStream's corpus: it accepts any number of trailing scalar arguments,
writes only the []byte payload to <raw-file>, and — when <args-file> is given —
writes each trailing argument's decoded integer value to it, one per line, in
declaration order (mode, then param), so a caller can print the replay recipe
without this module needing to know what they mean.
"""
import sys

HEADER = "go test fuzz v1"
_SIMPLE = {"a": 0x07, "b": 0x08, "f": 0x0C, "n": 0x0A, "r": 0x0D,
           "t": 0x09, "v": 0x0B, "\\": 0x5C, '"': 0x22, "'": 0x27}


def encode(raw: bytes, mode: int = None, param: int = None) -> str:
    body = "".join(f"\\x{b:02x}" for b in raw)
    out = f'{HEADER}\n[]byte("{body}")\n'
    if mode is not None:
        out += f"uint8({mode})\n"
    if param is not None:
        out += f"uint16({param})\n"
    return out


def _decode_bytes_literal(s: str) -> bytes:
    """Decode the contents of a Go `"..."` string literal (no surrounding
    quotes) to the bytes it represents."""
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


def _parse_rune_literal(inner: str) -> int:
    """Parse a Go rune literal's contents (without the surrounding quotes) to
    its code point. Used for byte(...)/uint8(...) fuzz arguments, which Go
    prints as a quoted char when the value is a printable code point."""
    if inner.startswith("\\"):
        esc = inner[1]
        if esc == "x":
            return int(inner[2:4], 16)
        if esc in ("u", "U"):
            n = 4 if esc == "u" else 8
            return int(inner[2:2 + n], 16)
        if esc in _SIMPLE:
            return _SIMPLE[esc]
        if esc.isdigit():
            return int(inner[1:4], 8)
        raise ValueError(f"unknown rune escape \\{esc}")
    return ord(inner)


def _parse_scalar_arg(arg: str) -> int:
    """Parse one trailing scalar fuzz argument, e.g. `byte('A')`, `uint8(1)` or
    `uint16(300)`, to its integer value."""
    arg = arg.strip()
    if "(" not in arg or not arg.endswith(")"):
        raise ValueError(f"unsupported argument form: {arg[:40]}")
    inner = arg[arg.index("(") + 1:-1]
    if inner.startswith("'") and inner.endswith("'"):
        return _parse_rune_literal(inner[1:-1])
    return int(inner, 0)


def _split(text: str) -> list:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith(HEADER):
        raise ValueError("not a Go fuzz corpus file")
    return lines[1:]


def decode(text: str) -> bytes:
    """Parse a Go fuzz corpus entry back to raw bytes.

    Raises ValueError on anything that is not a single []byte("...") entry — a
    multi-argument entry belongs to a fuzz target with a different signature, and
    guessing which argument is the wire input would be worse than failing.
    """
    args = _split(text)
    if len(args) != 1:
        raise ValueError(f"expected exactly one []byte argument, got {len(args)}")
    arg = args[0].strip()
    if not (arg.startswith('[]byte("') and arg.endswith('")')):
        raise ValueError(f"unsupported argument form: {arg[:40]}")
    return _decode_bytes_literal(arg[len('[]byte("'):-2])


def decode_first_bytes(text: str):
    """Parse a (possibly multi-argument) Go fuzz corpus entry, returning
    (payload, extra_args): the first []byte argument's bytes, and every
    trailing scalar argument's decoded integer value, in declaration order."""
    args = _split(text)
    if not args:
        raise ValueError("no arguments")
    first = args[0].strip()
    if not (first.startswith('[]byte("') and first.endswith('")')):
        raise ValueError(f"unsupported first argument form: {first[:40]}")
    payload = _decode_bytes_literal(first[len('[]byte("'):-2])
    extra = [_parse_scalar_arg(a) for a in args[1:]]
    return payload, extra


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] not in ("encode", "decode"):
        print(__doc__.strip().splitlines()[-3], file=sys.stderr)
        return 2
    mode = argv[0]
    rest = argv[1:]

    if mode == "encode":
        pos = []
        m = p = None
        i = 0
        while i < len(rest):
            if rest[i] == "--mode":
                m = int(rest[i + 1]); i += 2
            elif rest[i] == "--param":
                p = int(rest[i + 1]); i += 2
            else:
                pos.append(rest[i]); i += 1
        if len(pos) != 2:
            print("usage: gocorpus.py encode <raw-file> <go-file> [--mode M --param P]",
                  file=sys.stderr)
            return 2
        if (m is None) != (p is None):
            print("--mode and --param must be given together", file=sys.stderr)
            return 2
        src, dst = pos
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "w") as fh:
            fh.write(encode(data, m, p))
        return 0

    # decode
    first_bytes = rest and rest[0] == "--first-bytes"
    pos = rest[1:] if first_bytes else rest
    if first_bytes:
        if len(pos) not in (2, 3):
            print("usage: gocorpus.py decode --first-bytes <go-file> <raw-file> [<args-file>]",
                  file=sys.stderr)
            return 2
        src, dst = pos[0], pos[1]
        args_out = pos[2] if len(pos) == 3 else None
        with open(src) as fh:
            text = fh.read()
        payload, extra = decode_first_bytes(text)
        with open(dst, "wb") as fh:
            fh.write(payload)
        if args_out is not None:
            with open(args_out, "w") as fh:
                for v in extra:
                    fh.write(f"{v}\n")
        return 0

    if len(pos) != 2:
        print("usage: gocorpus.py decode <go-file> <raw-file>", file=sys.stderr)
        return 2
    src, dst = pos
    with open(src) as fh:
        text = fh.read()
    with open(dst, "wb") as fh:
        fh.write(decode(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
