/*
 * Crucible C driver — the coverage PACEMAKER for the SofaBuffers differential
 * fuzzer.
 *
 * One decode core, three front-ends:
 *   - default build (gcc/clang): persistent replay driver speaking the protocol
 *     in drivers/common/CONTRACT.md — reads length-prefixed inputs on stdin,
 *     emits one canonical line each on stdout.
 *   - -DCRUCIBLE_LIBFUZZER (clang -fsanitize=fuzzer): LLVMFuzzerTestOneInput,
 *     the block-path coverage-guided pacemaker; exercises the same core, no
 *     stdout.
 *   - -DCRUCIBLE_LIBFUZZER -DCRUCIBLE_FUZZ_STREAM: a second LLVMFuzzerTestOneInput
 *     that steers on the STREAMING (feed/finish) path instead (crucible#178) —
 *     see the comment above decode_chunked() and the one above that
 *     LLVMFuzzerTestOneInput for the input layout and the chunk-invariance oracle.
 *
 * Canonical form: see oracle/canonical.md.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "probe.h"   /* generated from schema/probe.sofab.yaml by build.sh */

/* Map a corelib return code to the canonical reject class (oracle/canonical.md). */
static const char *reject_class(sofab_ret_t r)
{
    switch (r)
    {
        case SOFAB_RET_E_INVALID_MSG: return "invalid_msg";
        case SOFAB_RET_E_ARGUMENT:    return "argument";
        /* SOFAB_RET_E_USAGE was removed in corelib-c-cpp#111; the canonical
         * "usage" class stays in oracle/canonical.md for the corelibs that
         * still have it. Anything unmapped falls through to "other". */
        case SOFAB_RET_E_BUFFER_FULL: return "buffer_full";
        default:                      return "other";
    }
}

/* ---- materialized value dump (oracle/materialized.md), SOFAB_MATERIALIZE=1 ----
 *
 * The default accept path re-encodes the decoded value to wire (schema-agnostic,
 * but blind to a decode that differs only where the sparse-canonical wire elides —
 * see canonical.md §Tradeoff). This second path instead walks the decoded value via
 * the generic object descriptor (the one reflective surface in the family) and dumps
 * every field + every array element explicitly. C is the descriptor anchor; the
 * engine/structured/materialize.py reference is the ground truth every driver matches. */
extern const sofab_object_descr_t _message_descr_message_probe;

static uint64_t md_rdu(const uint8_t *p, unsigned sz)
{
    switch (sz) {
        case 1: { uint8_t  t; memcpy(&t, p, 1); return t; }
        case 2: { uint16_t t; memcpy(&t, p, 2); return t; }
        case 4: { uint32_t t; memcpy(&t, p, 4); return t; }
        default: { uint64_t t; memcpy(&t, p, 8); return t; }
    }
}
static int64_t md_rds(const uint8_t *p, unsigned sz)
{
    switch (sz) {
        case 1: { int8_t  t; memcpy(&t, p, 1); return t; }
        case 2: { int16_t t; memcpy(&t, p, 2); return t; }
        case 4: { int32_t t; memcpy(&t, p, 4); return t; }
        default: { int64_t t; memcpy(&t, p, 8); return t; }
    }
}
static void md_hex(FILE *o, const uint8_t *b, size_t n)
{
    for (size_t i = 0; i < n; i++) fprintf(o, "%02x", b[i]);
}

static void md_value(FILE *o, const sofab_object_descr_t *info,
                     const sofab_object_descr_field_t *f, const uint8_t *base);
static void md_obj(FILE *o, const sofab_object_descr_t *info, const uint8_t *base);

/* An element slot is "empty" (its type default) — the fallback length projection for
 * an **un-sized** wrapper holder, which carries no used-count and can therefore only
 * express 0 or N (object.h, SOFAB_OBJECT_DESCR_SEQ vs _SEQ_SIZED). A sized holder
 * reports its own count instead: `count` is a capacity, not a length (MESSAGE_SPEC §3),
 * and the length is *highest present id + 1* (§5.1) — where the **last** element is
 * always written even when it equals its default (§2), so trimming trailing defaults
 * would report `["a", ""]` as `["a"]` and lose an element the wire carries.
 * A SEQUENCE slot (a struct_array element, WP-05) is empty iff its whole sub-object is
 * default — the recursive check mirrors the corelib's own `_field_is_default`
 * (object.c), which drives the identical interior elision on encode. */
