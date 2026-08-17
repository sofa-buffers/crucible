#!/usr/bin/env python3
"""Static canonicality audit of Crucible's committed corpora — a HAND-RUN tool.

WHAT IT IS FOR
    Every other check here asks whether the implementations agree with each other. That
    question has a blind spot: the test files are produced by our own encoder (gen.py),
    and if that encoder writes a file in a form the spec forbids, every implementation
    reads it, they all agree, and the gate is green — while the rule the file was meant
    to exercise went untested.

    This audit re-derives the properties FROM THE BYTES, without asking gen.py. That is
    the only way to catch a reference encoder that is itself wrong. It was written on
    2026-07-28 during the documentation#31 array-rule change, and it found the
    contradiction that change exposed in the committed corpora.

    The value reference (materialize.py) already covers every encoder mistake that
    changes the VALUE. What is left, and what this checks, is the class "right value,
    wrong bytes" — a file that carries the intended value in a form that should never
    have been written.

WHAT IT CHECKS — 4 rules, all from the omission family
    P1  no all-default (childless) sequence at a struct/union FIELD position
        -> MESSAGE_SPEC §2: such a field is omitted; a conformant encoder never emits
           the frame
    P2  no empty union frame at all (49b710b: the degenerate union is omitted)
    P3  no empty wrapper frame unless the field's declared default is non-empty
        (probe declares none, so: no empty wrapper at all)
    P4  no all-default element in a wrapper's INTERIOR -> documentation#31: the interior
        is sparse, such an element must be an id gap. (At the LAST index it is required
        instead — it carries the length — so P4 deliberately exempts the highest id.)

WHAT IT DOES NOT CHECK — the other 6 statically checkable rules
    the array length against the bytes actually present; over-`maxlen` strings/blobs;
    values over their declared width; UTF-8 validity; minimal (non-overlong) varints;
    ascending field ids.

    So it covers 4 of the 10 rules that a finished file can be checked against — call it
    40%. The six above are the same kind of local byte property and would each cost
    under an hour, but nobody has written them.

    One further rule is NOT statically checkable at all: that a wrapper's LAST element
    is present. The highest id on the wire is the last index by construction, so it can
    only be wrong relative to the intended value, which the byte stream does not carry.

WHY IT IS NOT A CI GATE (decided 2026-08-16)
    Two reasons, and the second is the stronger one.

    1. At 40% coverage a gate would read as "the test files are verified" while
       verifying the omission family only. An over-promising check is worse than none.

    2. IT HAS NO EXECUTABLE SELF-TEST. Its negative controls are files in
       corpus/conformance — two deliberately malformed (which it must report) and six
       correct (which it must not) — and that it reports exactly those two was checked
       once, by a human, in July. A gate over the canonical corpora would never touch
       those files, so a version of this script that silently stopped reporting anything
       would stay green forever. That is precisely the failure mode the audit exists to
       prevent, reproduced one level up.

    Its place is therefore where it earned it: run by hand when the spec moves, which is
    the situation it was built for. Before it could ever be gated it needs the self-test
    above, and preferably the six missing rules.

    STATUS: this is a decision, not an oversight, and docs/TODO.md carries it as closed
    pointing back here rather than restating it — one owner per fact. If you are reading
    this because you want to gate it after all, the two paragraphs above are the entry
    price, in that order: the self-test first, because without it a gate that silently
    stopped reporting would stay green forever, which is the failure this file exists to
    prevent.

    Also note it carries its own hand-written copy of the probe field layout below,
    while `oracle/materialized-schema.json` holds the same thing machine-generated and
    freshness-checked. A gate would have to read that instead; a hand-run tool can live
    with the copy as long as the reader knows it is one.

INTERPRETING THE OUTPUT
    Only `corpus/structured` and `corpus/structured-union` are meant to be canonical
    throughout — a hit there is unambiguous. `corpus/seeds`, `corpus/conformance` and
    `corpus/regression` deliberately carry malformed, truncated and non-canonical inputs,
    so they light up by design and a hit there means nothing on its own.

Usage: python3 engine/structured/audit_canonical.py    (from the repo root)
"""
import os, sys, glob

# ---- probe schema model (schema/probe.sofab.yaml) ---------------------------
# kind: 'struct' | 'wrapper_leaf' | 'wrapper_seq' | leaf
PROBE = {
    0:"leaf",1:"leaf",2:"leaf",3:"leaf",4:"leaf",5:"leaf",6:"leaf",7:"leaf",
    10:  ("struct", {0:"leaf",1:"leaf",2:"leaf",3:"leaf"}),
    100: ("struct", {0:"leaf",1:"leaf",2:"leaf",3:"leaf",4:"leaf",5:"leaf",6:"leaf",7:"leaf",
                     10:("struct", {0:"leaf",1:"leaf"})}),
    200: ("wrapper_leaf", None),
    201: ("wrapper_leaf", None),
    202: ("wrapper_seq", {0:"leaf",1:"leaf"}),
}
UNION = {0:"leaf", 1:("union", {0:"leaf",1:"leaf",2:"leaf",3:"leaf"}), 2:"leaf"}

