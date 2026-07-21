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

// ---- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 ----
//
// The default accept path re-encodes the decoded value to wire (schema-agnostic,
// but blind to a decode that differs only where the sparse-canonical wire elides —
// canonical.md §Tradeoff). This second path walks the DECODED value and dumps every
// field + every array element explicitly, matching engine/structured/materialize.py
// byte-for-byte. The generated container types differ between the two corelibs
// (std::vector/std::string vs InlineVector/FixedString/FixedBytes), so every helper
// below is written against the member API both share: .size(), operator[], .data().
static void md_hex(FILE *o, const void *pv, std::size_t n)
{
    const unsigned char *p = static_cast<const unsigned char *>(pv);
    for (std::size_t i = 0; i < n; i++) std::fprintf(o, "%02x", p[i]);
}
static void md_f32(FILE *o, float x)
{
    std::uint32_t b;
    std::memcpy(&b, &x, 4);
    std::fprintf(o, "f%08x", b);
}
static void md_f64(FILE *o, double x)
{
    std::uint64_t b;
    std::memcpy(&b, &x, 8);
    std::fprintf(o, "F%016llx", (unsigned long long)b);
}
// string field: "t" + byte-length + ":" + UTF-8 bytes as hex (std::string / FixedString).
template <typename S>
static void md_string(FILE *o, const S &s)
{
    std::size_t n = s.size();
    std::fprintf(o, "t%zu:", n);
    md_hex(o, s.data(), n);
}
// blob field: "b" + length + ":" + bytes as hex (std::vector<uint8_t> / FixedBytes).
template <typename B>
static void md_blob(FILE *o, const B &b)
{
    std::size_t n = b.size();
    std::fprintf(o, "b%zu:", n);
    md_hex(o, b.data(), n);
}
// Numeric arrays are std::array<T,5> in both variants: emit all N elements. u8/i8
// are cast to a wide int so they print as a number, not a character.
template <typename A>
static void md_uarr(FILE *o, const A &a)
{
    std::fputc('[', o);
    for (std::size_t i = 0; i < a.size(); i++)
    {
        if (i) std::fputc(',', o);
        std::fprintf(o, "u%llu", (unsigned long long)a[i]);
    }
    std::fputc(']', o);
}
template <typename A>
static void md_sarr(FILE *o, const A &a)
{
    std::fputc('[', o);
    for (std::size_t i = 0; i < a.size(); i++)
    {
        if (i) std::fputc(',', o);
        std::fprintf(o, "s%lld", (long long)a[i]);
    }
    std::fputc(']', o);
}
template <typename A>
static void md_f32arr(FILE *o, const A &a)
{
    std::fputc('[', o);
    for (std::size_t i = 0; i < a.size(); i++) { if (i) std::fputc(',', o); md_f32(o, a[i]); }
    std::fputc(']', o);
}
template <typename A>
static void md_f64arr(FILE *o, const A &a)
{
    std::fputc('[', o);
    for (std::size_t i = 0; i < a.size(); i++) { if (i) std::fputc(',', o); md_f64(o, a[i]); }
    std::fputc(']', o);
}

// Dump the decoded Probe as one materialized-form line (no "A " prefix), fields in
// ascending id order. Field ids/layout: oracle/materialized.md and the schema.
static void md_materialize(FILE *o, const message::Probe &m)
{
    std::fputc('{', o);
    std::fprintf(o, "0:u%llu",   (unsigned long long)m.u8);
    std::fprintf(o, ";1:s%lld",  (long long)m.i8);
    std::fprintf(o, ";2:u%llu",  (unsigned long long)m.u16);
    std::fprintf(o, ";3:s%lld",  (long long)m.i16);
    std::fprintf(o, ";4:u%llu",  (unsigned long long)m.u32);
    std::fprintf(o, ";5:s%lld",  (long long)m.i32);
    std::fprintf(o, ";6:u%llu",  (unsigned long long)m.u64);
    std::fprintf(o, ";7:s%lld",  (long long)m.i64);

    // nested struct (id 10): 0:f32 1:f64 2:str 3:blob
    std::fputs(";10:{0:", o); md_f32(o, m.nested.f32);
    std::fputs(";1:", o);     md_f64(o, m.nested.f64);
    std::fputs(";2:", o);     md_string(o, m.nested.str);
    std::fputs(";3:", o);     md_blob(o, m.nested.bytes_field);
    std::fputc('}', o);

    // arrays struct (id 100): eight numeric arrays (0..7) + nested fp arrays (id 10)
    std::fputs(";100:{0:", o); md_uarr(o, m.arrays.u8);
    std::fputs(";1:", o);      md_sarr(o, m.arrays.i8);
    std::fputs(";2:", o);      md_uarr(o, m.arrays.u16);
    std::fputs(";3:", o);      md_sarr(o, m.arrays.i16);
    std::fputs(";4:", o);      md_uarr(o, m.arrays.u32);
    std::fputs(";5:", o);      md_sarr(o, m.arrays.i32);
    std::fputs(";6:", o);      md_uarr(o, m.arrays.u64);
    std::fputs(";7:", o);      md_sarr(o, m.arrays.i64);
    std::fputs(";10:{0:", o);  md_f32arr(o, m.arrays.nested.fp32);
    std::fputs(";1:", o);      md_f64arr(o, m.arrays.nested.fp64);
    std::fputs("}}", o);

    // wrapper arrays (dynamic length is itself the signal): emit elements 0..size()-1.
    std::fputs(";200:[", o);
    for (std::size_t i = 0; i < m.string_array.size(); i++)
    {
        if (i) std::fputc(',', o);
        md_string(o, m.string_array[i]);
    }
    std::fputs("];201:[", o);
    for (std::size_t i = 0; i < m.blob_array.size(); i++)
    {
        if (i) std::fputc(',', o);
        md_blob(o, m.blob_array[i]);
    }
    std::fputs("]}", o);
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

    // Accept. In materialize mode (oracle/materialized.md) dump the decoded value
    // field-by-field instead of re-encoding it to wire.
    static int materialize = -1;
    if (materialize < 0) materialize = std::getenv("SOFAB_MATERIALIZE") ? 1 : 0;
    if (materialize)
    {
        std::fputs("A ", out);
        md_materialize(out, m);
        std::fputc('\n', out);
        return;
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