static int md_slot_empty(const sofab_object_descr_t *info,
                         const sofab_object_descr_field_t *f, const uint8_t *base)
{
    const uint8_t *p = base + f->offset;
    switch (f->type) {
    case SOFAB_OBJECT_FIELDTYPE_STRING: return p[0] == '\0';
    case SOFAB_OBJECT_FIELDTYPE_BLOB:
        return f->nested_idx ? (md_rdu(base + f->offset - f->nested_idx, f->nested_idx) == 0)
                             : (f->size == 0);
    case SOFAB_OBJECT_FIELDTYPE_UNSIGNED:
    case SOFAB_OBJECT_FIELDTYPE_SIGNED:
        return md_rdu(p, f->element_size) == 0;
    case SOFAB_OBJECT_FIELDTYPE_SEQUENCE: {
        const sofab_object_descr_t *nested = info->nested_list[f->nested_idx];
        for (size_t i = 0; i < nested->field_count; i++)
            if (!md_slot_empty(nested, &nested->field_list[i], p)) return 0;
        return 1;
    }
    default: return 0;  /* fp/array element kinds: treat as present */
    }
}

/* The element count a native `count: N` array actually carries.
 *
 * MESSAGE_SPEC §3: `count` is a CAPACITY, and the wire count M *is* the array's
 * length — "a decoder materializes exactly the M elements the wire carries … a
 * target pre-sized to N leaves the slots at [M, N) at their element default and
 * reports a length of M. There is no fill-to-N." The C object model is exactly such
 * a pre-sized target, so walking `f->size / element_size` slots would materialize the
 * spare capacity as trailing default elements — the removed fill-to-N.
 *
 * A sized array descriptor (SOFAB_OBJECT_FIELD_ARRAY_SIZED) carries that length in a
 * companion member the corelib static-asserts to sit immediately before the payload,
 * with `nested_idx` holding its byte width — the same convention BLOB_SIZED uses. An
 * un-sized descriptor has no length member and is full-capacity by definition. */
static size_t md_array_len(const sofab_object_descr_field_t *f, const uint8_t *base,
                           size_t capacity)
{
    if (!f->nested_idx) return capacity;
    size_t n = (size_t)md_rdu(base + f->offset - f->nested_idx, f->nested_idx);
    return n > capacity ? capacity : n;
}

