#!/usr/bin/env python3
"""$ref codegen gate — does writing a type through `$ref` change the generated code?

`schema/ref-forms/` holds one file per way a schema can use `$ref` (crucible#212). The
header of each states what sofabgen must do with it:

  * ``# expect: equivalent`` — two YAML documents: the first uses `$ref`, the second is the
    same message with every `$ref` written out. Both are generated for every target and
    compared. First, target-independently: the `$ref` document dereferenced must BE the
    inline one, and sofabgen's IR of the two (shared types expanded, names dropped) must be
    equal. The target is identical output; what is not identical is reported, per target,
    against the committed baseline ``results/ref-codegen-baseline.txt``.
    ``schema/probe-ref.sofab.yaml`` and its inline twin are checked as one more such pair.
  * ``# expect: reject [text]`` — sofabgen must refuse it on every target (and say
    ``text``).
  * ``# expect: accept`` — sofabgen must generate it on every target (no form uses it today;
    the recursive forms expect ``reject``: no recursive types, documentation#101).

A ``# known: <G-id>`` line marks a form whose expectation sofabgen does not meet yet (a
refusal that does not come; for a pair, a target that does not generate it or an IR that
differs); it is reported as XFAIL and does not fail the gate. When the finding is fixed the form meets
its expectation, which DOES fail the gate until the ``known:`` line is removed — so a fix
cannot land unnoticed.

How an equivalent pair is compared, per target. A `$defs` type is named after the def
(``Pt``), an inline one after its schema path (``Probe_A``), and the two spellings can never
coincide (generator ARCHITECTURE §8: ``Pascal`` emits no ``_``, a name may not hold ``__``).
So the check grades, from best to worst:

  IDENTICAL  same files, same bytes.
  RENAME     the token streams (whitespace ignored, since a longer name re-aligns
             formatted columns — except Python's indentation, which is code) are equal once
             a consistent identifier rename is applied. The rename is derived from the two
             outputs and only accepted for identifiers that never occur on the other side,
             where walking the two schemas pairs the inline type path one spells with the
             def the other spells, every name segment around it equal — so a changed
             literal, type or call cannot pass as a rename.
  LAYOUT     what remains after the rename are whole top-level declarations both sides hold,
             in another place or file (a C `$defs` type moves to ``sofab-defs.h``), or folded
             into one shared copy (a def at two sites is one type, inline gives two).
  DOC        as LAYOUT, plus comment lines that differ (a Java doc names ``probe.c`` / ``Hue``).
  DIFF       code only one side has, or the same code in another order inside a declaration.

The baseline records each pair's grade, the number of renamed identifiers, every residual
code line in order, and per file the number of differing comment lines; any change fails the
gate (an improvement too — re-run with ``--update`` and commit the new baseline). A comment
reworded alike on both sides changes nothing; one reworded on one side changes a count only
if its line count changes.

  python3 scripts/check-ref-codegen.py            # gate (exit 1 on any change)
  python3 scripts/check-ref-codegen.py --update   # rewrite the baseline
  python3 scripts/check-ref-codegen.py --report   # grade matrix + renames, no gate
  python3 scripts/check-ref-codegen.py --only union-split --lang go   # those cells vs the baseline
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, "schema", "ref-forms")
BASELINE = os.path.join(ROOT, "results", "ref-codegen-baseline.txt")
SOFABGEN = os.environ.get("SOFABGEN", os.path.join(ROOT, "tools", "sofabgen"))
LANGS = ["c", "cpp", "csharp", "dart", "go", "java", "kotlin", "python", "rust", "typescript", "zig"]
# The combined pair: every form in one message the roster builds (scripts/run-ref.sh). Its
# twin must be the $ref schema dereferenced, which this gate asserts like any form's.
PROBE_REF_NAME = "probe-ref"
PROBE_REF = (os.path.join(ROOT, "schema", "probe-ref.sofab.yaml"),
             os.path.join(ROOT, "schema", "probe-ref-inline.sofab.yaml"))


def extras_of(d):
    """The files a form may $ref across (`*.defs.yaml` beside it), copied beside each document."""
    return {n: open(os.path.join(d, n), encoding="utf-8").read()
            for n in sorted(os.listdir(d)) if n.endswith(".defs.yaml")}

class _Yaml12(yaml.SafeLoader):
    """PyYAML resolves `on`/`off`/`yes`/`no` as booleans (YAML 1.1); sofabgen's yaml.v3 reads
    them as strings — and a field may well be named `on` (the generator README's whole-field
    example is). Only `true`/`false` are booleans here, as there."""


_Yaml12.yaml_implicit_resolvers = {k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:bool"]
                                   for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Yaml12.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
                              list("tTfF"))


def yload(text):
    return yaml.load(text, Loader=_Yaml12) or {}


def _ptr_parts(ptr):
    """A JSON pointer's segments, `~1` and `~0` unescaped."""
    return [p.replace("~1", "/").replace("~0", "~") for p in ptr.strip("/").split("/")]


TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|\S")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


# ------------------------------------------------------------------------- forms
def load_form(path):
    text = open(path, encoding="utf-8").read()
    head = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        m = re.match(r"#\s*(form|expect|known):\s*(.*)", line)
        if m:
            head[m.group(1)] = m.group(2).strip()
    if "expect" not in head:
        return None
    docs = re.split(r"(?m)^---\s*$", text)
    kind, _, arg = head["expect"].partition(" ")
    return {"name": os.path.basename(path)[:-len(".sofab.yaml")], "kind": kind, "arg": arg.strip(),
            "known": head.get("known"), "form": head.get("form", ""), "docs": docs,
            "extras": extras_of(os.path.dirname(path))}


def probe_ref_form():
    ref, inl = (open(p, encoding="utf-8").read() for p in PROBE_REF)
    return {"name": PROBE_REF_NAME, "kind": "equivalent", "arg": "", "known": None,
            "form": "schema/probe-ref.sofab.yaml vs its inline twin", "docs": [ref, inl],
            "extras": extras_of(os.path.dirname(PROBE_REF[0]))}


def generate(doc, lang, work, extras):
    """Write one schema document beside the shared defs and generate it. -> (rc, out_dir, log)."""
    os.makedirs(work, exist_ok=True)
    for name, text in extras.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as g:
            g.write(text)
    schema = os.path.join(work, "probe.sofab.yaml")
    with open(schema, "w", encoding="utf-8") as f:
        f.write(doc)
    out = os.path.join(work, "out-" + lang)
    p = subprocess.run([SOFABGEN, "--lang", lang, "--in", schema, "--out", out],
                       capture_output=True, text=True)
    return p.returncode, out, (p.stderr + p.stdout).strip()


def model(doc, work, extras):
    """sofabgen's IR of `doc` with every shared type expanded in place and every type NAME
    dropped: what the message is, independent of how its types are spelled or shared."""
    os.makedirs(work, exist_ok=True)
    for name, text in extras.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as g:
            g.write(text)
    with open(os.path.join(work, "probe.sofab.yaml"), "w", encoding="utf-8") as g:
        g.write(doc)
    p = subprocess.run([SOFABGEN, "--dump-ir", "--in", os.path.join(work, "probe.sofab.yaml")],
                       capture_output=True, text=True)
    if p.returncode:
        return None, p.stderr
    ir = json.loads(p.stdout)
    named = {n["key"]: n for n in ir.get("named") or []}

    def expand(node, depth=0):
        if depth > 64:
            raise ValueError("ref cycle in IR")
        if isinstance(node, list):
            return [expand(x, depth) for x in node]
        if not isinstance(node, dict):
            return node
        # `variant` labels a split union's type (its name); `ref`/`elem_ref` name a type and are
        # replaced by its content
        out = {k: expand(v, depth) for k, v in node.items()
               if k not in ("ref", "elem_ref", "key", "path", "inline", "variant")}
        for link, into in (("ref", None), ("elem_ref", "elem_type")):
            if node.get(link) in named:
                body = {k: expand(v, depth + 1) for k, v in named[node[link]].items()
                        if k not in ("key", "path", "category", "inline", "name", "variant")}
                if into:
                    out[into] = body
                else:
                    for k, v in body.items():
                        out.setdefault(k, v)
        return out
    return expand(ir.get("messages") or []), ""


def dereferenced(doc, extras):
    """The document's `messages` with every `$ref` replaced by what it points at (the shared
    defs file included): the schema an inline twin must spell out word for word. The IR
    cannot stand in for this — it records that a field HAS a default, not its value."""
    docs = {None: yload(doc)}
    docs.update({n: yload(t) for n, t in extras.items()})

    def walk(node, cur, depth=0):
        if depth > 64:
            raise ValueError("$ref cycle")
        ref = _lone_ref(node)
        if ref is not None:
            f, _, ptr = ref.partition("#")
            f = f or cur
            target = docs.get(f, {})
            for part in _ptr_parts(ptr):
                target = target[part]
            return walk(target, f, depth + 1)
        if isinstance(node, dict):
            return {k: walk(v, cur, depth) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, cur, depth) for v in node]
        return node
    return walk(docs[None].get("messages"), None)


