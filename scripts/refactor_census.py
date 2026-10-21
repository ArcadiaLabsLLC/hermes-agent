import ast, glob, re, os, io, json, tokenize, hashlib, collections, sys

ROOT = "."
FILES = [l.strip() for l in open(sys.argv[1], encoding="utf-8-sig") if l.strip()]
PY_FILES = [f.replace("\\", "/") for f in glob.glob("**/*.py", recursive=True)
            if not any(seg in f.replace("\\", "/").split("/") for seg in (".venv", "node_modules", "site-packages", "__pycache__", "_worktrees", "worktrees"))]
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# ---------- code-line counter (two variants, to match the operator's table) ----------
def code_lines(path):
    src = open(path, encoding="utf-8-sig", errors="ignore").read()
    raw = src.count("\n") + (0 if src.endswith("\n") else 1)
    # variant A: non-blank, non-comment (docstrings count)
    a = sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith("#"))
    # variant B: tokenize-based, excludes comments, blank lines AND standalone string statements (docstrings)
    try:
        tree = ast.parse(src)
        doc_lines = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) and isinstance(n.body[0].value.value, str):
                doc_lines.update(range(n.body[0].lineno, n.body[0].end_lineno + 1))
        b = sum(1 for i, l in enumerate(src.splitlines(), 1) if l.strip() and not l.strip().startswith("#") and i not in doc_lines)
    except SyntaxError:
        b = -1
    return raw, a, b

# ---------- token index ----------
tokens = {}
for f in PY_FILES:
    try:
        tokens[f] = set(IDENT.findall(open(f, encoding="utf-8-sig", errors="ignore").read()))
    except Exception:
        tokens[f] = set()
is_test = lambda f: f.startswith("tests/") or "/tests/" in f or os.path.basename(f).startswith("test_")


def in_module_seams(path="tests/_downstream/_seams.py"):
    """``IN_MODULE_SEAMS`` from the seams module, read by AST (never imported: it imports the tree).

    Plan l5-17-test-only-names (bucket B): a seam kept in its production module by ruling is
    reached by tests on purpose, so it is counted as ``seam``, not offered as a test-only DECIDE.
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8-sig").read())
    except (OSError, SyntaxError):
        return set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "IN_MODULE_SEAMS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


SEAMS = in_module_seams()

# ---------- dead-code census ----------
#: Decorators that WRAP a function and leave it called by its own name, so a
#: name search judges it like an undecorated def. Every other decorator is read
#: as a registration (singledispatch ``.register``, ``@method``, routes,
#: ``@property``, ``@doctor_check``...) and its function is counted
#: ``decorated``, not offered. Closed list on purpose: an unknown decorator
#: defaults to "reached", the direction that cannot invent a DEAD row.
TRANSPARENT_DECORATORS = frozenset({
    "contextmanager", "asynccontextmanager", "lru_cache", "cache", "wraps",
    "staticmethod", "classmethod", "abstractmethod", "overload", "singledispatch",
    "dataclass", "total_ordering", "final",
})


def _decorator_name(node):
    """The last dotted segment of a decorator, call or not (``functools.lru_cache(maxsize=1)`` -> ``lru_cache``)."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def is_registered(node):
    """Is ``node`` reached through a registering decorator rather than by its name?"""
    return any(_decorator_name(d) not in TRANSPARENT_DECORATORS for d in node.decorator_list)


dead = {}
for f in FILES:
    if not f.endswith(".py"):
        continue
    src = open(f, encoding="utf-8-sig").read()
    tree = ast.parse(src)
    names = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # A function behind a REGISTERING decorator is reached through it, never by its
            # own name: counted as `decorated`, not offered (L5.17: 46 of 60). A wrapping
            # decorator (`@contextmanager`, `@lru_cache`) hides nothing: judged by name.
            top_kind = "decorated" if not isinstance(n, ast.ClassDef) and is_registered(n) else type(n).__name__
            names.append((n.name, top_kind, n.end_lineno - n.lineno + 1))
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (m.name.startswith("__") and m.name.endswith("__")):
                        names.append((n.name + "." + m.name, "decorated" if is_registered(m) else "method", m.end_lineno - m.lineno + 1))
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.append((t.id, "const", n.end_lineno - n.lineno + 1))
    own_tokens = tokens.get(f, set())
    # count references of the bare name INSIDE the file beyond its definition(s)
    own_count = collections.Counter(IDENT.findall(src))
    names = [(name, "seam" if f"{f}::{name}" in SEAMS else kind, span) for name, kind, span in names]
    rows = []
    for name, kind, span in names:
        bare = name.split(".")[-1]
        prod = [g for g in PY_FILES if g != f and not is_test(g) and bare in tokens[g]]
        test = [g for g in PY_FILES if is_test(g) and bare in tokens[g]]
        internal = own_count[bare] - 1  # minus the def itself
        rows.append({"name": name, "kind": kind, "span": span, "prod_files": len(prod), "test_files": len(test), "internal_refs": internal})
    dead[f] = rows