static void md_value(FILE *o, const sofab_object_descr_t *info,
                     const sofab_object_descr_field_t *f, const uint8_t *base)
{
    const uint8_t *p = base + f->offset;
    switch (f->type) {
    case SOFAB_OBJECT_FIELDTYPE_UNSIGNED:
        fprintf(o, "u%llu", (unsigned long long)md_rdu(p, f->element_size)); break;
    case SOFAB_OBJECT_FIELDTYPE_SIGNED:
        fprintf(o, "s%lld", (long long)md_rds(p, f->element_size)); break;
    case SOFAB_OBJECT_FIELDTYPE_BOOLEAN:
        /* §4.4: two-valued, so the materialized form is u1/u0 — a decode has already
         * normalized every non-zero spelling away (that is the rule under test). Read
         * the destination as bytes, never as a `bool` lvalue: a `bool` object holding a
         * value outside {0,1} has no value at all, so reading it could not tell us
         * whether the decode normalized. */
        fprintf(o, "u%u", md_rdu(p, f->element_size) ? 1u : 0u); break;
    case SOFAB_OBJECT_FIELDTYPE_FP32:
        { uint32_t b; memcpy(&b, p, 4); fprintf(o, "f%08x", b); } break;
    case SOFAB_OBJECT_FIELDTYPE_FP64:
        { uint64_t b; memcpy(&b, p, 8); fprintf(o, "F%016llx", (unsigned long long)b); } break;
    case SOFAB_OBJECT_FIELDTYPE_STRING:
        { size_t n = strlen((const char *)p); fprintf(o, "t%zu:", n); md_hex(o, p, n); } break;
    case SOFAB_OBJECT_FIELDTYPE_BLOB: {
        size_t n = f->nested_idx ? (size_t)md_rdu(base + f->offset - f->nested_idx, f->nested_idx)
                                 : f->size;
        if (n > f->size) n = f->size;
        fprintf(o, "b%zu:", n); md_hex(o, p, n);
        } break;
    case SOFAB_OBJECT_FIELDTYPE_ARRAY_UNSIGNED:
    case SOFAB_OBJECT_FIELDTYPE_ARRAY_BOOLEAN:
    case SOFAB_OBJECT_FIELDTYPE_ARRAY_SIGNED: {
        unsigned es = f->element_size;
        size_t cnt = md_array_len(f, base, es ? f->size / es : 0);
        int sg = (f->type == SOFAB_OBJECT_FIELDTYPE_ARRAY_SIGNED);
        /* an array of boolean is an array of unsigned 0/1 (MESSAGE_SPEC §4.7), each
         * element normalized on the same rule as the scalar above */
        int bl = (f->type == SOFAB_OBJECT_FIELDTYPE_ARRAY_BOOLEAN);
        fputc('[', o);
        for (size_t i = 0; i < cnt; i++) {
            if (i) fputc(',', o);
            if (sg) fprintf(o, "s%lld", (long long)md_rds(p + i * es, es));
            else {
                unsigned long long v = (unsigned long long)md_rdu(p + i * es, es);
                fprintf(o, "u%llu", bl ? (v ? 1ULL : 0ULL) : v);
            }
        }
        fputc(']', o);
        } break;
    case SOFAB_OBJECT_FIELDTYPE_ARRAY_FP32: {
        size_t cnt = md_array_len(f, base, f->size / 4); fputc('[', o);
        for (size_t i = 0; i < cnt; i++) { if (i) fputc(',', o);
            uint32_t b; memcpy(&b, p + i * 4, 4); fprintf(o, "f%08x", b); }
        fputc(']', o);
        } break;
    case SOFAB_OBJECT_FIELDTYPE_ARRAY_FP64: {
        size_t cnt = md_array_len(f, base, f->size / 8); fputc('[', o);
        for (size_t i = 0; i < cnt; i++) { if (i) fputc(',', o);
            uint64_t b; memcpy(&b, p + i * 8, 8); fprintf(o, "F%016llx", (unsigned long long)b); }
        fputc(']', o);
        } break;
    case SOFAB_OBJECT_FIELDTYPE_SEQUENCE: {
        const sofab_object_descr_t *nested = info->nested_list[f->nested_idx];
        if (nested->fixed_seq & SOFAB_OBJECT_SEQ_HOLDER) {   /* a wrapper array */
            /* A sized holder keeps the element count in a member the corelib
             * static-asserts to sit first in the holder (object.h,
             * SOFAB_OBJECT_DESCR_SEQ_SIZED); its width is the bits above
             * SOFAB_OBJECT_SEQ_LEN_SHIFT. That count is the array's length (§5.1) and
             * is the only source that survives a default-valued LAST element, which
             * §2 requires to be present. Without one, fall back to the
             * highest-populated projection — all an un-sized holder can express. */
            unsigned lw = nested->fixed_seq >> SOFAB_OBJECT_SEQ_LEN_SHIFT;
            size_t n;
            if (lw) {
                n = (size_t)md_rdu(p, lw);
                if (n > nested->field_count) n = nested->field_count;
            } else {
                n = 0;
                for (size_t i = 0; i < nested->field_count; i++)
                    if (!md_slot_empty(nested, &nested->field_list[i], p)) n = i + 1;
            }
            fputc('[', o);
            for (size_t i = 0; i < n; i++) {
                if (i) fputc(',', o);
                md_value(o, nested, &nested->field_list[i], p);
            }
            fputc(']', o);
        } else {                   /* a struct/union: recurse as an object */
            md_obj(o, nested, p);
        }
        } break;
    default: fputc('?', o); break;
    }
}

static void md_obj(FILE *o, const sofab_object_descr_t *info, const uint8_t *base)
{
    fputc('{', o);
    for (size_t i = 0; i < info->field_count; i++) {
        const sofab_object_descr_field_t *f = &info->field_list[i];
        if (i) fputc(';', o);
        fprintf(o, "%u:", (unsigned)f->id);
        md_value(o, info, f, base);
    }
    fputc('}', o);
}

