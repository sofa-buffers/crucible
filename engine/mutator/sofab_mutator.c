/*
 * Crucible structure-aware mutator — implementation. See sofab_mutator.h and
 * engine/mutator/DESIGN.md. Pure C11, no libFuzzer / corelib dependency.
 *
 * Strategy: a best-effort forward walk over the wire records the byte offsets of
 * the interesting sites (field headers, all varints, fixlen length-headers, array
 * counts, and fixlen payload regions with their subtype). One mutation operator,
 * chosen from those applicable to the sites found, is then applied. The walk is
 * bounded and tolerant of malformed input; if it finds nothing it falls back to a
 * generic byte tweak. Nothing here ever reads or writes out of [0, max_size).
 */
#include "sofab_mutator.h"

#include <string.h>

/* --- wire grammar constants (CORELIB_PLAN §4.3 / §4.7) ------------------------
 * Field header = varint (id << 3) | wire_type; wire_type in the low 3 bits. */
enum { WT_UNSIGNED = 0, WT_SIGNED = 1, WT_FIXLEN = 2, WT_ARR_U = 3,
       WT_ARR_S = 4, WT_ARR_FIX = 5, WT_SEQ_BEGIN = 6, WT_SEQ_END = 7 };
/* Fixlen length-header = varint (len << 3) | subtype; subtype in the low 3 bits. */
enum { FL_FP32 = 0, FL_FP64 = 1, FL_STRING = 2, FL_BLOB = 3 };

#define CAP 256          /* max recorded sites of each kind */
#define VARINT_MAX_BYTES 10

/* --- deterministic PRNG (xorshift32) ---------------------------------------- */
static uint32_t xs32(uint32_t *s)
{
    uint32_t x = *s ? *s : 0x9e3779b9u; /* never latch at 0 */
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return (*s = x);
}
static size_t rnd(uint32_t *s, size_t n) { return n ? (xs32(s) % n) : 0; }

/* Read the varint at data[off..size). Returns the number of bytes it occupies
 * (>=1 once a byte is present), sets *val to the decoded value (low 64 bits) and
 * *complete to 1 iff a terminating byte was seen within `size`. Returns 0 only
 * when off >= size. Caps at VARINT_MAX_BYTES so an overlong varint still ends. */
static size_t vread(const uint8_t *d, size_t off, size_t size,
                    uint64_t *val, int *complete)
{
    uint64_t v = 0; int shift = 0; size_t i = off, n = 0;
    while (i < size) {
        uint8_t b = d[i++]; n++;
        if (shift < 64) v |= (uint64_t)(b & 0x7f) << shift;
        if (!(b & 0x80)) { if (val) *val = v; if (complete) *complete = 1; return n; }
        shift += 7;
        if (n >= VARINT_MAX_BYTES) { if (val) *val = v; if (complete) *complete = 1; return n; }
    }
    if (val) *val = v;
    if (complete) *complete = 0;
    return n; /* n==0 iff off>=size (input exhausted) */
}

/* --- recorded sites --------------------------------------------------------- */
typedef struct {
    size_t hdr[CAP];        int nhdr;   /* field-header offsets */
    size_t voff[CAP], vlen[CAP]; int nv; /* every varint (offset + span) */
    size_t fl[CAP];         int nfl;   /* fixlen length-header offsets */
    size_t ac[CAP];         int nac;   /* array count offsets */
    struct { size_t off, len; int sub; } pl[CAP]; int npl; /* fixlen payloads */
} sites_t;

static void rec_v(sites_t *s, size_t off, size_t len)
{ if (s->nv < CAP) { s->voff[s->nv] = off; s->vlen[s->nv] = len; s->nv++; } }

/* Best-effort forward walk. Records sites; bounded by a guard and by always
 * advancing `p` or breaking. Sequence markers just continue the flat walk. */