def read_tree(d):
    files = {}
    for base, _, names in os.walk(d):
        for n in names:
            p = os.path.join(base, n)
            with open(p, "rb") as f:
                files[os.path.relpath(p, d)] = f.read().decode("utf-8", "replace")
    return files


# ---------------------------------------------------------------- name evidence
def segs(*names):
    """Lower-case name segments, split at `_` and camelCase: `_Vec2Alias__Loc` -> vec2 alias loc."""
    out = []
    for n in names:
        for part in re.split(r"[^A-Za-z0-9]+", n):
            out += [w.lower() for w in re.findall(r"[A-Z]+[0-9]*(?![a-z])|[A-Z]?[a-z0-9]+|[0-9]+", part)]
    return tuple(out)


def _within(needle, hay):
    n = len(needle)
    return any(hay[k:k + n] == needle for k in range(len(hay) - n + 1))


def _lone_ref(node):
    return node["$ref"] if isinstance(node, dict) and len(node) == 1 and isinstance(node.get("$ref"), str) else None


def correspondences(ref_doc, inl_doc, extras):
    """Which inline type becomes which $defs type: walk both documents in step and, at each
    `$ref` to a `$defs` body, pair the inline type's schema path with the def's name. A type
    declared inline INSIDE a def is named from the def, so the walk continues into the def's
    body with the def as the new path root. -> {inline path segments: {$ref path segments it may become}}."""
    docs = {None: yload(ref_doc)}
    docs.update({n: yload(t) for n, t in extras.items()})
    out = {}

    def resolve(ref, cur):
        f, _, ptr = ref.partition("#")
        f = f or cur
        node = docs.get(f, {})
        for part in _ptr_parts(ptr):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        parts = _ptr_parts(ptr)
        name = parts[2] if len(parts) == 3 and parts[0] == "$defs" else None
        return node, name, f

    unions = {}                                        # union def -> [(inline path, default_id)]

    def body(r, i, rpath, ipath, cur, key, site):
        """r/i: a scope body (fields / oneof / payload / enum / bits) on each side; `site` is
        the field spec holding it (for a union's default_id)."""
        seen, first = set(), True
        while True:                                    # follow an alias def to its body; the
            ref = _lone_ref(r)                         # site's type is the FIRST def named
            if ref is None or ref in seen:
                break
            seen.add(ref)
            r, name, cur = resolve(ref, cur)
            if name and first:
                out[segs(*ipath)] = {segs(name)}
                rpath = [name]
                if key == "oneof":
                    unions.setdefault(name, []).append((ipath, site.get("default_id"), r))
            first = False
        if seen == set() and rpath != ipath and key != "payload":
            out[segs(*ipath)] = {segs(*rpath)}            # declared inline inside a def
        if key in ("fields", "oneof", "payload") and isinstance(r, dict) and isinstance(i, dict):
            for k, spec in r.items():
                if k in i:
                    field(spec, i[k], rpath + [k], ipath + [k], cur)

    def field(r, i, rpath, ipath, cur):
        while _lone_ref(r):                            # a whole-field copy: follow it to the field
            r, _, cur = resolve(_lone_ref(r), cur)
        if not (isinstance(r, dict) and isinstance(i, dict)):
            return
        for key in ("fields", "oneof", "enum", "bits"):
            if key in r and key in i:
                body(r[key], i[key], rpath, ipath, cur, key, r)
        if "items" in r and "items" in i:              # an array's element takes the field's path
            field(r["items"], i["items"], rpath, ipath, cur)

    inl = yload(inl_doc)
    for m, spec in (docs[None].get("messages") or {}).items():
        ispec = (inl.get("messages") or {}).get(m)
        if isinstance(spec, dict) and isinstance(ispec, dict) and "payload" in spec:
            payload, cur = spec["payload"], None
            while _lone_ref(payload):                  # a $ref payload is expanded IN PLACE: its
                payload, _, cur = resolve(_lone_ref(payload), cur)   # fields are the message's
            body(payload, ispec.get("payload"), [m], [m], cur, "payload", spec)
    # A $defs union used with two effective default_ids is split into one type per default_id,
    # named after the default option (generator ARCHITECTURE §8): the site pairs with THAT type.
    for name, sites in unions.items():
        def opt(did, defn):
            ids = {v.get("id"): k for k, v in defn.items() if isinstance(v, dict)}
            return ids.get(min(ids) if did is None else did, "")
        eff = {opt(did, defn) for _, did, defn in sites}
        if len(eff) > 1:
            for ipath, did, defn in sites:
                # the variant type, or the def itself (its option ids are shared: `Shape_Num__ID`)
                out[segs(*ipath)] = {segs(name, "default", opt(did, defn)), segs(name)}
    return out