/* ---- the streaming axes (drivers/common/CONTRACT.md) -------------------------
 *
 * The replay protocol hands each record over whole and re-encodes it with one call,
 * so neither streaming surface of the generated API is reachable through it. Unset,
 * every variable below is today's behaviour byte for byte.
 *
 * C has no allocating encode -- `message_probe_encode` writes into a caller buffer,
 * which IS the `to` surface -- so this driver's default path is already `to` and
 * SOFAB_ENCODE=new is a hard error rather than a fallback (meta:
 * encode_surfaces=to,stream).
 *
 * Like Rust, the generated decoder has no `status`: the doc on
 * message_probe_decoder_t states the rule directly -- a feed reports only whether
 * THE BYTES ended on a field boundary (OK) or mid-field (INCOMPLETE), and "the last
 * verdict says whether it ended half-read". So the last feed's return is the status,
 * mapped exactly as the one-shot return is. */
enum enc_surface { ENC_TO, ENC_STREAM };

static struct {
    long split;
    long chunk;
    int scrub;
    enum enc_surface enc;
    int enc_set;              /* SOFAB_ENCODE was present -- see the announcement */
    long flush;
} g_cfg;

static long env_long(const char *name)
{
    const char *v = getenv(name);
    if (!v || !*v) return 0;
    return strtol(v, NULL, 10);
}

static void read_stream_cfg(void)
{
    const char *e;
    g_cfg.split = env_long("SOFAB_SPLIT");
    g_cfg.chunk = env_long("SOFAB_CHUNK");
    g_cfg.flush = env_long("SOFAB_FLUSH");
    e = getenv("SOFAB_CHUNK_SCRUB");
    g_cfg.scrub = e && *e && strcmp(e, "0") != 0;
    e = getenv("SOFAB_ENCODE");
    /* Whether the variable was PRESENT, not merely which surface it named. `to` is
     * this backend's default (there is no allocating encode), so without this flag
     * the announcement below stays silent on SOFAB_ENCODE=to and the gate cannot
     * tell an honoured request from an ignored one -- the exact hole the
     * announcement exists to close. Caught by the encode gate on 2026-08-16, when
     * it started asserting the announcement instead of discarding it. */
    g_cfg.enc_set = e && *e;
    if (!e || !*e || strcmp(e, "to") == 0)      g_cfg.enc = ENC_TO;
    else if (strcmp(e, "stream") == 0)          g_cfg.enc = ENC_STREAM;
    else if (strcmp(e, "new") == 0)
    {
        fprintf(stderr, "crucible-c: SOFAB_ENCODE=new — C has no allocating encode "
                        "(it has to, stream)\n");
        exit(2);
    }
    else
    {
        fprintf(stderr, "crucible-c: unknown SOFAB_ENCODE=%s (this backend has to, "
                        "stream)\n", e);
        exit(2);
    }
    /* Announce on stderr (never parsed). A driver that silently ignored these would
     * be indistinguishable from one that honours them -- identical stdout either
     * way -- so this makes "it really re-feeds" checkable rather than asserted. */
    if (g_cfg.split || g_cfg.chunk || g_cfg.scrub || g_cfg.flush ||
        g_cfg.enc_set || g_cfg.enc != ENC_TO)
    {
        fprintf(stderr, "crucible-c: streaming cfg split=%ld chunk=%ld scrub=%d "
                        "enc=%s flush=%ld\n",
                g_cfg.split, g_cfg.chunk, g_cfg.scrub,
                g_cfg.enc == ENC_TO ? "to" : "stream", g_cfg.flush);
    }
}

/* Feed the record in the given pieces through ONE decoder. Never an empty chunk:
 * k<=0, k>=len and n>=len all mean one chunk holding the whole record, which
 * matters twice over here -- it is today's single feed, and sofab_istream_feed
 * asserts datalen>0. Returns the last feed's verdict.
 *
 * Takes its settings as arguments rather than reading g_cfg, so both the replay
 * front-end (which reads them from the environment) and the streaming fuzz
 * front-end (which reads them from the fuzz input, crucible#178) share one
 * implementation. */
