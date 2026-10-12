# G-0047 — the generated C++ `encode()` / `encodeTo()` cannot report a refusal: it answers "no bytes", which is also the all-default message

**Status:** ✅ **RESOLVED** — fixed upstream the same day, in generator `05176bb8` ("fix(cpp): encode() and encodeTo() report a refusal"), about two and a half hours after it was filed. Both entry points now return `sofab::Error` and are `[[nodiscard]]`, exactly the generator#673 shape this write-up pointed at: `encode(std::vector<std::uint8_t>&)` and `encodeTo(dst, cap, used)`. The commit also cites a clause this write-up did not — CORELIB_PLAN §5.1.2, "a one-shot helper that ignores that report is non-conformant" — and adds `tests/conformance/cpp/encode_refusal_check.cpp`, which asserts in all four profiles that a refusal and the all-default message agree on their bytes and differ in their status.
**Guard:** scripts/run-encode-fail.sh — the destination-failure gate hands every driver an n-byte destination with no sink, so all four C++ profiles now answer a real refusal through the fixed API on every run (`E buffer_full`), and a regression to the old "answers nothing" shape would stop compiling: both entry points are `[[nodiscard]]` and the status is the return value. `isolate.cpp` in this folder still reproduces the original collision against a pre-fix generator.
**Issue:** [generator#736](https://github.com/sofa-buffers/generator/issues/736) (filed 2026-10-12) — the C++ twin of [generator#673](https://github.com/sofa-buffers/generator/issues/673), which made the Rust `encode()` fallible for exactly this reason, and the sequel to [generator#322](https://github.com/sofa-buffers/generator/issues/322), whose `return {}` fix was unambiguous until #656 added a reachable argument error.

**Found 2026-10-12** while teaching the drivers generator#656's encode-side refusal
(`oracle/canonical.md`'s new `E` verdict). Ten of the eleven backends hand the refusal to
the caller. The C++ backend is the one that does not, and it is not a corelib gap: the
corelib carries the answer and the generated wrapper drops it.

## The rule

generator `docs/ARCHITECTURE.md` §9.6.1 (generator#656): a value past its declared bound
is **refused at encode** with `Error::InvalidArgument`, written nowhere and clamped
nowhere, and "`encode()` then returns no bytes". For a caller that is only half an
answer, because **the all-default message also encodes to no bytes** — an empty wire form
is a legal, round-trippable value (MESSAGE_SPEC §2), and `oracle/canonical.md`'s `A `
line with empty hex is exactly it.

## The measurement

`isolate.cpp` in this folder, against the probe schema's own generated header
(`nested.str` is `maxlen 32`), `corelib: cpp`:

```sh
g++ -std=c++20 -I drivers/cpp/gen/cpp -I vendor/corelib-cpp/include \
    findings/G-0047-*/isolate.cpp -o /tmp/amb && /tmp/amb
```

```
all-default : encode().size()=0  encodeTo()=0  serialize().ok()=1 bytesUsed=0
over-maxlen : encode().size()=0  encodeTo()=0  serialize().ok()=0 bytesUsed=0
```

Both generated entry points answer identically for a legal value and for a refused one.
Only `serialize()` — the surface the caller has to drive itself, on a stream it owns —
tells them apart, through the `Result` / `ok()` the corelib has had all along.

## The generated code

`drivers/cpp/gen/cpp/probe.hpp` (sofabgen 0.0.0-20261012094159-af99e570da92):

```cpp
std::vector<std::uint8_t> encode() const {
    std::vector<std::uint8_t> _out(_maxSize);
    sofab::OStreamView _os{_out.data(), _out.size()};
    serialize(_os);
    if (!_os.ok()) { return {}; }          // the status is read, then discarded
    _out.resize(_os.bytesUsed());
    return _out;
}
std::size_t encodeTo(std::uint8_t *_dst, std::size_t _cap) const noexcept {
    sofab::OStreamView _os{_dst, _cap};
    serialize(_os);
    if (!_os.ok()) { return 0; }           // 0 is also "the message is empty"
    return _os.bytesUsed();
}
```

Both branches look at `_os.ok()` and then throw the distinction away. The doc comment
`encode()` carries makes it worse than silent, because it sends the caller to a surface
that cannot answer either:

```
 * @return The encoded bytes. Empty if the message encodes to nothing,
 *         and also empty if the encode was refused (a value past its
 *         schema bound, see @ref serialize) -- use encodeTo() when the
 *         two need telling apart.
```

`encodeTo()` returns `0` in both cases, as the run above shows. The advice is wrong, and
it is the kind that is only discovered by someone who tries it.

## Attribution: generated code, not the corelib

The corelib does its part. `sofab::OStreamImpl::Result` exposes `ok()` and `code()`,
`rejectArgument()` returns a `Result` carrying `Error::InvalidArgument`, and the
generated `serialize()` already returns that `Result` — §9.6.1's mechanism 3 ("a corelib
hook that only latches the error"). Both C++ corelibs (`corelib-cpp` and the `c-cpp`
wrapper) have it. Nothing a corelib could change would help: the two entry points that
lose the information are **generated**, their signatures are the generator's choice, and
only generated code knows there is a schema bound to refuse in the first place. So this
goes to **`generator`** (the C++ backend), not to `corelib-cpp`.

The precedent is exact and recent: generator#673 made the **Rust** `encode()` fallible
because it "drops `feed`'s `Result`, so `encode()` returns truncated bytes without an
error" — the same defect in the same place, found before #656 landed and fixed by
changing the generated signature. Every other backend reports it: Go returns
`sofab.ErrArgument`, Python raises `SofaArgumentError`, Java/Kotlin/C#/Dart throw,
TypeScript throws, Zig returns `error.InvalidArgument`, and C answers
`SOFAB_RET_E_ARGUMENT`. C++ is the only one left.

## Why it is reachable at all now

Before #656 an encode could only fail by running out of buffer, and both entry points
allocate `_maxSize` — the schema's worst case — so the failure branch was unreachable and
returning `{}` was unambiguous in practice. #656 gave it a trigger that does not depend
on the buffer at all. The 2026-10-07 clamp contract narrows *which* profiles are
affected, not whether the API can say it: the static-storage profiles (`cpp-fixed`,
`cpp-c-cpp`) clamp on assignment and emit no guard, while `cpp` and `cpp-c-cpp-dyn`
generate 19 `rejectArgument()` calls each (`scripts/check-encode-bounds.py`).

## What a fix needs

One of the two shapes the family already uses elsewhere:

- make `encode()` fallible, as generator#673 did for Rust — e.g. `std::optional<std::vector<std::uint8_t>>`, or an out-parameter carrying `sofab::Error`; or
- keep the signatures and add the status, e.g. `encodeTo(dst, cap, sofab::Error &err)` or a `bool ok` out-parameter, so the "no bytes" answer can be qualified.

Either way the doc comment's claim about `encodeTo()` has to go, since today it is simply
untrue.

## What Crucible did meanwhile, and what replaced it

While the issue was open, `drivers/cpp/driver.cpp` re-ran `serialize()` on a stream it
owned whenever the surface under test came back empty, and read the refusal from there.
**That is gone**, in the same session: the API grew the return value, so the workaround
would only be a second opinion about a status the call now reports. The driver reads
`encode()`/`encodeTo()`'s `sofab::Error` directly.

Two things worth keeping from the workaround's short life. It was written reading the
`Result` that `serialize` returns, which is **not** the accumulated verdict — the
generated body discards its intermediate Results and hands back the last write's, so a
two-byte destination answered `code() == None` while the stream was already not ok. The
stream's own `ok()`/`error()` is the status, which is what the `stream` arm still reads
and what `encode()`/`encodeTo()` always read internally. And the defect that exposed it
was found by `scripts/run-encode-fail.sh` on its first run — the gate written to make the
`E` verdict happen at all.
