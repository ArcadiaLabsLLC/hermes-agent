#!/usr/bin/env python3
"""Which fork code still leans on an upstream name the last merged release retired.

Read against the PURE release tag, never the fork tree: in the fork tree a fork edit
keeps a dead upstream name alive, so the question "does upstream still have it?"
can only be answered from the tag's own blobs. The tag is the upstream manifest's
base (``tests/fixtures/upstream_manifest.txt``, ``# base <sha>``), which every
release merge re-bases, so the scan follows the merge with no edit of its own.

Four arms (row "Stale fork tests", ``fork-hygiene-queue.md``, 2026-10-18):

  imports    fork imports and patch targets of upstream modules and names that the
             tag does not have (gated: ``tests/tooling/test_upstream_retirement_scan.py``)
  hunks      fork hunks in upstream files whose enclosing upstream function the tag
             rewrote or removed since the previous merged release
  twins      fork functions whose body matches an upstream function added since the
             fork point (a fork re-implementation of something upstream now ships)
  carried    carried-PR hunks (``tests/fixtures/carried_prs.json``) the tag now contains

  python scripts/upstream_retirement_scan.py                 # every arm, text
  python scripts/upstream_retirement_scan.py --arm imports   # one arm
  python scripts/upstream_retirement_scan.py --json          # machine rows

Arm ``imports`` needs only objects every clone of ``main`` has (the tag is merged).
Arms ``hunks`` / ``twins`` need the previous release and the fork point (also
ancestors of ``main``); ``carried`` needs the PR heads fetched
(``scripts/check_carried_prs.py --fetch-commands``) and reports ``unfetched`` otherwise.
Exit status: 0 always for a report; the gate decides what is red.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import difflib
import json
import re
import subprocess
import sys
import warnings
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tests" / "fixtures" / "upstream_manifest.txt"
CARRIED = ROOT / "tests" / "fixtures" / "carried_prs.json"
RELEASE_MERGE = re.compile(r"^merge: upstream (v\d+\.\d+\.\d+) into main")
PATCH_CALLS = frozenset({"patch", "setattr", "delattr"})
OBJECT_CALLS = frozenset({"object", "setattr", "delattr"})
BUILTIN_NAMES = frozenset(dir(builtins))
TWIN_RATIO = 0.9
TWIN_MIN_NODES = 40


@dataclass(frozen=True)
class Finding:
    arm: str
    kind: str
    path: str
    line: int
    target: str
    detail: str = ""

    def render(self) -> str:
        tail = f" — {self.detail}" if self.detail else ""
        return f"{self.arm}:{self.kind} {self.path}:{self.line} {self.target}{tail}"


# ---------------------------------------------------------------- git and trees


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="surrogateescape", check=False)
    if check and result.returncode != 0:
        raise SystemExit(f"[retire] git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def manifest_base(path: Path = MANIFEST) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    match = re.match(r"# base ([0-9a-f]+)", first)
    if not match:
        raise SystemExit(f"[retire] {path} carries no '# base <sha>' header")
    return _git("rev-parse", "--verify", match[1] + "^{commit}").strip()


def previous_release(tag: str) -> str | None:
    """The release merged before ``tag``: the second-newest release merge on main's first parents."""
    log = _git("log", "--first-parent", "--merges", "--format=%H %s", "HEAD")
    seen = []
    for line in log.splitlines():
        sha, _, subject = line.partition(" ")
        if RELEASE_MERGE.match(subject):
            seen.append(_git("rev-parse", sha + "^2").strip())
    later = [sha for sha in seen if sha != tag]
    return later[0] if later else None


def fork_point(tag: str) -> str:
    """The newest first-parent commit of HEAD that is still an ancestor of ``tag``."""
    chain = _git("rev-list", "--first-parent", "--reverse", "HEAD").split()
    lo, hi = 0, len(chain) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _is_ancestor(chain[mid], tag):
            lo = mid
        else:
            hi = mid
    return chain[lo]


def _is_ancestor(commit: str, of: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, of],
                          capture_output=True, check=False).returncode == 0


class Tree:
    """One commit's paths and blobs, read through one ``cat-file --batch`` process."""

    def __init__(self, ref: str):
        self.ref = ref
        listing = _git("-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", ref)
        self.paths = frozenset(listing.splitlines())
        self.dirs = frozenset(str(Path(p).parent).replace("\\", "/") for p in self.paths)

    def read(self, path: str) -> str | None:
        if path not in self.paths:
            return None
        return _blob(self.ref, path)

    def module_path(self, module: str) -> str | None:
        """The file (or namespace directory) ``module`` names in this tree."""
        base = module.replace(".", "/")
        for candidate in (base + ".py", base + "/__init__.py"):
            if candidate in self.paths:
                return candidate
        return base + "/" if base in self.dirs else None