static sofab_ret_t decode_chunked(message_probe_t *m, const uint8_t *buf, size_t len,
                                  long split, long chunk, int scrub)
{
    message_probe_decoder_t d;
    sofab_ret_t r = SOFAB_RET_OK;
    uint8_t scratch[MESSAGE_PROBE_MAX_SIZE];
    size_t step, off;

    message_probe_decoder_init(&d, m);

    if (chunk > 0)                                   step = (size_t)chunk;
    else if (split > 0 && (size_t)split < len)       step = (size_t)split;
    else                                              step = len;

    off = 0;
    while (off < len)
    {
        size_t n = len - off < step ? len - off : step;
        /* A two-way split is two chunks, not fixed-size: after the first cut, the
         * rest goes in one piece. */
        if (chunk <= 0 && off > 0) n = len - off;
        if (scrub && n <= sizeof(scratch))
        {
            /* Scrub needs a buffer the driver owns: feed it, then overwrite. A
             * decoder that borrowed from the chunk rather than copying out of it
             * reads back 0xA5. */
            memcpy(scratch, buf + off, n);
            r = message_probe_decoder_feed(&d, scratch, n);
            memset(scratch, 0xA5, n);
        }
        else
        {
            r = message_probe_decoder_feed(&d, buf + off, n);
        }
        /* INCOMPLETE mid-stream only means THOSE bytes ended mid-field; any other
         * error is terminal. */
        if (r != SOFAB_RET_OK && r != SOFAB_RET_INCOMPLETE) break;
        off += n;
    }
    return r;
}

/* Accumulator for the streaming encode's flush callback. */
struct enc_acc {
    uint8_t bytes[MESSAGE_PROBE_MAX_SIZE];
    size_t len;
};

static void enc_flush_cb(sofab_ostream_t *ctx, const uint8_t *data, size_t len,
                         void *usrptr)
{
    struct enc_acc *a = (struct enc_acc *)usrptr;
    (void)ctx;
    if (a->len + len <= sizeof(a->bytes))
    {
        memcpy(a->bytes + a->len, data, len);
        a->len += len;
    }
}

/* Which generated call produces the `A <hex>` payload. Both surfaces must emit
 * identical bytes for one decoded value, and SOFAB_FLUSH must not change that: it
 * gives the ostream an n-byte buffer with a flush callback, so the encoder crosses a
 * buffer boundary at every offset -- the encode-side mirror of SOFAB_CHUNK=1. */
static sofab_ret_t encode_via(const message_probe_t *m, uint8_t *dst, size_t dstlen,
                              size_t *used)
{
    if (g_cfg.enc == ENC_TO)
    {
        return message_probe_encode(m, dst, dstlen, used);
    }
    {
        struct enc_acc acc;
        sofab_ostream_t os;
        uint8_t small[MESSAGE_PROBE_MAX_SIZE];
        size_t cap = g_cfg.flush > 0 ? (size_t)g_cfg.flush : sizeof(small);
        sofab_ret_t r;
        acc.len = 0;
        if (cap == 0) cap = 1;
        if (cap > sizeof(small)) cap = sizeof(small);
        sofab_ostream_init(&os, small, cap, 0, enc_flush_cb, &acc);
        r = message_probe_encode_to(&os, m);
        (void)sofab_ostream_flush(&os);
        if (r != SOFAB_RET_OK) return r;
        if (acc.len > dstlen) return SOFAB_RET_E_BUFFER_FULL;
        memcpy(dst, acc.bytes, acc.len);
        *used = acc.len;
        return SOFAB_RET_OK;
    }
}

/* Decode one candidate input and write its canonical line to `out`
 * (oracle/canonical.md: decode -> re-encode -> hex). */