static void walk(const uint8_t *d, size_t size, sites_t *s)
{
    memset(s, 0, sizeof *s);
    size_t p = 0; unsigned guard = 0;
    while (p < size && guard++ < 200000u) {
        int comp; uint64_t hv;
        size_t hn = vread(d, p, size, &hv, &comp);
        if (hn == 0) break;
        if (s->nhdr < CAP) s->hdr[s->nhdr++] = p;
        rec_v(s, p, hn);
        if (!comp) break;                 /* header truncated at EOF */
        int type = (int)(hv & 7);
        p += hn;

        if (type == WT_UNSIGNED || type == WT_SIGNED) {
            if (p < size) {
                int c2; size_t vn = vread(d, p, size, NULL, &c2);
                if (vn == 0) break;
                rec_v(s, p, vn); p += vn;
                if (!c2) break;
            }
        } else if (type == WT_FIXLEN) {
            if (p >= size) break;
            int c2; uint64_t lh; size_t ln = vread(d, p, size, &lh, &c2);
            if (ln == 0) break;
            rec_v(s, p, ln); if (s->nfl < CAP) s->fl[s->nfl++] = p;
            p += ln; if (!c2) break;
            uint64_t len = lh >> 3; int sub = (int)(lh & 7);
            size_t avail = size - p;
            size_t take = (len < avail) ? (size_t)len : avail;
            if (take > 0 && s->npl < CAP) { s->pl[s->npl].off = p; s->pl[s->npl].len = take; s->pl[s->npl].sub = sub; s->npl++; }
            p += take; if (take < len) break;
        } else if (type == WT_ARR_U || type == WT_ARR_S) {
            if (p >= size) break;
            int c2; uint64_t cv; size_t cn = vread(d, p, size, &cv, &c2);
            if (cn == 0) break;
            rec_v(s, p, cn); if (s->nac < CAP) s->ac[s->nac++] = p;
            p += cn; if (!c2) break;
            uint64_t k = 0;
            while (k < cv && p < size) {
                int c3; size_t en = vread(d, p, size, NULL, &c3);
                if (en == 0) { p = size; break; }
                rec_v(s, p, en); p += en; if (!c3) { p = size; break; }
                k++;
            }
        } else if (type == WT_ARR_FIX) {
            if (p >= size) break;
            int c2; uint64_t cv; size_t cn = vread(d, p, size, &cv, &c2);
            if (cn == 0) break;
            rec_v(s, p, cn); if (s->nac < CAP) s->ac[s->nac++] = p;
            p += cn; if (!c2) break;
            if (p >= size) break;
            int c3; uint64_t fw; size_t fn = vread(d, p, size, &fw, &c3);
            if (fn == 0) break;
            rec_v(s, p, fn); if (s->nfl < CAP) s->fl[s->nfl++] = p;
            p += fn; if (!c3) break;
            uint64_t width = fw >> 3; int sub = (int)(fw & 7);
            size_t avail = size - p;
            /* cv*width without overflow: bound by avail (which is <= size). */
            size_t take;
            if (width == 0) take = 0;
            else if (cv > (uint64_t)(avail / width)) take = avail;
            else { uint64_t total = cv * width; take = (total < avail) ? (size_t)total : avail; }
            if (take > 0 && s->npl < CAP) { s->pl[s->npl].off = p; s->pl[s->npl].len = take; s->pl[s->npl].sub = sub; s->npl++; }
            p += take;
        }
        /* WT_SEQ_BEGIN / WT_SEQ_END: nothing extra; children follow flatly. */
    }
}

/* --- helpers that change buffer size (bounds-checked) ----------------------- */
static size_t ins_bytes(uint8_t *d, size_t size, size_t max_size,
                        size_t at, const uint8_t *src, size_t n, uint8_t fill)
{
    if (at > size) at = size;
    if (size + n > max_size) n = max_size - size;      /* clamp to capacity */
    if (n == 0) return size;
    memmove(d + at + n, d + at, size - at);
    if (src) memcpy(d + at, src, n); else memset(d + at, fill, n);
    return size + n;
}

/* Fill a varint span [off, off+len) with the maximum value it can hold:
 * all-continuation 0xff bytes, terminator 0x7f. Same span length, in place. */
static void vmaxout(uint8_t *d, size_t off, size_t len)
{
    for (size_t j = 0; j + 1 < len; j++) d[off + j] = 0xff;
    if (len) d[off + len - 1] = 0x7f;
}

