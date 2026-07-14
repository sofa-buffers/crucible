// Crucible C++ driver — shared body for BOTH C++ corelibs:
//   cpp    -> corelib-cpp        (pure C++20, header-only)
//   c-cpp  -> corelib-c-cpp      (the C++ wrapper over the C corelib)
//
// build.sh selects which `sofab/sofab.hpp` is on the include path; the generated
// probe.hpp and the sofab:: API (IStreamObject, Result, Error) are identical
// across both, so this one source builds against either.
//
// Single pass: unlike the Rust generated decode, C++ IStreamObject::feed RETURNS
// the Result, so we read the value (*in) and the verdict (r) from one feed.
//
// Emits the canonical form (oracle/canonical.md) over the replay protocol
// (drivers/common/CONTRACT.md).
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "probe.hpp" // generated; pulls the variant's sofab/sofab.hpp

static const char *reject_class(sofab::Error e)
{
    switch (e)
    {
        case sofab::Error::InvalidMessage:  return "invalid_msg";
        case sofab::Error::InvalidArgument: return "argument";
        case sofab::Error::UsageError:      return "usage";
        case sofab::Error::BufferFull:      return "buffer_full";
        default:                            return "other";
    }
}

static void decode_and_report(const std::uint8_t *data, std::size_t len, FILE *out)
{
    message::Probe m; // schema defaults

    // An empty buffer is the valid all-defaults message. The c-cpp wrapper routes
    // to the C istream, which asserts datalen>0 as a debug precondition (see the C
    // driver / docs/ARCHITECTURE.md), so skip feed for len==0 as the C driver does.
    if (len > 0)
    {
        sofab::IStreamObject<message::Probe> in;
        auto r = in.feed(data, len);
        if (r.incomplete())
        {
            // INCOMPLETE (MESSAGE_SPEC §7): bytes end mid-message — the third
            // canonical verdict, neither accept (A) nor reject (R). Not an error.
            std::fputs("I\n", out);
            return;
        }
        if (!r.ok())
        {
#ifdef CRUCIBLE_HAS_LIMIT_EXCEEDED
            // LIMIT_EXCEEDED (generator#102, limit mode only): a configured
            // receiver-side cap on a schema-unbounded field. A policy rejection
            // distinct from INVALID — its own verdict `L`, not `R`. Guarded by the
            // build macro: only the pure-C++ corelib's Error carries LimitExceeded
            // (the c-cpp fixed-capacity wrapper's Error does not).
            if (r.code() == sofab::Error::LimitExceeded)
            {
                std::fputs("L\n", out);
                return;
            }
#endif
            std::fprintf(out, "R %s\n", reject_class(r.code()));
            return;
        }
        m = *in;
    }

    // Accept: re-encode the decoded value and emit its canonical wire as hex.
    std::vector<std::uint8_t> enc = m.encode();
    std::fputs("A ", out);
    for (std::uint8_t b : enc)
    {
        std::fprintf(out, "%02x", b);
    }
    std::fputc('\n', out);
}

int main()
{
    std::vector<std::uint8_t> buf;
    for (;;)
    {
        std::uint8_t lenbytes[4];
        std::size_t got = std::fread(lenbytes, 1, 4, stdin);
        if (got == 0) break; // clean EOF at record boundary
        if (got != 4) { std::fprintf(stderr, "crucible-cpp: short length prefix\n"); return 1; }

        std::uint32_t n = (std::uint32_t)lenbytes[0] | ((std::uint32_t)lenbytes[1] << 8) |
                          ((std::uint32_t)lenbytes[2] << 16) | ((std::uint32_t)lenbytes[3] << 24);

        buf.resize(n);
        if (n > 0 && std::fread(buf.data(), 1, n, stdin) != n)
        {
            std::fprintf(stderr, "crucible-cpp: short payload\n");
            return 1;
        }

        decode_and_report(buf.data(), n, stdout);
        std::fflush(stdout);
    }
    return 0;
}