static void decode_and_report(const uint8_t *buf, size_t len, FILE *out)
{
    message_probe_t m;
    message_probe_init(&m);

    /* An empty buffer is the valid sparse-canonical encoding of the all-defaults
     * message (Go decodes it so). corelib-c-cpp's sofab_istream_feed asserts
     * datalen>0 as a debug precondition; under NDEBUG the same call returns OK
     * with defaults. We keep asserts ON (they catch real bugs on non-empty
     * input) but honor the precondition here so a valid empty message isn't a
     * false abort. See docs/ARCHITECTURE.md. */
    if (len > 0)
    {
        /* The chunked path is taken ONLY when a chunking variable is set, so the
         * default stays the one-shot message_probe_decode byte for byte -- which is
         * also what makes the gate meaningful: it then compares two genuinely
         * different code paths rather than one against itself. */
        sofab_ret_t r = (g_cfg.split || g_cfg.chunk || g_cfg.scrub)
                            ? decode_chunked(&m, buf, len, g_cfg.split, g_cfg.chunk, g_cfg.scrub)
                            : message_probe_decode(&m, buf, len);
        if (r == SOFAB_RET_INCOMPLETE)
        {
            /* Decode ended mid-field or with an open sequence: valid so far but
             * not a complete message. Distinct hard verdict (oracle/canonical.md,
             * MESSAGE_SPEC §7) — must not collapse into A (accept) or R (reject). */
            fputs("I\n", out);
            return;
        }
        if (r != SOFAB_RET_OK)
        {
            fprintf(out, "R %s\n", reject_class(r));
            return;
        }
    }

    /* Accept. In materialize mode (oracle/materialized.md) dump the decoded value
     * via the object descriptor instead of re-encoding it to wire. */
    static int materialize = -1;
    if (materialize < 0) materialize = getenv("SOFAB_MATERIALIZE") ? 1 : 0;
    if (materialize) {
        fputs("A ", out);
        md_obj(out, &_message_descr_message_probe, (const uint8_t *)&m);
        fputc('\n', out);
        return;
    }

    /* Accept: re-encode the decoded value and emit its canonical wire as hex. */
    uint8_t enc[MESSAGE_PROBE_MAX_SIZE];
    size_t used = 0;
    sofab_ret_t er = encode_via(&m, enc, sizeof(enc), &used);
    if (er != SOFAB_RET_OK)
    {
        fprintf(out, "R %s\n", reject_class(er));
        return;
    }
    fputs("A ", out);
    for (size_t k = 0; k < used; k++)
    {
        fprintf(out, "%02x", enc[k]);
    }
    fputc('\n', out);
}

#ifdef CRUCIBLE_LIBFUZZER
#include "sofab_mutator.h"   /* engine/mutator: grammar-aware mutation ops */

#ifndef CRUCIBLE_FUZZ_STREAM
/* Block-path coverage pacemaker front-end. Exercise the decode core; sanitizers
 * catch memory faults, the differential path catches disagreement. No output. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    message_probe_t m;
    message_probe_init(&m);
    if (size > 0) (void)message_probe_decode(&m, data, size); /* see decode_and_report */
    return 0;
}
#else
/* Streaming (feed/finish) coverage pacemaker front-end (crucible#178). Nothing
 * else steers a fuzzer on this path: every other front-end calls the one-shot
 * decode, so feed/finish is only ever REPLAYED, over a corpus the block path
 * grew. This is a second, independent target rather than a mode of the first
 * one, because libFuzzer's coverage counters are per-binary and mixing the two
 * paths in one target would blur which one the fuzzer is actually steering on.
 *
 * Input layout: a fixed 3-byte header in front of the message,
 * [mode][param_lo][param_hi], mirroring the two replay axes (CONTRACT.md
 * "Decode side") exactly so a violation this finds reproduces directly against
 * the replay driver:
 *   mode&1==0 -> split = param   (SOFAB_SPLIT=param: two chunks, [0,param) then
 *                                 the rest)
 *   mode&1==1 -> chunk = param   (SOFAB_CHUNK=param: fixed-size chunks)
 * The other 7 bits of mode are reserved and ignored, so a mutation of them is
 * harmless. param==0 or param>=len means one chunk holding the whole record,
 * same as an unset SOFAB_SPLIT/SOFAB_CHUNK (decode_chunked's own rule).
 *
 * This does not merely feed the streaming path and hope a sanitizer trips --
 * every streaming defect found so far (F-0058, F-0060, F-0061, crucible#130)
 * was a VALUE or VERDICT mismatch, not a memory fault, and nothing but this
 * oracle would notice one. So each input is decoded twice, one-shot and
 * chunked per the header, and the run aborts if the two disagree: on the
 * verdict class (A / I / R <class>), or, when both accept, on the re-encoded
 * bytes. That is exactly the invariant run-chunked.sh checks over the replay
 * driver (CONTRACT.md: "an intra-driver invariant"); this is the fuzz-time
 * form of the same check. The chunked decode always scrubs each fed buffer
 * after the corelib returns from it (0xA5), so a decoder that borrowed from a
 * chunk instead of copying out of it is caught the same way SOFAB_CHUNK_SCRUB
 * catches it in the replay driver. */
#define STREAM_HDR 3