/* --- the mutator ------------------------------------------------------------ */
size_t sofab_grammar_mutate(uint8_t *data, size_t size, size_t max_size,
                            uint32_t *rng)
{
    if (max_size == 0) return 0;
    if (size > max_size) size = max_size;

    sites_t s; walk(data, size, &s);

    /* Build the menu of operators applicable to what the walk found. */
    enum { OP_TRUNC, OP_EXTEND, OP_FLIP, OP_MAXV, OP_TYPE, OP_ID,
           OP_FLEN, OP_ACOUNT, OP_SEQOPEN, OP_SEQEND, OP_UTF8, OP_FPSPEC,
           OP_DUP, OP_BYTE };
    int menu[32]; int m = 0;
    if (s.nv)              menu[m++] = OP_TRUNC;
    if (s.nv && size < max_size) menu[m++] = OP_EXTEND;
    if (s.nv)              menu[m++] = OP_FLIP;
    if (s.nv)              menu[m++] = OP_MAXV;
    if (s.nhdr)            menu[m++] = OP_TYPE;
    if (s.nhdr)            menu[m++] = OP_ID;
    if (s.nfl)             menu[m++] = OP_FLEN;
    if (s.nac)             menu[m++] = OP_ACOUNT;
    if (size < max_size)   menu[m++] = OP_SEQOPEN;
    if (size < max_size)   menu[m++] = OP_SEQEND;
    if (s.npl)             menu[m++] = OP_UTF8;   /* only strings actually mutate */
    if (s.npl)             menu[m++] = OP_FPSPEC;
    if (s.nhdr && size < max_size) menu[m++] = OP_DUP;
    menu[m++] = OP_BYTE;   /* always available (bootstrap / fallback) */

    int op = menu[rnd(rng, (size_t)m)];

    switch (op) {
    case OP_TRUNC: {
        int i = (int)rnd(rng, (size_t)s.nv);
        size_t end = s.voff[i] + s.vlen[i];
        if (end <= size && s.vlen[i]) {
            data[end - 1] |= 0x80;    /* claim "more bytes follow" ... */
            return end;               /* ... then cut: dangling varint at EOF (§7) */
        }
        return size;
    }
    case OP_EXTEND: {                 /* overlong a varint -> > 64 bits -> INVALID */
        int i = (int)rnd(rng, (size_t)s.nv);
        size_t e = 1 + rnd(rng, 12);
        return ins_bytes(data, size, max_size, s.voff[i], NULL, e, 0x80);
    }
    case OP_FLIP: {                   /* flip a continuation bit somewhere in a varint */
        int i = (int)rnd(rng, (size_t)s.nv);
        if (s.vlen[i]) data[s.voff[i] + rnd(rng, s.vlen[i])] ^= 0x80;
        return size;
    }
    case OP_MAXV: {
        int i = (int)rnd(rng, (size_t)s.nv);
        if (s.voff[i] + s.vlen[i] <= size) vmaxout(data, s.voff[i], s.vlen[i]);
        return size;
    }
    case OP_TYPE: {                   /* rewrite a field's 3-bit wire type */
        int i = (int)rnd(rng, (size_t)s.nhdr);
        data[s.hdr[i]] = (uint8_t)((data[s.hdr[i]] & ~0x07) | (xs32(rng) & 0x07));
        return size;
    }
    case OP_ID: {                     /* perturb a field id (bits above the type) */
        int i = (int)rnd(rng, (size_t)s.nhdr);
        data[s.hdr[i]] ^= (uint8_t)(1u << (3 + (xs32(rng) & 3)));
        return size;
    }
    case OP_FLEN: {                   /* change a fixlen declared length, keep subtype */
        int i = (int)rnd(rng, (size_t)s.nfl);
        data[s.fl[i]] ^= (uint8_t)(1u << (3 + (xs32(rng) & 3)));
        return size;
    }
    case OP_ACOUNT: {                 /* claim a huge array count */
        int i = (int)rnd(rng, (size_t)s.nac);
        /* find this count's span length via a fresh read (bounded) */
        int c; size_t cn = vread(data, s.ac[i], size, NULL, &c);
        if (cn) vmaxout(data, s.ac[i], cn);
        return size;
    }
    case OP_SEQOPEN: { uint8_t b = (WT_SEQ_BEGIN); return ins_bytes(data, size, max_size, size, &b, 1, 0); }
    case OP_SEQEND:  { uint8_t b = (WT_SEQ_END);   return ins_bytes(data, size, max_size, size, &b, 1, 0); }
    case OP_UTF8: {                   /* invalid UTF-8 into a string payload (§8) */
        /* pick a string payload; if none, no-op */
        int idx = -1, tries = 0;
        while (tries++ < s.npl) { int j = (int)rnd(rng, (size_t)s.npl); if (s.pl[j].sub == FL_STRING) { idx = j; break; } }
        if (idx >= 0 && s.pl[idx].len)
            data[s.pl[idx].off + rnd(rng, s.pl[idx].len)] = 0xff;
        return size;
    }
    case OP_FPSPEC: {                 /* NaN/inf-ish bytes into an fp payload */
        int idx = -1, tries = 0;
        while (tries++ < s.npl) { int j = (int)rnd(rng, (size_t)s.npl); if (s.pl[j].sub == FL_FP32 || s.pl[j].sub == FL_FP64) { idx = j; break; } }
        if (idx >= 0 && s.pl[idx].len) {
            size_t o = s.pl[idx].off, l = s.pl[idx].len;
            memset(data + o, 0xff, l);            /* all-ones: a quiet NaN pattern */
            data[o + l - 1] = (xs32(rng) & 1) ? 0x7f : 0xff; /* +NaN / -NaN top byte */
        }
        return size;
    }
    case OP_DUP: {                    /* duplicate a field's bytes (id reorder/skip paths) */
        int i = (int)rnd(rng, (size_t)s.nhdr);
        size_t a = s.hdr[i];
        size_t b = (i + 1 < s.nhdr) ? s.hdr[i + 1] : size;
        if (b > a && b <= size) {
            size_t span = b - a;
            if (span > max_size - size) span = max_size - size;
            if (span) { memmove(data + b + span, data + b, size - b); memcpy(data + b, data + a, span); return size + span; }
        }
        return size;
    }
    case OP_BYTE:
    default: {                        /* generic tweak / bootstrap for empty input */
        if (size == 0) {
            uint8_t seed[2] = { (uint8_t)((10u << 3) | WT_SEQ_BEGIN), WT_SEQ_END };
            return ins_bytes(data, 0, max_size, 0, seed, 2, 0);
        }
        data[rnd(rng, size)] ^= (uint8_t)(1u << (xs32(rng) & 7));
        return size;
    }
    }
}
