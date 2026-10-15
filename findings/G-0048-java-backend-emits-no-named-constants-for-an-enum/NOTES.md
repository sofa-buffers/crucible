# G-0048 — the Java backend emits no named constants for an `enum`: the field is a bare `long`

**Status:** ✅ **RESOLVED** — fixed upstream in [generator#763](https://github.com/sofa-buffers/generator/pull/763) (merged 2026-10-15, `d2f79dd1`, "feat(java): named constants beside enum and bitfield fields"). Every enum and bitfield type now gets a holder class of `long` constants beside the unchanged `long` field — a flag as its mask — and each field's javadoc points at it with `@see`. Owner: **generator** (the Java backend), not a corelib.
**Issue:** [generator#758](https://github.com/sofa-buffers/generator/issues/758) (filed 2026-10-14, closed 2026-10-15)
**Guard:** none — not wire-observable, so no Crucible gate can see it; the generator's own conformance leg `tests/conformance/java/NamedConstants.java` (added in generator#763) compiles against the constants under `-Xlint:all -Werror`, so a regression breaks the generator's CI.

**Found 2026-10-14** on branch `worktree-probe-enum-bitfield`, sofabgen
`0.0.0-20261014101647-9b68239d849a` (generator main `9b68239d849a`), documentation
`main@b6586b5`.

## The rule

MESSAGE_SPEC §1 (l.119-122 at `b6586b5`), on an `enum`:

> A target language whose native `enum` cannot hold an undeclared value (Java, Kotlin, Dart,
> Rust, a strict Python `Enum`) **MUST** materialize the field as the declared integer type
> with named constants beside it, rather than as that language's closed enum.

Java is named in the clause. Two halves: the *integer type* (so an in-width unnamed value is
representable) and the *named constants beside it* (so an application can still say
`Level.ON` instead of `1`).

## What the Java backend generates

`schema/probe.sofab.yaml` declares `Level: { MIN: -128, LOW: -3, OFF: 0, ON: 1, MAX: 127 }` and
`Code: { NEG: -1000, TWO: 2, SEVEN: 7, BIG: 300 }`. The generated Java
(`drivers/java/build/gen/src/main/java/message/`):

- `Probe.java:31` `public long level;`, `Probe.java:32` `public long code = 7L;`,
  `Probe_Nested.java:15` `public long level;`, `Probe_StructArray.java:12`
  `public long code = 7L;` — the integer half is there (and the width check is generated,
  e.g. `Probe.java:365`, `if (value < -128L || value > 127L) throw Sofab.invalid(...)`).
  Holding the field as `long` rather than `byte` is permitted: MESSAGE_SPEC §1 l.107-112
  lets a target that cannot hold an enum at exactly its width ("a Java or Kotlin constant
  set is an `int`") hold it wider and enforce the declared width as an explicit check,
  which `Probe.java:365` is. Only the named-constants half is missing.
- The constant half is missing: the package holds only `Probe*.java`; no `Level` /
  `Code` class, and no `static final` for `MIN`, `LOW`, `ON`, `NEG`, `SEVEN` anywhere
  (`grep -rn 'static final' …/message/` finds only `MAX_SIZE` and decoder internals).

The siblings in the same clause do emit them, from the same schema: Kotlin `object Level` /
`object Code` (`drivers/kotlin/build/jvm/gen/src/main/kotlin/message/Level.kt:16`), Dart
`abstract final class Level { static const int LOW = -3; … }`, Rust `pub mod Level`.
Java is the one backend named by the MUST that has none.

## Attribution: generated code

Which constants exist is a **schema** fact; the corelib never sees an enum declaration, so
only the generator can emit them. The generator documents the gap as deliberate:
generator `docs/ARCHITECTURE.md` ("Generated-code principles", l.986-988 at `9b68239d849a`):
"C's enum fields and Java's enum/bitfield fields remain the one case with no symbol at all:
they lower to a raw integer and carry only the field-level metadata above". C is not named
by the MUST (a C `enum` holds any value of its underlying type), Java is — so the C half of
that sentence is a design choice and the Java half conflicts with the spec.

A Java `bitfield` field is also a bare `long` with no per-flag constants. The bitfield
paragraph of §1 does not repeat the "named constants" clause, so that half is a
consistency point (C gained `#define`s per flag in generator#606), not a MUST.

## Why no gate sees it

Every Crucible oracle compares wire verdicts and stored values. A missing constant changes
neither: the 20-driver differential, the materialized oracle and cross-encode are all green
on the new enum positions. The draft issue carries the evidence instead of a reproducer.

## Resolution (verified 2026-10-15)

Verified with the sofabgen build of generator main `d2f79dd1`
(`0.0.0-20261015054610-d2f79dd114a4`, the `sofabgen-linux-amd64` artifact of generator CI run
38688582104, checksum verified) on Crucible's `probe` schema:

- the generated package now carries `Level.java`, `Code.java`, `Perm.java` and `Wide.java` beside
  `Probe*.java` — e.g. `public static final long MIN = -128L; … MAX = 127L;` in `Level`, and
  `R = 1L << 0`, `W = 1L << 1`, `X = 1L << 3` in `Perm`;
- each enum and bitfield field in `Probe.java` carries `/** @see Level */` (and so on);
- the fields stay `long`, so nothing on the wire changed: the Java replay driver's output over
  `corpus/{seeds,regression,conformance,structured}` (425 inputs) is identical with the old and
  the new generator — plain, `SOFAB_MATERIALIZE=1`, `SOFAB_CHUNK=1` and `SOFAB_ENCODE_FAIL=8`, 0
  changed lines.

That CI run concluded `failure`, but only through five jobs that failed in "Set up job"
(runner infrastructure: lang-typescript, lang-kotlin, lang-zig, hermetic, lang-docs); the Java
leg and the artifact build are green. Until a fully green run exists, `scripts/bootstrap.sh`
keeps installing the previous green build (`9b68239d849a`), which is harmless here: no Crucible
gate depends on the holder classes.
