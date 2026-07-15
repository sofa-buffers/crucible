/*
 * Standalone soak test for the structure-aware mutator. Builds without libFuzzer
 * (gcc/clang + ASan/UBSan) so a bare workspace can verify the safety and
 * determinism contract from sofab_mutator.h:
 *   - never reads/writes out of [0, max_size)  (ASan/UBSan enforce);
 *   - deterministic in the rng seed;
 *   - respects max_size;
 *   - and actually produces the target shapes (truncated varint, invalid UTF-8).
 *
 * Build:  cc -std=c11 -fsanitize=address,undefined -I engine/mutator \
 *            engine/mutator/test_mutator.c engine/mutator/sofab_mutator.c -o /tmp/mut_test
 * Run:    /tmp/mut_test
 */
#include "sofab_mutator.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static size_t unhex(const char *h, uint8_t *out)
{
    size_t n = 0;
    for (; h[0] && h[1]; h += 2) {
        unsigned b; sscanf(h, "%2x", &b); out[n++] = (uint8_t)b;
    }
    return n;
}

/* Seeds: empty, a valid-ish full-scale message, and the finding reproducers. */
static const char *SEEDS[] = {
    "",
    "002a090d12200000c03f1a126869",                 /* 02_basic-ish */
    "5607a606560707c60c07",                         /* all-defaults re-encoding */
    "56121a41ff4207a606560707c60c07",               /* F-0004 invalid utf8 */
    "a6060308010203040506070807",                   /* over-count array */
    "560a59",                                        /* F-0006 fp64 wrong len */
    "80",                                            /* F-0001 dangling varint */
};

int main(void)
{
    const size_t MAXSZ = 2048;
    uint8_t *a = malloc(MAXSZ), *b = malloc(MAXSZ);
    int iters = 0, over = 0;
    long trunc_varint = 0, has_ff = 0, grew = 0, shrank = 0;

    for (size_t si = 0; si < sizeof(SEEDS)/sizeof(SEEDS[0]); si++) {
        uint8_t seedbuf[512];
        size_t seedn = unhex(SEEDS[si], seedbuf);

        /* Determinism: same seed + same rng => byte-identical output. */
        {
            memcpy(a, seedbuf, seedn); memcpy(b, seedbuf, seedn);
            uint32_t r1 = 0x1234567u, r2 = 0x1234567u;
            size_t n1 = sofab_grammar_mutate(a, seedn, MAXSZ, &r1);
            size_t n2 = sofab_grammar_mutate(b, seedn, MAXSZ, &r2);
            if (n1 != n2 || memcmp(a, b, n1) != 0) {
                fprintf(stderr, "NON-DETERMINISTIC on seed %zu\n", si);
                return 1;
            }
        }

        /* Soak: iterative mutation, many rng seeds, feeding output back in. */
        for (uint32_t seed = 1; seed <= 4000; seed++) {
            memcpy(a, seedbuf, seedn);
            size_t n = seedn;
            uint32_t rng = seed * 2654435761u + 1u;
            for (int step = 0; step < 12; step++) {
                size_t before = n;
                n = sofab_grammar_mutate(a, n, MAXSZ, &rng);
                iters++;
                if (n > MAXSZ) { over++; }
                if (n > before) grew++; else if (n < before) shrank++;
            }
            if (n && (a[n - 1] & 0x80)) trunc_varint++;   /* ends mid-varint (§7) */
            for (size_t k = 0; k < n; k++) if (a[k] == 0xff) { has_ff++; break; }
        }
    }

    printf("iters=%d  over_max=%d  grew=%ld shrank=%ld\n", iters, over, grew, shrank);
    printf("outputs ending in a truncated varint: %ld\n", trunc_varint);
    printf("outputs containing an 0xff byte:       %ld\n", has_ff);

    if (over) { fprintf(stderr, "FAIL: exceeded max_size %d time(s)\n", over); return 1; }
    if (trunc_varint == 0) { fprintf(stderr, "FAIL: never produced a truncated varint\n"); return 1; }
    if (has_ff == 0) { fprintf(stderr, "FAIL: never produced an 0xff byte\n"); return 1; }
    free(a); free(b);
    printf("OK: safe, deterministic, and produces the target shapes\n");
    return 0;
}
