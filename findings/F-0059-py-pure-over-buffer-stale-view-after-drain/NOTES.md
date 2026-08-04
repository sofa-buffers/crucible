# F-0059 — corelib-py's pure engine writes into the drained buffer after a flush, so everything past the first flush is lost

**Status:** 🔴 **OPEN** — filed against corelib-py ([`results/FINDINGS.md`](../../results/FINDINGS.md)
owns this finding's state; this file is the evidence).

**Found 2026-08-04**, on the first run of the **streaming-encode axis**
([crucible#132](https://github.com/sofa-buffers/crucible/issues/132)). Invisible to every other
gate here by construction: they all re-encode with one call into an unbounded buffer, so no flush
ever happens mid-message.

It is also an **engine-parity** break — the two engines of the *same* corelib disagree, which is
the one thing corelib-py's own tests are built to prevent.

## The reproducer — nine lines, corelib-py only

No sofabgen, no generated code, no Crucible harness (`repro_over_buffer_cap1.py`):

```python
from sofab import Encoder
acc = bytearray(); enc = None
def sink(chunk):
    acc.extend(chunk)
    enc.buffer_set(bytearray(1))          # hand back a fresh 1-byte buffer
enc = Encoder.over_buffer(bytearray(1), 0, sink)
enc.write_unsigned(0, 1)                  # field id 0, value 1  ->  00 01
enc.flush()
```

| engine | `over_buffer(1)` | in-memory `Encoder()` |
|---|---|---|
| Cython (`_speedups`) | `0001` | `0001` |
| **pure Python** | **`0000`** | `0001` |

The sink does exactly what the docstring on `over_buffer` asks for: *"``flush`` is expected to
drain them and (via `buffer_set`) hand back a fresh buffer so encoding continues."*

## The cause — a view captured before the drain

`Encoder._put` (`src/sofab/encoder.py`) caches the buffer view **once, before the loop**:

```python
def _put(self, data: bytes) -> None:
    if self._fixed is None:
        self._buf += data
        return
    mv = self._fixed          # <-- captured here
    cap = self._cap           # <-- and here
    pos = 0
    n = len(data)
    while pos < n:
        if self._cursor >= cap:
            self._drain()     # <-- sink runs, and calls buffer_set(...)
            ...
        take = min(cap - self._cursor, n - pos)
        mv[self._cursor : self._cursor + take] = data[pos : pos + take]   # <-- stale mv
        self._cursor += take
        pos += take
```

`_drain()` invokes the sink, the sink calls `buffer_set()`, and `buffer_set` replaces
`self._fixed` / `self._cap` / `self._cursor`. But `_put` keeps writing through **`mv`, the old,
already-drained buffer**. The new buffer is never written to, so the next drain — and the final
`flush()`, which emits `bytes(self._fixed[0 : self._cursor])` — hands out its zeroed contents.

`cap` is stale for the same reason, so a sink that hands back a *differently sized* buffer would
also mis-slice.

## Scope — every byte after the first flush

Across `corpus/structured` (108 value-rich messages) at `SOFAB_FLUSH=1`, the first byte survives
and everything after it is zeroed:

| input | correct | pure engine |
|---|---|---|
| `u8 = 1` | `0001` | `0000` |
| `u8 = 255` | `00ff01` | `000000` |
| `u16 = 65535` | `10ffff03` | `10000000` |
| `i16 = -1` | `1901` | `1900` |

Only `SOFAB_FLUSH=1` is affected in this corpus, because that is the size at which a drain lands
inside a single `_put`. A larger caller buffer with a message long enough to fill it would hit the
same path — the trigger is *a drain during one `_put`*, not the number 1.

The **decode** side is unaffected: both engines are chunk-invariant over every cut the axis
applies (311 chunkings × the seed corpus, 0 mismatches each).

## Attribution — corelib-py

`_put`, `_drain` and `buffer_set` are all corelib-py's own encoder. No schema fact is involved:
`count`, `maxlen` and the field's declared type play no part, generated code merely calls
`write_unsigned`, and the reproducer above does not use generated code at all. Under CLAUDE.md's
split this is wire mechanics on the writer side.

It is a **pure-engine-only** defect — the Cython accelerator implements `_put` separately and is
correct — which is what makes it an engine-parity break rather than a corelib-wide one.

## Suggested fix

Re-read `self._fixed` and `self._cap` after `_drain()` rather than caching them across it. Hoisting
them is a reasonable optimization for the common no-drain path, so the minimal change is to refresh
both inside the `if self._cursor >= cap:` branch, right after `_drain()` returns.

Worth a parity test that exercises `over_buffer` with a buffer small enough to force a mid-`_put`
drain: the existing tests appear to cover `over_buffer` only where the message fits.

## Effect on the Crucible gates

`py-pure` is in the encode-invariance roster and this makes that gate red, so it is held out of
`scripts/run-encode.sh`'s opt-in list while the finding is open — the same treatment `zig` has on
the chunked gate for F-0058, and for the same reason (`results/known-clusters.txt`: a gate that is
permanently red for an already-filed defect stops meaning "something new broke"). `py-cython` stays
in, and both stay in the chunked gate, which they pass. Recorded in `docs/TODO.md`.