class _BlobReader:
    """One long-lived ``git cat-file --batch``: a blob per round trip, not a process per blob."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def __call__(self, ref: str, path: str) -> str:
        if self._proc is None:
            self._proc = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._proc.stdin.write(f"{ref}:{path}\n".encode())
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().split()
        if len(header) < 3 or header[1] == b"missing":
            return ""
        data = self._proc.stdout.read(int(header[2]) + 1)[:-1]
        return data.decode("utf-8", errors="replace")


_READER = _BlobReader()


@lru_cache(maxsize=None)
def _blob(ref: str, path: str) -> str:
    return _READER(ref, path)


class WorkTree:
    """The checkout as a tree: tracked paths, read from disk."""

    def __init__(self):
        self.ref = "WORKTREE"
        self.paths = frozenset(_git("-c", "core.quotepath=off", "ls-files").splitlines())
        self.dirs = frozenset(str(Path(p).parent).replace("\\", "/") for p in self.paths)

    def read(self, path: str) -> str | None:
        try:
            return (ROOT / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    module_path = Tree.module_path


def _parse(source: str | None) -> ast.Module | None:
    if source is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # an upstream file's invalid escape is not ours
            return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


# ---------------------------------------------------------------- names a module binds

_OPEN_BINDERS = (ast.If, ast.Try, ast.With, ast.For)


def bound_names(tree: ast.Module | None) -> frozenset[str] | None:
    """Top-level names a module binds; ``None`` when it binds dynamically (``*``, ``__getattr__``)."""
    if tree is None:
        return None
    names: set[str] = set()
    for node in _top_statements(tree.body):
        dynamic = _bind(node, names)
        if dynamic:
            return None
    return frozenset(names)


def _top_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for node in body:
        yield node
        if isinstance(node, _OPEN_BINDERS):
            nested = [*node.body, *getattr(node, "orelse", []), *getattr(node, "finalbody", [])]
            for handler in getattr(node, "handlers", []):
                nested.extend(handler.body)
            yield from _top_statements(nested)


def _bind(node: ast.stmt, names: set[str]) -> bool:
    """Add what ``node`` binds to ``names``; True when the binding is dynamic."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
        return node.name == "__getattr__"
    if isinstance(node, ast.Expr):
        return _exports_namespace(node.value)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            if alias.name == "*":
                return True
            names.add((alias.asname or alias.name).split(".")[0])
        return False
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
    for target in targets:
        if target is not None:
            names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return False


def _exports_namespace(node: ast.expr) -> bool:
    """A call handed ``globals()`` or ``sys.modules[__name__]`` binds names no parse can list."""
    if not isinstance(node, ast.Call):
        return False
    return any(_is_namespace(arg) for arg in node.args)


def _is_namespace(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):
        return getattr(node.func, "id", "") == "globals"
    return isinstance(node, ast.Subscript) and ast.unparse(node) == "sys.modules[__name__]"


# ---------------------------------------------------------------- arm 1: imports


@dataclass(frozen=True)
class Ref:
    path: str
    line: int
    module: str
    name: str | None
    via: str


def fork_python_files(head: WorkTree, tag: Tree) -> list[str]:
    return sorted(p for p in head.paths if p.endswith(".py") and p not in tag.paths
                  and not p.startswith(("docs/", "Harness_Brain/")))


def references(path: str, tree: ast.Module) -> list[Ref]:
    """Absolute imports, relative imports and patch targets in one fork file."""
    package = path.rsplit("/", 1)[0].replace("/", ".") if "/" in path else ""
    collector = _RefCollector(path, package)
    collector.visit(tree)
    return collector.refs