WT_U,WT_S,WT_FIX,WT_ARR_U,WT_ARR_S,WT_ARR_FIX,WT_SEQ_BEG,WT_SEQ_END = range(8)

def rd(b,i):
    v=s=0
    while True:
        if i>=len(b): raise EOFError("varint past EOF")
        x=b[i]; v|=(x&0x7f)<<s; i+=1; s+=7
        if not x&0x80: break
    return v,i

def parse(b, i, model, path, out):
    """Parse one scope; returns (i, n_children). Appends (path, kind, empty?) findings."""
    n = 0
    while i < len(b):
        v,i = rd(b,i)
        wt, fid = v&7, v>>3
        if wt == WT_SEQ_END:
            return i, n, True
        n += 1
        node = model.get(fid) if isinstance(model, dict) else None
        if wt == WT_SEQ_BEG:
            sub = node[1] if isinstance(node, tuple) else None
            kind = node[0] if isinstance(node, tuple) else "unknown"
            if kind == "wrapper_seq":
                # elements: each id is an index, each element a sequence
                i, cnt, closed = parse_elements(b, i, sub, path+[fid], out)
                out.append((path+[fid], "wrapper_seq", cnt))
            elif kind == "wrapper_leaf":
                i, cnt, closed = parse(b, i, {}, path+[fid], out)
                out.append((path+[fid], "wrapper_leaf", cnt))
            else:
                i, cnt, closed = parse(b, i, sub or {}, path+[fid], out)
                out.append((path+[fid], kind, cnt))
        elif wt == WT_FIX:
            w,i = rd(b,i); i += w>>3
        elif wt in (WT_U, WT_S):
            _,i = rd(b,i)
        elif wt in (WT_ARR_U, WT_ARR_S):
            c,i = rd(b,i)
            for _ in range(c): _,i = rd(b,i)
        elif wt == WT_ARR_FIX:
            c,i = rd(b,i); w,i = rd(b,i); i += c*(w>>3)
    return i, n, False

def parse_elements(b, i, elem_model, path, out):
    """A wrapper whose elements are sequences: record each element's child count."""
    n = 0; last_empty = None; empties = []
    max_id = [-1]
    def _finish():
        """Re-tag every all-default element except the one at the array's HIGHEST id:
        that one carries the length (§2) and is required; the others must be gaps.
        `max_id` is the highest id of ANY element — comparing against the highest
        *empty* id would exempt an interior empty whenever no later element is empty."""
        for idx, f in empties:
            if f != max_id[0]:
                out[idx] = (out[idx][0], "interior_empty_elem", 0)
    while i < len(b):
        v,i = rd(b,i)
        wt, fid = v&7, v>>3
        if wt == WT_SEQ_END:
            _finish()
            return i, n, True
        n += 1
        max_id[0] = max(max_id[0], fid)
        if wt == WT_SEQ_BEG:
            i, cnt, _ = parse(b, i, elem_model or {}, path+[fid], out)
            out.append((path+[fid], "seq_elem", cnt))
            if cnt == 0:
                empties.append((len(out) - 1, fid))
            last_empty = None
        elif wt == WT_FIX:
            w,i = rd(b,i); i += w>>3; last_empty = None
        elif wt in (WT_U,WT_S):
            _,i = rd(b,i); last_empty = None
        else:
            raise ValueError(f"unexpected wt {wt} at element position {path}")
    _finish()
    return i, n, False

def audit(path_bin, model, label):
    b = open(path_bin,'rb').read()
    out = []
    try:
        parse(b, 0, model, [], out)
    except (EOFError, ValueError, IndexError) as e:
        return [f"PARSE {os.path.basename(path_bin)}: {e}"]
    probs = []
    for p, kind, cnt in out:
        loc = ".".join(map(str,p))
        if cnt == 0:
            if kind == "seq_elem":
                continue                          # last-index empty element: required
            if kind == "struct":
                probs.append(f"P1 empty STRUCT frame at id {loc}")
            elif kind == "union":
                probs.append(f"P2 empty UNION frame at id {loc}")
            elif kind in ("wrapper_leaf","wrapper_seq"):
                probs.append(f"P3 empty WRAPPER frame at id {loc} (no non-empty declared default in probe)")
        if kind == "interior_empty_elem":
            probs.append(f"P4 all-default ELEMENT in the interior at {loc} (must be an id gap)")
    return probs

def main():
    total = bad = 0
    for corpus, model, label in [("corpus/structured", PROBE, "probe"),
                                 ("corpus/conformance", PROBE, "probe"),
                                 ("corpus/seeds", PROBE, "probe"),
                                 ("corpus/regression", PROBE, "probe"),
                                 ("corpus/structured-union", UNION, "union")]:
        files = sorted(glob.glob(f"{corpus}/*.bin"))
        n_bad = 0
        for f in files:
            total += 1
            probs = audit(f, model, label)
            if probs:
                n_bad += 1; bad += 1
                print(f"  {f}")
                for p in probs: print(f"      {p}")
        print(f"{corpus}: {len(files)} file(s), {n_bad} with findings")
    print(f"\nTOTAL {total} inputs, {bad} with canonicality findings")

if __name__ == "__main__":
    main()