# ---------- duplicate-body census (functions, methods, nested) ----------
def norm_hash(node):
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return None, 0
    clone = ast.FunctionDef(name="_", args=node.args, body=body, decorator_list=[], returns=None, type_comment=None)
    ast.fix_missing_locations(clone)
    txt = ast.unparse(clone)
    lines = txt.count("\n") + 1
    return hashlib.sha1(txt.encode()).hexdigest()[:12], lines

groups = collections.defaultdict(list)
same_name = collections.defaultdict(set)
scan = sorted(set(FILES) | {g for g in PY_FILES if not is_test(g) and (g.startswith("agent_runtime/") or g.startswith("hermes_cli/") or g.startswith("tools/") or g.startswith("agent/charsheet/"))})
for f in scan:
    if not f.endswith(".py"):
        continue
    try:
        tree = ast.parse(open(f, encoding="utf-8-sig").read())
    except SyntaxError:
        continue
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            h, ln = norm_hash(n)
            if h and ln >= 4:
                groups[h].append((f, n.name, n.lineno, ln))
            if n.name.startswith("_") and not n.name.startswith("__"):
                same_name[n.name].add(f)
dups = [v for v in groups.values() if len({x[0] for x in v}) >= 2 or len(v) >= 2]
dups.sort(key=lambda v: -v[0][3])
collisions = {k: sorted(v) for k, v in same_name.items() if len(v) >= 3}

# ---------- print ----------
print("=== CODE LINE COUNTER CHECK (raw / nonblank-noncomment / also-minus-docstrings) ===")
for f in FILES[:6]:
    if f.endswith(".py"):
        print(f, code_lines(f))
print()
print("=== DEAD-CODE CENSUS (per file: candidates with 0 prod refs outside the file) ===")
tot_dead = tot_testonly = tot_lines = 0
for f, rows in dead.items():
    candidates = [r for r in rows if r["kind"] not in ("decorated", "seam")]
    d = [r for r in candidates if r["prod_files"] == 0 and r["test_files"] == 0 and r["internal_refs"] == 0]
    t = [r for r in candidates if r["prod_files"] == 0 and r["test_files"] > 0 and r["internal_refs"] == 0]
    tot_dead += len(d); tot_testonly += len(t); tot_lines += sum(r["span"] for r in d)
    print(f"{f}: unreferenced={len(d)} ({sum(r['span'] for r in d)} lines) test-only={len(t)} ({sum(r['span'] for r in t)} lines) decorated-or-seam-not-judged={len(rows) - len(candidates)}")
    for r in d:
        print(f"    DEAD  {r['kind']:8} {r['name']}  [{r['span']}]")
    for r in t:
        print(f"    TEST  {r['kind']:8} {r['name']}  [{r['span']}]")
print(f"TOTAL unreferenced={tot_dead} ({tot_lines} lines), test-only={tot_testonly}")
print()
print(f"=== DUPLICATE BODIES ({len(dups)} groups, >=4 unparsed lines, across agent_runtime/hermes_cli/tools/charsheet) ===")
for v in dups[:80]:
    print(f"  [{v[0][3]} lines] " + " | ".join(f"{f}:{n}@{l}" for f, n, l, _ in v))
print()
print(f"=== SAME-NAME PRIVATE HELPERS defined in >=3 files ({len(collisions)}) ===")
for k, v in sorted(collisions.items(), key=lambda kv: -len(kv[1]))[:40]:
    print(f"  {k}: {len(v)} files: {', '.join(v)}")
json.dump({"dead": dead, "dups": dups, "collisions": collisions}, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