def _at(needle, hay):
    n = len(needle)
    return next(k for k in range(len(hay) - n + 1) if hay[k:k + n] == needle)


def allowed(a, b, corr):
    """May inline identifier `a` be renamed to `b`? Only if `a` spells an inline type path whose
    $ref counterpart `b` spells — judged by the most specific path each name contains — and
    everything around the type part is the same on both sides (`Probe_U0_Num__ID` may become
    `Shape_Num__ID`, never `Shape_Name__ID`)."""
    sa, sb = segs(a), segs(b)
    ia = max((k for k in corr if _within(k, sa)), key=len, default=None)
    if ia is None or corr[ia] == {ia}:
        return False
    rb = max((v for alts in corr.values() for v in alts if _within(v, sb)), key=len, default=None)
    if rb not in corr[ia]:
        return False
    i, j = _at(ia, sa), _at(rb, sb)
    return sa[:i] == sb[:j] and sa[i + len(ia):] == sb[j + len(rb):]


# -------------------------------------------------------------------- compare
def toks(text):
    return TOKEN.findall(text)


def file_toks(path, text):
    """A file's tokens; in an indentation-sensitive file (Python) every line starts with a
    token for its indentation, so a statement moved in or out of a block is a difference."""
    if not path.endswith(".py"):
        return toks(text)
    out = []
    for raw in text.splitlines():
        ts = toks(raw)
        if ts:
            out += [f"<indent {len(raw) - len(raw.lstrip())}>"] + ts
    return out


C_DIRECTIVES = {"define", "include", "if", "ifdef", "ifndef", "endif", "else", "elif", "error",
                "pragma", "undef", "warning", "line"}


def is_comment(raw):
    """A line that holds only a comment (or a block comment's continuation), in any target."""
    t = raw.strip()
    if t.startswith(("//", "/*", "*", '"""')):
        return True
    if t.startswith("#") and not t.startswith(("#[", "#!")):
        word = re.match(r"#\s*([A-Za-z]*)", t).group(1)
        return word not in C_DIRECTIVES
    return False


def _lined(text):
    """The tokens of `text` with a "\\n" token between lines (blank lines dropped)."""
    out = []
    for raw in text.splitlines():
        ts = toks(raw)
        if ts:
            out += ts + ["\n"]
    return out