/* Classify one decode outcome into the verdict class the differential
 * comparator would see (oracle/canonical.md): "A", "I" or "R <class>". Fills
 * *used (encoded length) only for "A" -- decode_and_report's re-encode step,
 * duplicated here rather than shared because that function owns writing to a
 * FILE*, not producing a comparable value. */
static void stream_verdict(sofab_ret_t r, const message_probe_t *m,
                           char *cls, size_t clscap,
                           uint8_t *enc, size_t enccap, size_t *used)
{
    *used = 0;
    if (r == SOFAB_RET_INCOMPLETE) { snprintf(cls, clscap, "I"); return; }
    if (r != SOFAB_RET_OK) { snprintf(cls, clscap, "R %s", reject_class(r)); return; }
    sofab_ret_t er = message_probe_encode(m, enc, enccap, used);
    if (er != SOFAB_RET_OK) { snprintf(cls, clscap, "R %s", reject_class(er)); *used = 0; return; }
    snprintf(cls, clscap, "A");
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size <= STREAM_HDR) return 0;
    const uint8_t *msg = data + STREAM_HDR;
    size_t len = size - STREAM_HDR;
    if (len == 0) return 0;   /* CONTRACT rule 4: a length-0 record is never fed */

    long param = (long)((unsigned)data[1] | ((unsigned)data[2] << 8));
    long split = (data[0] & 1) ? 0 : param;
    long chunk = (data[0] & 1) ? param : 0;

    message_probe_t a, b;
    message_probe_init(&a);
    message_probe_init(&b);
    sofab_ret_t ra = message_probe_decode(&a, msg, len);
    sofab_ret_t rb = decode_chunked(&b, msg, len, split, chunk, /*scrub=*/1);

    char cls_a[16], cls_b[16];
    uint8_t enc_a[MESSAGE_PROBE_MAX_SIZE], enc_b[MESSAGE_PROBE_MAX_SIZE];
    size_t used_a, used_b;
    stream_verdict(ra, &a, cls_a, sizeof(cls_a), enc_a, sizeof(enc_a), &used_a);
    stream_verdict(rb, &b, cls_b, sizeof(cls_b), enc_b, sizeof(enc_b), &used_b);

    int mismatch = strcmp(cls_a, cls_b) != 0;
    if (!mismatch && strcmp(cls_a, "A") == 0)
        mismatch = used_a != used_b || memcmp(enc_a, enc_b, used_a) != 0;

    if (mismatch)
    {
        fprintf(stderr, "crucible-c: CHUNK INVARIANCE VIOLATION -- mode=%s param=%ld "
                        "len=%zu one-shot=[%s] chunked=[%s]\n",
                (data[0] & 1) ? "chunk" : "split", param, len, cls_a, cls_b);
        if (strcmp(cls_a, "A") == 0)
        {
            fputs("crucible-c:   one-shot hex: ", stderr);
            for (size_t k = 0; k < used_a; k++) fprintf(stderr, "%02x", enc_a[k]);
            fputc('\n', stderr);
        }
        if (strcmp(cls_b, "A") == 0)
        {
            fputs("crucible-c:   chunked  hex: ", stderr);
            for (size_t k = 0; k < used_b; k++) fprintf(stderr, "%02x", enc_b[k]);
            fputc('\n', stderr);
        }
        fprintf(stderr, "crucible-c:   replay: strip the %d-byte header, then "
                        "SOFAB_%s=%ld over the remaining %zu-byte message\n",
                STREAM_HDR, (data[0] & 1) ? "CHUNK" : "SPLIT", param, len);
        abort();
    }
    return 0;
}
#endif /* CRUCIBLE_FUZZ_STREAM */

/* Build with -DCRUCIBLE_NO_CUSTOM_MUTATOR to fall back to libFuzzer's byte-level
 * mutator (the A/B baseline for the coverage check in DESIGN.md). */
#ifndef CRUCIBLE_NO_CUSTOM_MUTATOR
/* libFuzzer's built-in mutator — used both as a ~40% mix-in and as the fallback
 * for the structure-aware ops (keeps libFuzzer's generic power; see DESIGN.md). */
size_t LLVMFuzzerMutate(uint8_t *data, size_t size, size_t max_size);

