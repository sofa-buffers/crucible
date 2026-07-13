/*
 * Crucible C driver — the coverage PACEMAKER for the SofaBuffers differential
 * fuzzer.
 *
 * One decode core, two front-ends:
 *   - default build (gcc/clang): persistent replay driver speaking the protocol
 *     in drivers/common/CONTRACT.md — reads length-prefixed inputs on stdin,
 *     emits one canonical line each on stdout.
 *   - -DCRUCIBLE_LIBFUZZER (clang -fsanitize=fuzzer): LLVMFuzzerTestOneInput,
 *     the coverage-guided pacemaker; exercises the same core, no stdout.
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
        case SOFAB_RET_E_USAGE:       return "usage";
        case SOFAB_RET_E_BUFFER_FULL: return "buffer_full";
        default:                      return "other";
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
        sofab_ret_t r = message_probe_decode(&m, buf, len);
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

    /* Accept: re-encode the decoded value and emit its canonical wire as hex. */
    uint8_t enc[MESSAGE_PROBE_MAX_SIZE];
    size_t used = 0;
    sofab_ret_t er = message_probe_encode(&m, enc, sizeof(enc), &used);
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
/* Coverage pacemaker front-end. Exercise the decode core; sanitizers catch
 * memory faults, the differential path catches disagreement. No output. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    message_probe_t m;
    message_probe_init(&m);
    if (size > 0) (void)message_probe_decode(&m, data, size); /* see decode_and_report */
    return 0;
}
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