def derive_renames(pairs, corr, ref_vocab, inl_vocab, ren):
    """Extend `ren` (inline identifier -> $ref identifier) from the equal-length replaced runs
    of aligned token sequences. Returns True when it grew."""
    seen = {}
    for inl, ref in pairs:
        sm = difflib.SequenceMatcher(None, inl, ref, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "replace" or i2 - i1 != j2 - j1:
                continue
            for a, b in zip(inl[i1:i2], ref[j1:j2]):
                if a != b and IDENT.match(a) and IDENT.match(b):
                    votes = seen.setdefault(a, {})
                    votes[b] = votes.get(b, 0) + 1
    grew = False
    for a, bs in seen.items():
        if a in ren or a in ref_vocab:
            continue                                  # a name both sides use is not renamed
        # an alignment can pair a name with the wrong one (two similar blocks, reordered, or
        # two lines alike but for the option they name): only a pairing the schemas state
        # counts, and the best-supported one must lead outright
        ranked = sorted(((n, b) for b, n in bs.items() if b not in inl_vocab and allowed(a, b, corr)),
                        reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            ren[a] = ranked[0][1]
            grew = True
    return grew


def raw_hunks(mapped, rt):
    """(path, kind, inline tokens, $ref tokens) for every non-equal run, files paired by path."""
    out = []
    for path in sorted(set(mapped) | set(rt)):
        inls, ref = mapped.get(path, []), rt.get(path)
        if ref is None:
            out += [(path + " (file only inline)", "delete", ts, []) for ts in inls]
            continue
        if not inls:
            out.append((path + " (file only with $ref)", "insert", [], ref))
            continue
        for k, ts in enumerate(inls):
            if k:                                     # two inline types fold onto one $ref type
                out.append((path + " (second inline copy)", "delete", ts, []))
                continue
            sm = difflib.SequenceMatcher(None, ts, ref, autojunk=False)
            out += [(path, tag, ts[i1:i2], ref[j1:j2])
                    for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
    return out


def line_pairs(it, rt, ren, corr):
    """Order-free evidence: a line only the inline side holds, set against each equally long
    line of the $ref side that differs from it in identifiers alone, every one of them a
    rename the schemas allow. Every $ref line is a candidate, not only the unmatched ones:
    two inline types may fold onto one shared type, whose lines then answer for both."""
    def pool(files, rename):
        out = {}
        for ts in files.values():
            for line in " ".join(rename.get(t, t) if t != "\n" else t for t in ts).split(" \n "):
                out[line] = out.get(line, 0) + 1
        return out
    li = pool({p: _lined(t) for p, t in it.items()}, ren)
    lr = pool({p: _lined(t) for p, t in rt.items()}, {})
    only_i = [l.split(" ") for l in li if li[l] > lr.get(l, 0)]
    by_len = {}
    for l in lr:
        ts = l.split(" ")
        by_len.setdefault(len(ts), []).append(ts)
    out = []
    for a in only_i:
        for b in by_len.get(len(a), []):
            diff = [(x, y) for x, y in zip(a, b) if x != y]
            if diff and all(IDENT.match(x) and IDENT.match(y) and allowed(x, y, corr) for x, y in diff):
                out.append((a, b))
    return out


def moved_pairs(hunks):
    """Each deleted run aligned with the inserted run it most resembles: a block that moved
    to another place or file carries its renames with it."""
    dels = [h[2] for h in hunks if h[2] and not h[3]]
    ins = [h[3] for h in hunks if h[3] and not h[2]]
    out = []
    for d in dels:
        best, score = None, 0.5
        for i in ins:
            sm = difflib.SequenceMatcher(None, d, i, autojunk=False)
            if sm.real_quick_ratio() > score and sm.quick_ratio() > score and sm.ratio() > score:
                best, score = i, sm.ratio()
        if best is not None:
            out.append((d, best))
    return out


def rename_path(path, ren):
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: ren.get(m.group(0), m.group(0)), path)


def compare(ref_files, inl_files, corr):
    """-> (grade, renames, residual hunks)."""
    if ref_files == inl_files:
        return "IDENTICAL", {}, []
    rt = {p: file_toks(p, t) for p, t in ref_files.items()}
    it = {p: file_toks(p, t) for p, t in inl_files.items()}
    rtl = {p: t for p, t in ref_files.items()}
    itl = {p: t for p, t in inl_files.items()}
    ref_vocab = {t for ts in rt.values() for t in ts}
    inl_vocab = {t for ts in it.values() for t in ts}

    # Derive the rename from the files both sides name alike, pair the rest through it (a
    # Java/Kotlin file is named after its type), then follow blocks that moved; repeat until
    # the rename stops growing.
    ren = {}

    def mapping():
        m = {}
        for p in sorted(it):
            m.setdefault(rename_path(p, ren), []).append([ren.get(t, t) for t in it[p]])
        return m

    for _ in range(6):
        mapped = mapping()
        pairs = [(ts[0], rt[p]) for p, ts in mapped.items() if p in rt]
        hunks0 = raw_hunks(mapped, rt)
        evidence = pairs + moved_pairs(hunks0) + line_pairs(itl, rtl, ren, corr)
        if not derive_renames(evidence, corr, ref_vocab, inl_vocab, ren):
            break
    mapped = mapping()
    if all(p in rt and len(ts) == 1 and ts[0] == rt[p] for p, ts in mapped.items()) and set(mapped) == set(rt):
        return "RENAME", ren, []

    # What is left is compared declaration by declaration. Every file is cut into its top-level
    # declarations (a cut at each line that starts in column 0 with every bracket closed);
    # a line is its tokens, renamed, in Python with its indentation; comments are set apart.
    #   moved / folded  a declaration both sides hold verbatim, in another place or file, or
    #                   one the inline side holds twice and the $ref side once (shared type)
    #   comment         comment lines only one side holds (kept as per-file counts: a comment
    #                   reworded alike on both sides changes nothing)
    #   content         a declaration only one side holds: set against its most similar
    #                   counterpart and diffed IN ORDER, so a reordered body is content too
    def cut(files, rename):
        decls, notes = [], {}
        for path in sorted(files):
            mp = rename_path(path, rename)
            cur, depth = [], 0
            for raw in files[path].splitlines():
                ts = [rename.get(t, t) for t in toks(raw)]
                if not ts:
                    continue
                if is_comment(raw):
                    notes.setdefault(mp, []).append(" ".join(ts))
                    continue
                lead = len(raw) - len(raw.lstrip())
                if cur and depth == 0 and lead == 0:
                    decls.append((mp, tuple(cur)))
                    cur = []
                cur.append((f"<indent {lead}> " if path.endswith(".py") else "") + " ".join(ts))
                depth += sum(ts.count(a) for a in "([{") - sum(ts.count(b) for b in ")]}")
            if cur:
                decls.append((mp, tuple(cur)))
        return decls, notes

    rd, rn = cut(ref_files, {})
    idl, inn = cut(inl_files, ren)
    res = [("file+", p_, "only with $ref") for p_ in sorted(set(rt) - set(mapped))]
    res += [("file-", p_, "only inline") for p_ in sorted(set(mapped) - set(rt))]
    res += [("file-", p_, f"{len(ts)} inline files fold onto this one") for p_, ts in sorted(mapped.items()) if len(ts) > 1]

    from collections import Counter
    r_left, i_left = Counter(b for _, b in rd), Counter(b for _, b in idl)
    common = r_left & i_left
    # moved: the common declarations outside the longest run both sides hold in the same order
    seq_r = [x for x in rd if common[x[1]]]
    seq_i = [x for x in idl if common[x[1]]]
    kept = sum(m.size for m in difflib.SequenceMatcher(None, seq_r, seq_i, autojunk=False).get_matching_blocks())
    moved = min(len(seq_r), len(seq_i)) - kept
    r_only, i_only = [], []
    rc, ic = Counter(common), Counter(common)
    for pa, b in rd:
        if rc[b]:
            rc[b] -= 1
        else:
            r_only.append((pa, b))
    for pa, b in idl:
        if ic[b]:
            ic[b] -= 1
        else:
            i_only.append((pa, b))
    folded = [x for x in i_only if x[1] in r_left]
    i_only = [x for x in i_only if x[1] not in r_left]
    unfolded = [x for x in r_only if x[1] in i_left]       # the mirror: $ref side holds it twice
    r_only = [x for x in r_only if x[1] not in i_left]
    if moved:
        res.append(("moved", "*", f"{moved} top-level declaration(s) held by both sides in another place"))
    if folded or unfolded:
        res.append(("folded", "*", f"{len(folded)} inline / {len(unfolded)} $ref declaration(s) "
                                   "the other side holds once (one shared type)"))

    content = []
    pool = list(r_only)
    for pa, b in i_only:
        best, score = None, 0.5
        for k, (pb, c) in enumerate(pool):
            sm = difflib.SequenceMatcher(None, b, c, autojunk=False)
            if sm.real_quick_ratio() > score and sm.quick_ratio() > score and sm.ratio() > score:
                best, score = k, sm.ratio()
        if best is None:
            content += [("-", pa, line) for line in b]
            continue
        pb, c = pool.pop(best)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b, c, autojunk=False).get_opcodes():
            if tag in ("delete", "replace"):
                content += [("-", pa, line) for line in b[i1:i2]]
            if tag in ("insert", "replace"):
                content += [("+", pb, line) for line in c[j1:j2]]
    for pb, c in pool:
        content += [("+", pb, line) for line in c]

    comments = {}
    for path in sorted(set(rn) | set(inn)):
        a, b = Counter(inn.get(path, [])), Counter(rn.get(path, []))
        m, p_ = sum((a - b).values()), sum((b - a).values())
        if m or p_:
            comments[path] = (m, p_)
    # the baseline keeps comment COUNTS per file, so a reword that keeps the line count is no change
    for path, (m, p_) in sorted(comments.items()):
        res.append(("comment", path, f"-{m}/+{p_} comment line(s)"))
    if content:
        return "DIFF", ren, res + content
    if comments:
        return "DOC", ren, res
    return "LAYOUT", ren, res


# ------------------------------------------------------------------- the gate
def run(forms, langs):
    rows = []                                        # (form, lang, grade, detail, ok)
    report = {}                                      # (form, lang) -> (grade, ren, hunks)
    models = {}                                      # form -> the two documents model alike
    xfailed = set()                                  # equivalent forms a known gap still breaks
    with tempfile.TemporaryDirectory() as tmp:
        for f in forms:
            for lang in langs:
                work = os.path.join(tmp, f["name"], lang)
                if f["kind"] == "equivalent":
                    if len(f["docs"]) != 2:
                        rows.append((f["name"], lang, "BROKEN", "needs exactly two documents", False))
                        continue
                    rc1, o1, l1 = generate(f["docs"][0], lang, os.path.join(work, "ref"), f["extras"])
                    rc2, o2, l2 = generate(f["docs"][1], lang, os.path.join(work, "inline"), f["extras"])
                    if f["name"] not in models:            # once per pair: target-independent
                        m1, e1 = model(f["docs"][0], os.path.join(tmp, f["name"], "ir-ref"), f["extras"])
                        m2, e2 = model(f["docs"][1], os.path.join(tmp, f["name"], "ir-inline"), f["extras"])
                        same_schema = dereferenced(f["docs"][0], f["extras"]) == yload(f["docs"][1]).get("messages")
                        models[f["name"]] = same_schema and m1 is not None and m1 == m2
                        why = ("" if same_schema else "the $ref document, dereferenced, is not the inline document; ") \
                            + (e1 or e2 or ("" if m1 == m2 else "sofabgen models the two documents differently"))
                        grade = "SAME" if models[f["name"]] else ("SCHEMA-DIFF" if not same_schema else "MODEL-DIFF")
                        ok = models[f["name"]]
                        if grade == "MODEL-DIFF" and f["known"]:   # a known generator gap
                            grade, ok = f"XFAIL {f['known']}", True
                            xfailed.add(f["name"])
                        rows.append((f["name"], "ir", grade, why, ok))
                    if rc1 or rc2:
                        last = (l1 if rc1 else l2).splitlines()[-1:]
                        if f["known"]:
                            xfailed.add(f["name"])
                            rows.append((f["name"], lang, f"XFAIL {f['known']}", f"GENFAIL {last}", True))
                        else:
                            rows.append((f["name"], lang, "GENFAIL", last, False))
                        continue
                    grade, ren, hunks = compare(read_tree(o1), read_tree(o2), correspondences(f["docs"][0], f["docs"][1], f["extras"]))
                    report[(f["name"], lang)] = (grade, ren, hunks)
                    rows.append((f["name"], lang, grade, f"{len(ren)} renamed, {len(hunks)} residual", True))
                    continue
                rc, _, log = generate(f["docs"][0], lang, work, f["extras"])
                if f["kind"] == "reject":
                    met = rc != 0 and f["arg"] in log
                    got = "REJECTED" if rc else "GENERATED"
                    if rc and not met:
                        got = "REJECTED-OTHER"
                else:                                    # accept
                    met = rc == 0
                    got = "GENERATED" if rc == 0 else "REJECTED"
                last = log.splitlines()[-1] if log else ""
                if f["known"]:
                    ok = not met
                    grade = f"XFAIL {f['known']}" if ok else f"FIXED? {f['known']}"
                    detail = got + ("" if ok else " — expectation met; drop the `known:` line")
                else:
                    ok, grade, detail = met, ("OK" if met else "FAIL"), got
                rows.append((f["name"], lang, grade, f"{detail}: {last}"[:160], ok))
            if f["kind"] == "equivalent" and f["known"] and f["name"] not in xfailed and len(langs) == len(LANGS):
                rows.append((f["name"], "ir", f"FIXED? {f['known']}",
                             "every target generates it and models it alike — drop the `known:` line", False))
    return rows, report


def baseline_text(report):
    out = ["# results/ref-codegen-baseline.txt — generated by scripts/check-ref-codegen.py --update.",
           "# One block per (form, target): the grade, the number of renamed identifiers with a",
           "# digest of the rename, and every residual: `file+`/`file-` a file only the $ref/inline",
           "# output has; `moved` the number of top-level declarations both hold in another place;",
           "# `comment` per file the comment lines only the inline (-) / $ref (+) output has; `+`/`-`",
           "# a code line (tokens, renamed), in file order, only the $ref/inline output has.",
           f"# `{PROBE_REF_NAME}` (every form in one message) is the sum of the forms above, so it is held",
           "# as counts and a digest of its residuals; `--report --only probe-ref` prints them.", ""]

    def sha(lines):
        return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:10]
    for (form, lang) in sorted(report):
        grade, ren, hunks = report[(form, lang)]
        names = sha(f"{a}>{b}" for a, b in sorted(ren.items())) if ren else "-"
        lines = [f"    {cls} {text}   [{path}]" for cls, path, text in hunks]
        if form == PROBE_REF_NAME:
            plus = sum(1 for c, *_ in hunks if c.startswith(("+", "file+")))
            out.append(f"{form} {lang} {grade} renames={len(ren)}:{names} "
                       f"residuals=+{plus}/-{len(hunks) - plus}:{sha(lines) if hunks else '-'}")
            continue
        out.append(f"{form} {lang} {grade} renames={len(ren)}:{names}")
        out += lines
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--only", action="append", help="form name (repeatable)")
    ap.add_argument("--lang", action="append", choices=LANGS)
    ap.add_argument("-v", "--verbose", action="store_true", help="print renames and residuals")
    a = ap.parse_args()
    if not os.access(SOFABGEN, os.X_OK):
        print(f"error: no sofabgen at {SOFABGEN} (run scripts/bootstrap.sh)", file=sys.stderr)
        return 2
    forms = [f for f in (load_form(os.path.join(FORMS, n)) for n in sorted(os.listdir(FORMS))
                         if n.endswith(".sofab.yaml")) if f] + [probe_ref_form()]
    if a.only:
        forms = [f for f in forms if f["name"] in a.only]
    langs = a.lang or LANGS
    partial = bool(a.only or a.lang)

    rows, report = run(forms, langs)

    width = max(len(f["name"]) for f in forms)
    print(f"{'form'.ljust(width)}  ir     " + " ".join(l[:6].ljust(6) for l in langs))
    by = {(r[0], r[1]): r for r in rows}
    for f in forms:
        cells = [by[(f["name"], "ir")][2][:6].ljust(6) if (f["name"], "ir") in by else "      "]
        for l in langs:
            g = by[(f["name"], l)][2]
            cells.append(g.split()[0][:6].ljust(6))
        print(f"{f['name'].ljust(width)}  " + " ".join(cells))

    if a.verbose or a.report:
        for (form, lang), (grade, ren, hunks) in sorted(report.items()):
            if grade == "IDENTICAL":
                continue
            print(f"\n--- {form} [{lang}] {grade}")
            for k, v in sorted(ren.items()):
                print(f"    rename {k} -> {v}")
            for cls, path, text in hunks:
                print(f"    {cls} {text}   [{path}]")

    bad = [r for r in rows if not r[4]]
    for form, lang, grade, detail, _ in bad:
        print(f"FAIL {form} [{lang}] {grade}: {detail}")

    if a.report:
        return 0
    text = baseline_text(report)
    if a.update:
        if partial:
            print("error: --update needs the full set (no --only/--lang)", file=sys.stderr)
            return 2
        with open(BASELINE, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(BASELINE, ROOT)}")
        return 1 if bad else 0
    old = open(BASELINE, encoding="utf-8").read() if os.path.exists(BASELINE) else ""
    if partial:                                      # --only / --lang: the cells that ran, block by block
        def blocks(t):
            out, key = {}, None
            for line in t.splitlines():
                if line and not line.startswith((" ", "#")):
                    key = tuple(line.split()[:2])
                    out[key] = [line]
                elif key and line.startswith(" "):
                    out[key].append(line)
            return out
        was, now = blocks(old), blocks(text)
        changed = [k for k in now if was.get(k) != now[k]]
        for k in changed:
            print("\n".join(difflib.unified_diff(was.get(k, []), now[k], "baseline", "now", lineterm="", n=1)))
        if changed:
            print(f"FAIL {len(changed)} cell(s) differ from the baseline")
            return 1
    else:
        if old != text:
            diff = difflib.unified_diff(old.splitlines(), text.splitlines(), "baseline", "now", lineterm="", n=1)
            print("\n".join(list(diff)[:80]))
            print("FAIL the $ref codegen residuals changed — inspect, then "
                  "`python3 scripts/check-ref-codegen.py --update` and commit the baseline")
            return 1
    print(f"{len(rows)} cells, {len(bad)} failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