#ifndef CRUCIBLE_FUZZ_STREAM
/* Structure-aware custom mutator (engine/mutator/DESIGN.md). libFuzzer picks it
 * up automatically when present. Deterministic in `seed`; ~40% of the time it
 * defers to the byte-level mutator, otherwise it applies one grammar-aware op
 * (varint/header/length/count/sequence/utf8/fp) so the pacemaker reaches deep
 * TLV paths on purpose instead of by luck. */
size_t LLVMFuzzerCustomMutator(uint8_t *data, size_t size, size_t max_size,
                               unsigned int seed)
{
    uint32_t rng = (uint32_t)seed ^ 0x9e3779b9u;   /* never 0; see sofab_mutator */
    if ((rng & 7) < 3)                              /* ~37.5%: generic mutator */
        return LLVMFuzzerMutate(data, size, max_size);
    return sofab_grammar_mutate(data, size, max_size, &rng);
}
#else
/* Header-aware structure-aware mutator: mutates EITHER the 3-byte
 * mode/param header OR the message, never both in the same call, so the
 * grammar-aware ops below always see a clean message and never corrupt the
 * cut position by treating it as wire bytes. Falls back to the whole-buffer
 * generic mutator whenever there isn't room for a header, which is always a
 * valid (if header-oblivious) mutation to hand back. */
size_t LLVMFuzzerCustomMutator(uint8_t *data, size_t size, size_t max_size,
                               unsigned int seed)
{
    uint32_t rng = (uint32_t)seed ^ 0x9e3779b9u;
    if (size < STREAM_HDR || max_size < STREAM_HDR)
        return LLVMFuzzerMutate(data, size, max_size);

    rng = rng * 1103515245u + 12345u;
    if ((rng & 7) == 0)   /* ~1/8: re-roll the header only, message untouched */
    {
        size_t msg_len = size - STREAM_HDR;
        rng = rng * 1103515245u + 12345u;
        data[0] = (uint8_t)rng;   /* mode: bit 0; the rest is reserved */
        rng = rng * 1103515245u + 12345u;
        uint32_t param = (rng & 1)
            ? (rng % 16) + 1                                /* small: near-boundary cuts */
            : (msg_len > 0 ? (uint32_t)(rng % msg_len) : 0); /* anywhere inside the message */
        data[1] = (uint8_t)param;
        data[2] = (uint8_t)(param >> 8);
        return size;
    }
    /* Otherwise: mutate the message only, header untouched. Same ~37.5%
     * generic / else structure-aware split as the block pacemaker. */
    size_t msg_size = size - STREAM_HDR;
    size_t msg_max = max_size - STREAM_HDR;
    size_t new_len = ((rng & 7) < 3)
        ? LLVMFuzzerMutate(data + STREAM_HDR, msg_size, msg_max)
        : sofab_grammar_mutate(data + STREAM_HDR, msg_size, msg_max, &rng);
    return STREAM_HDR + new_len;
}
#endif /* CRUCIBLE_FUZZ_STREAM */
#endif /* CRUCIBLE_NO_CUSTOM_MUTATOR */
#else
/* Persistent replay front-end (drivers/common/CONTRACT.md). */
static int read_exact(void *dst, size_t n)
{
    return fread(dst, 1, n, stdin) == n;
}

int main(void)
{
    uint8_t *buf = NULL;
    size_t cap = 0;

    read_stream_cfg();

    for (;;)
    {
        uint8_t lenbytes[4];
        size_t got = fread(lenbytes, 1, 4, stdin);
        if (got == 0) break;                 /* clean EOF at record boundary */
        if (got != 4) { fprintf(stderr, "crucible-c: short length prefix\n"); return 1; }

        uint32_t n = (uint32_t)lenbytes[0] | ((uint32_t)lenbytes[1] << 8) |
                     ((uint32_t)lenbytes[2] << 16) | ((uint32_t)lenbytes[3] << 24);

        if (n > cap)
        {
            uint8_t *nb = realloc(buf, n);
            if (!nb) { fprintf(stderr, "crucible-c: oom (%u bytes)\n", n); free(buf); return 1; }
            buf = nb;
            cap = n;
        }
        if (n > 0 && !read_exact(buf, n)) { fprintf(stderr, "crucible-c: short payload\n"); free(buf); return 1; }

        /* Always hand decode a valid pointer, even for a 0-byte input. */
        static uint8_t empty[1];
        decode_and_report(n ? buf : empty, n, stdout);
        fflush(stdout);
    }

    free(buf);
    return 0;
}
#endif
