# G-0041 — the Dart backend still emits a `status` accessor beside `feed`, the one backend the IStream contract never reached (§5.2.1)

**Status:** ✅ **fixed in sofabgen `e243e25c`** — [generator#555](https://github.com/sofa-buffers/generator/issues/555), verified 2026-09-18; [`results/FINDINGS.md`](../../results/FINDINGS.md) owns this finding's status and its resolution trail, this file is the evidence.
**Guard:** none — a surface defect has no input that exposes it. The differential and materialized oracles are both structurally blind to it (an extra accessor produces no bytes); it is caught by reading generated code, and upstream by a backend test of the kind `TestTSClosedNameSet` already is for G-0040.
**Issue:** [generator#555](https://github.com/sofa-buffers/generator/issues/555)

**Found 2026-09-18** while catching the replay drivers up to sofabgen
`0.0.0-20260918072500-d865b921`. Five drivers — java, kotlin, zig, typescript, csharp — had
to stop reading a `status` accessor that the generated decoder no longer has. The dart
driver was the only one that still compiled, and that asymmetry is the finding.

## What the backend emits

`generators/dart/backend.go`:

```go
918   f.line("  sofab.DecodeStatus _st = sofab.DecodeStatus.complete;")
924   f.line("    _st = _d.feed(chunk);")
929   f.line("  sofab.DecodeStatus get status => _st;")
```

producing (`tests/matrix/testdata/golden/dart/message.dart:163-183`, and the same in our
`drivers/dart/build/message.dart:736-747`):

```dart
sofab.DecodeStatus _st = sofab.DecodeStatus.complete;

sofab.DecodeStatus feed(List<int> chunk) {
  _st = _d.feed(chunk);
  return status;
}

/// The outcome for everything fed so far, without feeding more.
sofab.DecodeStatus get status => _st;
```

`feed` already returns the outcome; `_st` is a second copy of it.

## Established across the family, not inferred

The same schema generated with the same sofabgen build, for every backend:

| backend | `status` accessor on the generated decoder |
|---|---|
| c, cpp, go, rust, python, typescript, java, kotlin, csharp, zig | — |
| **dart** | `message.dart:174` — `sofab.DecodeStatus get status => _st;` |

## The clause

`CORELIB_PLAN.md:716-719` (documentation `main@382159e`, read at the tip), §5.2.1
*How an outcome is delivered (normative)*:

> **No second place to ask.** A `status()` accessor beside `feed`, **or any other surface
> holding a copy of the outcome**, is not a conformant way to deliver one. Two answers to
> the same question can disagree, and the outcome **MUST** reach the caller from the `feed`
> that produced it.

The obvious counter — *"§5.2.1 binds the corelib, not the generated layer"* — does not
survive three facts: MESSAGE_SPEC §7 obliges generated code to return the corelib's status
**verbatim**; the clause says *any other surface*, and `_st` is literally a copy; and ten of
eleven backends already emit none, so the generator has itself read the clause as binding
here.

## Attribution — codegen, established by reading both sides

**The generator.** `corelib-dart` exposes no such accessor (`grep -rn "get status" lib/`: no
matches) and latches the terminal verdict at the top of `feed`
(`lib/src/decoder.dart:795,858,863,866` — `_terminal` / `_terminalStatus`, checked before a
byte is read). That is exactly generator#541's own argument — *"every one of the six
corelibs already latches both refusal kinds itself"* — applied to dart. The corelib is
conformant; the extra door is added by generated code alone.

## Why dart was missed

Not a line dropped from a sweep. `4f0076c1` (generator#541) deleted the remembered status
from **six** backends and says so: *"the remembered `status` #461/#521 added to the six
exception-shaped backends"*. Its predecessor `0a9457c9` (#463, *"fix(all)!: adopt the new
IStream contract — feed is the only answer"*) touched csharp, java, python, rust, typescript
and zig despite the `(all)`. `generators/dart/backend.go` has never been touched by IStream
contract work at all. Dart's accessor predates the arc.

## What does not apply, stated so it is not assumed

#541's *behavioural* complaint — the remembered status *"flattened LimitExceeded into an
INCOMPLETE that says something untrue about the wire"* — **does not reproduce on dart**.
`corelib-dart`'s `DecodeStatus` is four-valued (`complete, incomplete, invalid,
limitExceeded`, `lib/src/wire.dart:103-118`), so `_st` carries a cap refusal faithfully. The
case here is §5.2.1 plus family consistency, not a wrong verdict.

## Why it is not a deletion

`finish()` is implemented **through** the accessor and its doc comment sends the caller
there:

```dart
/// Returns null if the stream ended mid-field or was rejected, so a
/// half-filled value is never mistaken for a whole one; read [status] for
/// which it was, or [message] to get it anyway.
Probe? finish() => status == sofab.DecodeStatus.complete ? _out : null;
```

Removing `status` alone leaves a caller unable to tell "ended mid-field" from "rejected".
Dart needs the restructuring the six got — `finish()` asks the stream with a zero-length
feed — adapted to its non-throwing shape.

## Resolution (verified 2026-09-18)

`e243e25c`, *"refactor(dart): the generated decoder asks the stream instead of remembering a
status (#555)"* — landed 12:15, the same day the issue was filed. It is the restructuring
this write-up said the fix would need, not a deletion: the `_st` field is gone, `feed` is a
plain forward, and `finish()` re-asks the stream with a zero-length feed, which is exactly
what #541 gave the six exception-shaped backends, adapted to dart's non-throwing shape.

```dart
sofab.DecodeStatus feed(List<int> chunk) => _d.feed(chunk);

Probe get message => _out;

/// … the outcome [feed] returned says which it was, or read [message] to get it anyway.
Probe? finish() =>
    _d.feed(const <int>[]) == sofab.DecodeStatus.complete ? _out : null;
```

The doc comment moved with it — it no longer sends the caller to an accessor, it sends them
to what `feed` returned. Checked by regenerating `schema/probe.sofab.yaml` for **all eleven**
backends at `e243e25c`: no `status` accessor anywhere, dart included.

## Crucible's side

`drivers/dart/driver.dart` read `d.status` and was the last of the eleven chunked-capable
drivers doing so; it now keeps what the last `feed` returned, initialised to `complete` so a
zero-length record — which feeds nothing — still answers for the valid empty message. Same
shape as the five drivers that made this move on the previous sofabgen build.
