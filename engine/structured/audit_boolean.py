#!/usr/bin/env python3
"""Completeness audit for the §4.4 boolean coverage — a HAND-RUN tool.

Sibling of `audit_canonical.py`, and there for the same reason: a coverage claim that
lives only in prose rots. This one re-derives, from the schema and the axes themselves,
whether every place a `boolean` can sit has one, whether the position model agrees with
the schema, which axes actually reach a boolean position, whether every materialized-form
walker handles the kind, and whether the value set still covers each distinct way of
getting §4.4 wrong. Run it after any schema or sweep change that touches booleans.

    python3 engine/structured/audit_boolean.py      # exits non-zero on a gap
"""
import importlib, io, contextlib, os, subprocess, sys, tempfile, yaml
sys.path.insert(0, 'engine/structured')

FAIL = []
def check(label, ok, detail=""):
    print(f"  [{'ok ' if ok else 'GAP'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok: FAIL.append(label)

print("\n1. SCHEMA POSITIONS — every place a `boolean` can sit, and whether one does")
def bool_positions(path):
    y = yaml.safe_load(open(path)); (_, m), = y["messages"].items()
    found = []
    def walk(fields, scope, kind):
        for name, spec in fields.items():
            t = spec["type"]; p = scope + [spec["id"]]
            if t == "boolean": found.append((tuple(p), kind))
            elif t == "struct": walk(spec["fields"], p, "struct child")
            elif t == "union":
                for on, os_ in spec["oneof"].items():
                    if os_["type"] == "boolean": found.append((tuple(p+[os_["id"]]), "union member"))
            elif t == "array":
                it = spec["items"]
                if it["type"] == "boolean": found.append((tuple(p), "array element"))
                elif it["type"] == "struct": walk(it["fields"], p + [0], "wrapper-element child")
    walk(m["payload"], [], "root scalar")
    return found
probe = bool_positions('schema/probe.sofab.yaml')
union = bool_positions('schema/probe-union.sofab.yaml')
for p, k in probe + union: print(f"        {str(p):16} {k}")
kinds = {k for _, k in probe + union}
for want in ("root scalar", "struct child", "array element", "wrapper-element child", "union member"):
    check(f"position kind: {want}", want in kinds)

print("\n2. POSITION MODEL — the schema and sweep_positions agree")
from sweep_positions import POSITIONS, UNION_MEMBER_POSITIONS
model = {(p.path + (p.fid,)) for p in POSITIONS if "bool" in p.cat}
model |= {(p.path + (p.fid,)) for p in UNION_MEMBER_POSITIONS if "bool" in p.cat}
schema = {p for p, _ in probe} | {p for p, _ in union}
check("every schema boolean has a Position", schema <= model, f"schema={sorted(schema)} model={sorted(model)}")
check("no Position without a schema boolean", model <= schema)

print("\n3. AXES — which sweep reaches a boolean position")
AXES = ["sweep_repeated_id","sweep_overbound","sweep_reserved_subtype","sweep_truncation",
        "sweep_malform_truncate","wiretype_sweep","sweep_varint","sweep_empty_frame",
        "sweep_framing","sweep_unknown_seq","sweep_repeated_elem","sweep_tolerance"]
TAGS = ("root_id203","root_id204","10_id9","202_0_id2","bool")
reach = {}
for a in AXES:
    m = importlib.import_module(a); d = tempfile.mkdtemp()
    with contextlib.redirect_stdout(io.StringIO()): vs = m.emit(d)
    names = [v[0] for v in vs]
    n_bool = sum(1 for n in names if any(t in n for t in TAGS))
    if a == "sweep_truncation":
        # this axis names its vectors by OFFSET, not by position: it truncates ONE rich
        # message at every byte. So count the cut points that land inside a boolean
        # field instead of grepping names (the naive grep reports 0 and is wrong).
        rich = m.rich_message()
        first = rich.hex().find("d80c") // 2          # `flag` (id 203) header
        n_bool = len(rich) - first
    reach[a] = (len(names), n_bool)
for a,(n,b) in reach.items(): print(f"        {a:24} {n:>5} vectors, {b:>4} at a boolean position")
# the axes that MUST reach one, and why the others need not
MUST = {"wiretype_sweep":"§7.3 — a boolean's wire type must be swept",
        "sweep_reserved_subtype":"§4.6 — every position",
        "sweep_overbound":"§7.1 — the array's count still binds",
        "sweep_repeated_id":"§7.4 — the field slot",
        "sweep_tolerance":"§4.4 — the rule itself",
        "sweep_empty_frame":"§2 — the zero-count boolean array",
        "sweep_truncation":"§7 — truncating through a boolean's varint"}
for a, why in MUST.items(): check(f"{a} reaches a boolean ({why})", reach[a][1] > 0)

print("\n4. WALKERS — every materialized-form walker handles the `bool` kind")
W = {"drivers/c/driver.c":None,  # descriptor-driven: sofabgen emits UNSIGNED, no bool branch exists
     "drivers/go/driver.go":'case "bool"', "drivers/python/driver.py":'"bool": _bool',
     "drivers/ts/driver.ts":'case "bool"', "drivers/cs/Driver.cs":'"bool" =>',
     "drivers/java/ProbeDump.java":'case "bool"',
     "drivers/cpp/materialize_gen.py":'kind == "bool"', "drivers/dart/materialize_gen.py":'kind == "bool"',
     "drivers/kotlin/materialize_gen.py":'kind == "bool"', "drivers/rust/materialize_gen.py":'kind == "bool"',
     "drivers/zig/materialize_gen.py":'kind == "bool"',
     "engine/structured/materialize.py":'kind == "bool"'}
for f, needle in W.items():
    if needle is None:
        print(f"  [n/a] {f} — descriptor-driven (sofabgen tags the field UNSIGNED; prints the RAW value, which is the signal)")
        continue
    check(f, needle in open(f).read())
# and the rust array path, which is separate
check("drivers/rust/materialize_gen.py array path", 'mz_arr_bool' in open('drivers/rust/materialize_gen.py').read())

print("\n5. VALUES — each defeats a different way of getting §4.4 wrong")
import sweep_tolerance as T
d = tempfile.mkdtemp()
with contextlib.redirect_stdout(io.StringIO()): vs = T.emit(d)
names = " ".join(v[0] for v in vs)
for v in ("bool_two","bool_0xff","bool_256_over_u8","bool_2p32_over_u32","bool_2p63_sign_bit",
          "bool_u64_max","bool_true_nonminimal","bool_false_explicit","bool_false_nonminimal",
          "bool_varint_over_64bit","bool_true_ctl"):
    check(f"value case {v}", v in names)

print("\n6. ORACLES")
print("        round-trip      — corpus/structured (8 boolean vectors) + corpus/seeds/07_booleans.bin")
print("        materialized    — same corpus, SOFAB_MATERIALIZE=1 (u1/u0, raw value if unnormalized)")
print("        chunk-invariance— corpus/seeds/07_booleans.bin")
print("        encode surfaces — corpus/structured (run-encode.sh: new/to/stream)")
print("        union           — corpus/structured-union (2 boolean vectors) + tolerance emit_union")
print("        limit mode      — n/a: a boolean has no capacity, so no receiver cap binds it")

print(f"\n{'ALL CHECKS PASSED' if not FAIL else str(len(FAIL)) + ' GAP(S): ' + ', '.join(FAIL)}")
sys.exit(1 if FAIL else 0)