class _RefCollector(ast.NodeVisitor):
    def __init__(self, path: str, package: str):
        self.path, self.package = path, package
        self.refs: list[Ref] = []
        self.aliases: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.refs.append(Ref(self.path, node.lineno, alias.name, None, "import"))
            if alias.asname:
                self.aliases[alias.asname] = alias.name
            else:
                self.aliases.setdefault(alias.name.split(".")[0], alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = self._absolute(node)
        if module is None:
            return
        for alias in node.names:
            if alias.name != "*":
                self.refs.append(Ref(self.path, node.lineno, module, alias.name, "from"))
                self.aliases[alias.asname or alias.name] = f"{module}.{alias.name}"

    def visit_Call(self, node: ast.Call) -> None:
        target = self._patch_target(node)
        if target:
            module, _, name = target.rpartition(".")
            self.refs.append(Ref(self.path, node.lineno, module, name, "patch"))
        self.generic_visit(node)

    def _absolute(self, node: ast.ImportFrom) -> str | None:
        if not node.level:
            return node.module
        parts = self.package.split(".") if self.package else []
        if node.level - 1 > len(parts):
            return None
        base = parts[: len(parts) - (node.level - 1)]
        return ".".join([*base, *([node.module] if node.module else [])]) or None

    def _patch_target(self, node: ast.Call) -> str | None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        args = node.args
        if name in PATCH_CALLS and args and _is_str(args[0]) and "." in args[0].value:
            return args[0].value
        if name in OBJECT_CALLS and len(args) >= 2 and _is_str(args[1]):
            owner = self._owner(args[0])
            return f"{owner}.{args[1].value}" if owner else None
        return None

    def _owner(self, node: ast.expr) -> str | None:
        if not isinstance(node, (ast.Name, ast.Attribute)):
            return None
        dotted = ast.unparse(node)
        head, _, rest = dotted.partition(".")
        bound = self.aliases.get(head)
        return None if bound is None else ".".join(filter(None, (bound, rest)))


def _is_str(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class ImportArm:
    """Resolve every fork reference into an upstream module against the tag."""

    def __init__(self, head: WorkTree, tag: Tree, history: Iterable[Tree] = ()):
        self.head, self.tag, self.history = head, tag, tuple(history)
        self.tops = {p.split("/")[0].removesuffix(".py") for p in tag.paths if p.endswith(".py")}
        self._names: dict[str, frozenset[str] | None] = {}
        self._deleted: frozenset[str] | None = None

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        for path in fork_python_files(self.head, self.tag):
            tree = _parse(self.head.read(path))
            if tree is None:
                continue
            for ref in references(path, tree):
                finding = self.judge(ref)
                if finding:
                    findings.append(finding)
        return sorted(set(findings), key=lambda f: (f.path, f.line, f.target))

    def judge(self, ref: Ref) -> Finding | None:
        if ref.module.split(".")[0] not in self.tops:
            return None
        module, name = self._split(ref)
        if module is None:
            return self._module_gone(ref)
        if name is None or name in BUILTIN_NAMES or self._has(module, name):
            return None
        return self._name_gone(ref, module, name)

    def _split(self, ref: Ref) -> tuple[str | None, str | None]:
        """The longest prefix of the dotted target that is a module at the tag, and the name after it."""
        parts = ref.module.split(".") + ([ref.name] if ref.name else [])
        for cut in range(len(parts), 0, -1):
            module = ".".join(parts[:cut])
            if self.tag.module_path(module):
                rest = parts[cut:]
                return module, (rest[0] if rest else None)
        return None, None

    def _has(self, module: str, name: str) -> bool:
        if self.tag.module_path(f"{module}.{name}"):
            return True
        names = self._module_names(module)
        return names is None or name in names

    def _module_names(self, module: str) -> frozenset[str] | None:
        if module not in self._names:
            path = self.tag.module_path(module)
            if path.endswith("/"):
                self._names[module] = frozenset(
                    p[len(path):].split("/")[0].removesuffix(".py") for p in self.tag.paths if p.startswith(path))
            else:
                self._names[module] = bound_names(_parse(self.tag.read(path)))
        return self._names[module]

    def _module_gone(self, ref: Ref) -> Finding | None:
        dotted = ref.module + (f".{ref.name}" if ref.name and ref.via != "from" else "")
        head_path = self._head_module(dotted)
        if head_path and head_path not in self.tag.paths and not self._was_upstream(head_path):
            return None  # a fork-owned module under an upstream package
        kind = "module-retired" if head_path else "module-missing"
        return Finding("imports", kind, ref.path, ref.line, dotted, ref.via)

    def _head_module(self, dotted: str) -> str | None:
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            path = self.head.module_path(".".join(parts[:cut]))
            if path:
                return path
        return None

    def _was_upstream(self, path: str) -> bool:
        """Did upstream ever ship ``path`` and delete it before the tag? One history walk, cached."""
        if self._deleted is None:
            listing = _git("log", "--diff-filter=D", "--name-only", "--format=", self.tag.ref, "--", "*.py")
            self._deleted = frozenset(listing.split())
        stem = path.rstrip("/")
        return path in self._deleted or any(p.startswith(stem + "/") for p in self._deleted)

    def _name_gone(self, ref: Ref, module: str, name: str) -> Finding | None:
        path = self.tag.module_path(module)
        head_names = bound_names(_parse(self.head.read(path)))
        in_head = head_names is None or name in head_names or self.head.module_path(f"{module}.{name}")
        if in_head and not self._ever_upstream(module, path, name):
            return None  # a name the fork's own edit adds: footprint, not retirement
        kind = "name-retired" if in_head else "name-missing"
        return Finding("imports", kind, ref.path, ref.line, f"{module}:{name}", ref.via)

    def _ever_upstream(self, module: str, path: str, name: str) -> bool:
        """Upstream had ``module.name`` (a binding or a submodule) at the fork point or the previous release."""
        return any(tree.module_path(f"{module}.{name}") or name in (bound_names(_parse(tree.read(path))) or ())
                   for tree in self.history)


# ---------------------------------------------------------------- arm 2: hunks


def functions(tree: ast.Module | None) -> dict[str, ast.AST]:
    """``qualname -> node`` for every function and method."""
    found: dict[str, ast.AST] = {}
    if tree is None:
        return found

    def walk(body: Iterable[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{node.name}"
                if not isinstance(node, ast.ClassDef):
                    found[qual] = node
                walk(node.body, qual + ".")
    walk(tree.body, "")
    return found


def _shape(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def enclosing(funcs: dict[str, ast.AST], line: int) -> str | None:
    best = None
    for qual, node in funcs.items():
        if node.lineno <= line <= (node.end_lineno or node.lineno):
            if best is None or node.lineno >= funcs[best].lineno:
                best = qual
    return best


def changed_lines(base: str, path: str) -> list[int]:
    diff = _git("diff", "-U0", "--no-color", base, "--", path)
    lines = []
    for match in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(match[1]), int(match[2] or 1)
        lines.extend(range(start, start + max(count, 1)))
    return lines


def hunk_arm(head: WorkTree, tag: Tree, prev: Tree) -> list[Finding]:
    edited = _git("diff", "--name-only", tag.ref, "--", "*.py").splitlines()
    findings: set[Finding] = set()
    for path in (p for p in edited if p in tag.paths):
        head_funcs = functions(_parse(head.read(path)))
        tag_funcs = functions(_parse(tag.read(path)))
        prev_funcs = functions(_parse(prev.read(path)))
        for line in changed_lines(tag.ref, path):
            qual = enclosing(head_funcs, line)
            kind = _hunk_kind(qual, tag_funcs, prev_funcs)
            if kind:
                findings.add(Finding("hunks", kind, path, head_funcs[qual].lineno, qual))
    return sorted(findings, key=lambda f: (f.path, f.line))


def _hunk_kind(qual: str | None, tag_funcs: dict, prev_funcs: dict) -> str | None:
    if qual is None or qual not in prev_funcs:
        return None  # module level, or a function the fork added
    if qual not in tag_funcs:
        return "removed-by-tag"
    return "rewritten-by-tag" if _shape(tag_funcs[qual]) != _shape(prev_funcs[qual]) else None


# ---------------------------------------------------------------- arm 3: twins


def _body_key(node: ast.AST) -> str:
    body = list(getattr(node, "body", []))
    if body and isinstance(body[0], ast.Expr) and _is_str(body[0].value):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def _size(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def upstream_additions(tag: Tree, point: Tree) -> dict[str, tuple[str, str]]:
    """``body -> (path, qualname)`` for functions upstream added between the fork point and the tag."""
    changed = _git("diff", "--name-only", "--diff-filter=AM", point.ref, tag.ref, "--", "*.py").splitlines()
    added: dict[str, tuple[str, str]] = {}
    for path in changed:
        before = functions(_parse(point.read(path)))
        for qual, node in functions(_parse(tag.read(path))).items():
            if qual not in before and _size(node) >= TWIN_MIN_NODES:
                added[_body_key(node)] = (path, qual)
    return added


def fork_functions(head: WorkTree, tag: Tree) -> Iterator[tuple[str, str, ast.AST]]:
    for path in fork_python_files(head, tag):
        if path.startswith("tests/"):
            continue
        for qual, node in functions(_parse(head.read(path))).items():
            if _size(node) >= TWIN_MIN_NODES:
                yield path, qual, node


def twin_arm(head: WorkTree, tag: Tree, point: Tree) -> list[Finding]:
    added = upstream_additions(tag, point)
    by_name: dict[str, list[tuple[str, str, str]]] = {}
    for body, (path, qual) in added.items():
        by_name.setdefault(qual.rsplit(".", 1)[-1], []).append((body, path, qual))
    findings = []
    for path, qual, node in fork_functions(head, tag):
        body = _body_key(node)
        match = added.get(body)
        kind = "identical" if match else None
        if not match:
            match, kind = _near_twin(body, by_name.get(qual.rsplit(".", 1)[-1], ()))
        if match:
            findings.append(Finding("twins", kind, path, node.lineno, qual, f"upstream {match[0]}::{match[1]}"))
    return findings


def _near_twin(body: str, candidates: Iterable[tuple[str, str, str]]) -> tuple[tuple[str, str] | None, str | None]:
    for other, path, qual in candidates:
        if difflib.SequenceMatcher(None, body, other, autojunk=False).ratio() >= TWIN_RATIO:
            return (path, qual), "same-name-near"
    return None, None


# ---------------------------------------------------------------- arm 4: carried


def carried_arm(tag: Tree, manifest: Path = CARRIED) -> list[Finding]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_carried_prs import added_blocks, contains_lines

    data = json.loads(manifest.read_text(encoding="utf-8"))
    findings = []
    for number, entry in sorted(data["prs"].items(), key=lambda item: int(item[0])):
        head, base = entry["reviewed_head"], entry["reviewed_base"]
        if not (_has_commit(head) and _has_commit(base)):
            findings.append(Finding("carried", "unfetched", f"#{number}", 0, entry["head_ref"]))
            continue
        merged = _is_ancestor(head, tag.ref)
        for path, rule in sorted(entry["files"].items()):
            patch = _git("diff", base, head, "--", rule.get("pr_path", path), check=False)
            blocks = [b for b in added_blocks(patch) if sum(len(x.strip()) for x in b) >= 20]
            lines = (tag.read(path) or "").splitlines()
            held = sum(1 for b in blocks if contains_lines(lines, "\n".join(b)))
            if blocks and (merged or held == len(blocks)):
                kind = "merged" if merged else "upstream-has-it"
                findings.append(Finding("carried", kind, path, 0, f"#{number}", f"{held}/{len(blocks)} blocks at tag"))
    return findings


def _has_commit(sha: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", sha + "^{commit}"],
                          capture_output=True, check=False).returncode == 0


# ---------------------------------------------------------------- driver


@dataclass
class Pins:
    tag: str
    prev: str | None = None
    point: str | None = None
    notes: list[str] = field(default_factory=list)


def _arm_imports(pins: Pins) -> list[Finding]:
    pins.prev = pins.prev or previous_release(pins.tag)
    pins.point = pins.point or fork_point(pins.tag)
    history = [Tree(ref) for ref in (pins.point, pins.prev) if ref]
    return ImportArm(WorkTree(), Tree(pins.tag), history).run()


def _arm_hunks(pins: Pins) -> list[Finding]:
    pins.prev = pins.prev or previous_release(pins.tag)
    if not pins.prev:
        pins.notes.append("hunks: no previous release merge found; arm skipped")
        return []
    return hunk_arm(WorkTree(), Tree(pins.tag), Tree(pins.prev))


def _arm_twins(pins: Pins) -> list[Finding]:
    pins.point = pins.point or fork_point(pins.tag)
    return twin_arm(WorkTree(), Tree(pins.tag), Tree(pins.point))


def _arm_carried(pins: Pins) -> list[Finding]:
    return carried_arm(Tree(pins.tag))


ARMS: dict[str, Callable[[Pins], list[Finding]]] = {
    "imports": _arm_imports,
    "hunks": _arm_hunks,
    "twins": _arm_twins,
    "carried": _arm_carried,
}


def scan(arms: Iterable[str], pins: Pins) -> dict[str, list[Finding]]:
    return {arm: ARMS[arm](pins) for arm in arms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arm", action="append", choices=sorted(ARMS), help="repeatable; default every arm")
    parser.add_argument("--tag", help="the release commit (default: the upstream manifest's base)")
    parser.add_argument("--prev", help="the previously merged release (default: read from main's release merges)")
    parser.add_argument("--fork-point", help="default: newest first-parent commit of HEAD inside the tag")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tag = _git("rev-parse", "--verify", args.tag + "^{commit}").strip() if args.tag else manifest_base()
    pins = Pins(tag=tag, prev=args.prev, point=args.fork_point)
    results = scan(args.arm or list(ARMS), pins)
    if args.json:
        print(json.dumps({"pins": asdict(pins), "arms": {a: [asdict(f) for f in fs] for a, fs in results.items()}},
                         indent=1))
        return 0
    print(f"[retire] tag {pins.tag[:10]} prev {(pins.prev or '-')[:10]} fork-point {(pins.point or '-')[:10]}")
    for arm, found in results.items():
        print(f"== {arm}: {len(found)}")
        for finding in found:
            print("  " + finding.render())
    for note in pins.notes:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
