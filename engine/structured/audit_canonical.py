#!/usr/bin/env python3
"""Static canonicality audit of Crucible's committed corpora against the POC spec
(documentation PR #29, incl. #30 and #31). Independent of gen.py: it re-derives the
properties from the bytes, so it can catch a reference encoder that is itself wrong.

Properties checked on every input that is meant to be CANONICAL:
  P1  no all-default (childless) sequence at a struct/union FIELD position
      -> §2: such a field is omitted; a conformant encoder never emits the frame
  P2  no empty union frame at all (49b710b: the degenerate union is omitted)
  P3  no empty wrapper frame unless the field's declared default is non-empty
      (probe declares none, so: no empty wrapper at all)
  P4  no all-default element in a wrapper's INTERIOR -> #31: the interior is sparse,
      such an element must be an id gap. (At the LAST index it is required instead —
      it carries the length — so P4 deliberately exempts the highest id.)

Not checked here, because it needs the value and not just the bytes: that the last
element is *present*. A wrapper's last element is present by construction — the
highest id on the wire is the last index — so it can only be wrong relative to the
intended value, which the byte stream does not carry.

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
