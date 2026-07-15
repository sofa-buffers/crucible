/*
 * Crucible structure-aware mutator for the SofaBuffers wire format.
 *
 * A grammar-aware libFuzzer custom mutator (TODO.md Phase 3 #1, design in
 * engine/mutator/DESIGN.md, wire grammar in docs/PLAN.md §5 / CORELIB_PLAN §4).
 * libFuzzer's byte-level mutator corrupts an early header/length byte and gets
 * rejected in the first parse step, so deep paths (nested sequences, array
 * counts, varint boundaries, MAX_DEPTH) are reached only by luck. This mutator
 * edits the wire at the *field* level so it stays parseable-ish and drives the
 * decoder into those paths on purpose.
 *
 * Pure and libFuzzer-independent so it can be unit-tested standalone
 * (engine/mutator/test_mutator.c). drivers/c/driver.c's LLVMFuzzerCustomMutator
 * seeds the PRNG, mixes in LLVMFuzzerMutate ~40% of the time, and calls this for
 * the rest.
 *
 * Contract (DESIGN.md "Hook"):
 *   - deterministic in `*rng_state` (xorshift seed) — never rand()/time;
 *   - never grows past `max_size`; returns the new size (<= max_size);
 *   - never reads/writes out of bounds on malformed `data` (it mutates
 *     already-broken inputs) — verified under ASan by test_mutator.c.
 */
#ifndef CRUCIBLE_SOFAB_MUTATOR_H
#define CRUCIBLE_SOFAB_MUTATOR_H

#include <stddef.h>
#include <stdint.h>

/*
 * Mutate `data` (of `size` bytes, capacity `max_size`) in place, grammar-aware.
 * Advances `*rng_state` (xorshift32; seed it non-zero). Returns the new size,
 * always in [0, max_size]. Safe on any bytes, including empty/malformed input.
 */
size_t sofab_grammar_mutate(uint8_t *data, size_t size, size_t max_size,
                            uint32_t *rng_state);

#endif /* CRUCIBLE_SOFAB_MUTATOR_H */
