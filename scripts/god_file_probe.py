#!/usr/bin/env python3
"""The god-file program's one instrument, and the census every Wave 0 gate reads.

Plan: ``docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md``
(§0.1, §2.4, Appendix A) and ``downstream-god-file-refactor.md`` §2 Wave 0.

The POPULATION is enumerated from the tree, never typed: a file is FORK
PRODUCTION iff git tracks it, it is not in the committed upstream manifest
(``tests/fixtures/upstream_manifest.txt``, the same fence ``[up-fp]`` reads, so
CI needs no ``upstream`` remote), it ends in ``.py``, and it is not a test —
``tests/`` is excluded except ``tests/_downstream/`` (fork code by the
program's scope rule) — nor under ``docs/``.

Every arm below is a pure function of that population, and each gate under
``tests/tooling/`` holds one arm to its grandfathered fixture:

  size       W0-G1  files over 800 CODE lines (non-blank, not ``#``-led;
                    docstrings count — ruling Q1)
  ladders    W0-G5  routing ladders on a string / an ``isinstance`` subject,
                    and compares against the members of a declared vocabulary
                    IN REACH (the declaring module and its importers)
  floor      W0-G7  functions over 150 lines or nested deeper than 4
  duplicates W0-G3  byte-identical bodies (alpha-renamed) and private helper
                    NAME collisions across modules
  layers     W0-G6  undeclared ``__layer__`` modules, parts importing
                    ``hermes_cli.harness``, ``_private`` upstream imports

Grandfathered fixtures only SHRINK: a site not in its fixture is NEW (red), a
listed site whose number rose GREW (red), a listed site that no longer violates
is STALE (red until its row is deleted); a number that fell but still violates
is legal and ``--write-fixtures`` lowers it.

  python scripts/god_file_probe.py                    # the §0.2 table (over 800 raw)
  python scripts/god_file_probe.py --min-lines 0 --counter code
  python scripts/god_file_probe.py --detail agent_runtime/store.py
  python scripts/god_file_probe.py --check            # every arm vs its fixture; exit 1 on drift
  python scripts/god_file_probe.py --write-fixtures   # lower fixtures; refuses NEW/GREW
  python scripts/god_file_probe.py --write-fixtures --bootstrap   # Wave 0 only
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tests" / "fixtures" / "upstream_manifest.txt"
FIXTURES = ROOT / "tests" / "fixtures"

CEILING_CODE_LINES = 800
MAX_FUNCTION_LINES = 150
MAX_NESTING = 4
MIN_DUPLICATE_BODY_LINES = 4
#: Rule 16's layers, lowest first. A module may import its own layer or lower.
LAYERS = ("models", "policy", "stores", "lanes", "wiring")
#: The trees W0-G6 walks (every module must declare its layer, or be grandfathered).
LAYERED_ROOTS = ("agent_runtime/", "hermes_cli/harness_parts/", "plugins/eternia-harness/")
HARNESS_PARTS = "hermes_cli/harness_parts/"

SIZE_FIXTURE = FIXTURES / "size_ceiling_grandfathered.json"
LADDER_FIXTURE = FIXTURES / "ladder_routing_grandfathered.json"
FLOOR_FIXTURE = FIXTURES / "legibility_grandfathered.json"
DUPLICATE_FIXTURE = FIXTURES / "duplicate_bodies_grandfathered.json"
LAYER_FIXTURE = FIXTURES / "import_layers_grandfathered.json"

_CONTROL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)
if sys.version_info >= (3, 11):
    _CONTROL = (*_CONTROL, ast.TryStar)
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


# ── population ──────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


@lru_cache(maxsize=None)
def upstream_paths(manifest: Path = MANIFEST) -> frozenset[str]:
    """Every path upstream owns (the manifest, minus its ``# base`` header)."""
    lines = manifest.read_text(encoding="utf-8").splitlines()
    return frozenset(line for line in lines if line and not line.startswith("#"))


def is_fork_production(path: str) -> bool:
    if not path.endswith(".py") or path.startswith("docs/"):
        return False
    return not path.startswith("tests/") or path.startswith("tests/_downstream/")


@lru_cache(maxsize=None)
def fork_production_files(root: Path = ROOT, manifest: Path = MANIFEST) -> tuple[str, ...]:
    """The population, from ``git ls-files`` minus the upstream manifest."""
    upstream = upstream_paths(manifest)
    tracked = _git(root, "ls-files", "-z", "--", "*.py").split("\0")
    return tuple(
        sorted(p for p in tracked if p and p not in upstream and is_fork_production(p) and (root / p).is_file())
    )


@lru_cache(maxsize=None)
def _source(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8", errors="replace")


@lru_cache(maxsize=None)
def _tree(root: Path, path: str) -> ast.Module | None:
    try:
        return ast.parse(_source(root, path), filename=path)
    except SyntaxError:
        return None


def raw_lines(source: str) -> int:
    return len(source.splitlines())


def code_lines(source: str) -> int:
    """The §0.1 counter: non-blank, not ``#``-led (docstrings count)."""
    return sum(1 for line in source.splitlines() if line.strip() and not line.strip().startswith("#"))


# ── function units ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Unit:
    path: str
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    module_level: bool

    @property
    def lines(self) -> int:
        return (self.node.end_lineno or self.node.lineno) - self.node.lineno + 1


def iter_units(path: str, tree: ast.Module) -> Iterator[Unit]:
    """Every function, method and nested function, with a dotted qualname."""

    def walk(body: list[ast.stmt], prefix: str, module_level: bool) -> Iterator[Unit]:
        for node in body:
            if isinstance(node, _FUNCS):
                name = f"{prefix}{node.name}"
                yield Unit(path, name, node, module_level)
                yield from walk(node.body, f"{name}.", False)
            elif isinstance(node, ast.ClassDef):
                yield from walk(node.body, f"{prefix}{node.name}.", False)
            else:
                for child in _child_bodies(node):
                    yield from walk(child, prefix, module_level)

    yield from walk(tree.body, "", True)


def _child_bodies(node: ast.AST) -> Iterator[list[ast.stmt]]:
    for field in ("body", "orelse", "finalbody"):
        value = getattr(node, field, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            yield value
    for handler in getattr(node, "handlers", []) or []:
        yield handler.body
    for case in getattr(node, "cases", []) or []:
        yield case.body


def nesting_depth(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Deepest control-block nesting inside one function (nested defs are their own unit).

    ``elif`` is not nesting: an ``If`` that is its parent's sole ``orelse`` sits
    at the parent's depth.
    """

    def depth(body: list[ast.stmt], level: int) -> int:
        deepest = level
        for stmt in body:
            if isinstance(stmt, (*_FUNCS, ast.ClassDef)) or not isinstance(stmt, _CONTROL):
                continue
            inner = level + 1
            deepest = max(deepest, inner)
            if isinstance(stmt, ast.If):
                deepest = max(deepest, depth(stmt.body, inner))
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    deepest = max(deepest, depth(stmt.orelse, level))
                else:
                    deepest = max(deepest, depth(stmt.orelse, inner))
            else:
                for child in _child_bodies(stmt):
                    deepest = max(deepest, depth(child, inner))
        return deepest

    return depth(node.body, 0)


# ── Appendix A: the §0.2 table ──────────────────────────────────────────────


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_str_collection(node: ast.AST) -> bool:
    return isinstance(node, (ast.Tuple, ast.Set, ast.List)) and any(_is_str(e) for e in node.elts)


def routed(test: ast.AST) -> bool:
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and any(_is_str(c) or _is_str_collection(c) for c in node.comparators):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance":
            return True
    return False


def chains(tree: ast.AST) -> list[tuple[int, int, bool]]:
    """If-chains of >= 3 arms: ``(line, arms, routed)`` (Appendix A, verbatim semantics)."""
    orelse = {id(o) for n in ast.walk(tree) if isinstance(n, ast.If) for o in n.orelse if isinstance(o, ast.If)}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and id(node) not in orelse:
            arms, is_routed, cur = 1, routed(node.test), node
            while len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                cur = cur.orelse[0]
                arms += 1
                is_routed = is_routed or routed(cur.test)
            arms += bool(cur.orelse)
            if arms >= 3:
                out.append((node.lineno, arms, is_routed))
    return out


def file_row(root: Path, path: str) -> dict:
    source = _source(root, path)
    tree = _tree(root, path)
    row = {"path": path, "raw": raw_lines(source), "code": code_lines(source)}
    if tree is None:
        return row | {"defs": 0, "longest": ("<syntax error>", 0), "chains": 0, "routed": 0, "str_eq": 0, "isinstance": 0}
    top = [n for n in tree.body if isinstance(n, (*_FUNCS, ast.ClassDef))]
    units = list(iter_units(path, tree))
    longest = max(((u.qualname, u.lines) for u in units), key=lambda t: t[1], default=("-", 0))
    found = chains(tree)
    str_eq = sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, ast.Compare) and any(_is_str(c) for c in n.comparators)
    )
    isinst = sum(
        1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance"
    )
    return row | {
        "defs": len(top),
        "longest": longest,
        "chains": len(found),
        "routed": sum(1 for _, _, r in found if r),
        "str_eq": str_eq,
        "isinstance": isinst,
    }


# ── W0-G1: the size ceiling ─────────────────────────────────────────────────


def size_census(root: Path = ROOT) -> dict[str, int]:
    """``{path: code lines}`` for every fork production file over the ceiling."""
    out = {}
    for path in fork_production_files(root):
        count = code_lines(_source(root, path))
        if count > CEILING_CODE_LINES:
            out[path] = count
    return out


def size_ledger_line(root: Path = ROOT) -> str:
    census = size_census(root)
    raw_over = sum(1 for p in fork_production_files(root) if raw_lines(_source(root, p)) > CEILING_CODE_LINES)
    return (
        f"[ds-size] units={len(census)} total={sum(census.values())} ceiling={CEILING_CODE_LINES} "
        f"counter=code (raw-over={raw_over}, not bound — ruling Q1)"
    )


# ── W0-G5: ladder routing ───────────────────────────────────────────────────


def _subject(node: ast.AST) -> str | None:
    if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call)):
        return ast.unparse(node)
    return None


def _string_subjects(test: ast.AST) -> set[str]:
    """Names a test compares against a string constant (either side, ==/!=/in/not in)."""
    subjects = set()
    for node in ast.walk(test):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            continue
        left, right = node.left, node.comparators[0]
        if _is_str(right) or _is_str_collection(right):
            name = _subject(left)
        elif _is_str(left) and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            name = _subject(right)
        else:
            name = None
        if name:
            subjects.add(name)
    return subjects


def _isinstance_subjects(test: ast.AST) -> set[str]:
    subjects = set()
    for node in ast.walk(test):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and node.args
        ):
            name = _subject(node.args[0])
            if name:
                subjects.add(name)
    return subjects


def _chain(node: ast.If) -> tuple[list[ast.expr], list[list[ast.stmt]]]:
    """An if-chain's tests and every arm body (the trailing ``else`` included)."""
    tests, bodies, cur = [node.test], [node.body], node
    while len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
        cur = cur.orelse[0]
        tests.append(cur.test)
        bodies.append(cur.body)
    if cur.orelse:
        bodies.append(cur.orelse)
    return tests, bodies


def _ladders_in(body: list[ast.stmt]) -> Iterator[tuple[str, str, int]]:
    """``(kind, subject, arms)`` for every ladder whose arms are siblings in ``body``.

    Arms are counted across sibling ``If`` statements (return-terminated guards)
    AND down each one's ``elif`` chain, so a ladder is found whichever way it is
    spelled. Recurses into every nested body except nested function/class defs
    (those are their own units).
    """
    counts: dict[tuple[str, str], int] = defaultdict(int)
    nested: list[list[ast.stmt]] = []
    for stmt in body:
        if not isinstance(stmt, _CONTROL):  # a nested def is its own unit; a simple statement has no arms
            continue
        if not isinstance(stmt, ast.If):
            nested.extend(_child_bodies(stmt))
            continue
        tests, bodies = _chain(stmt)
        for test in tests:
            for name in _string_subjects(test):
                counts[("ladder", name)] += 1
            for name in _isinstance_subjects(test):
                counts[("isinstance", name)] += 1
        nested.extend(bodies)
    for (kind, name), arms in counts.items():
        if arms >= 3:
            yield kind, name, arms
    for child in nested:
        yield from _ladders_in(child)


def _vocabulary_strings(tree: ast.Module) -> set[str]:
    """Strings a module declares as a vocabulary: ``Final`` str collections and str Enum members."""
    found: set[str] = set()
    for node in tree.body:
        found |= _final_strings(node) | _enum_strings(node)
    return found


def _final_strings(node: ast.stmt) -> set[str]:
    """``NAME: Final[...] = ("a", "b")`` (or ``frozenset({...})``) -> its strings."""
    if not (isinstance(node, ast.AnnAssign) and node.value is not None and "Final" in ast.unparse(node.annotation)):
        return set()
    value = node.value
    if isinstance(value, ast.Call) and value.args:  # frozenset((...)) / tuple([...])
        value = value.args[0]
    if not isinstance(value, (ast.Tuple, ast.Set, ast.List)):
        return set()
    return {e.value for e in value.elts if _is_str(e)}


def _enum_strings(node: ast.stmt) -> set[str]:
    """A ``class X(str, Enum)`` / ``StrEnum`` -> its string member values."""
    if not isinstance(node, ast.ClassDef):
        return set()
    if not {ast.unparse(b).rsplit(".", 1)[-1] for b in node.bases} & {"Enum", "StrEnum"}:
        return set()
    return {stmt.value.value for stmt in node.body if isinstance(stmt, ast.Assign) and _is_str(stmt.value)}


def vocabulary(root: Path = ROOT) -> frozenset[str]:
    """The union of every fork vocabulary, enumerated from its declarations."""
    words: set[str] = set()
    for path in fork_production_files(root):
        tree = _tree(root, path)
        if tree is not None:
            words |= _vocabulary_strings(tree)
    return frozenset(w for w in words if w)


def visible_vocabularies(root: Path = ROOT) -> dict[str, frozenset[str]]:
    """``{path: words}`` — the vocabulary each module can SEE: its own declarations
    plus those of every fork module it imports (resolved, module-level or deferred).

    Scoped, not fork-wide (lane Q-RUNTIME 2026-09-25, the R3 finding): a union of
    every ``Final``/``Enum`` string read ``"none"`` in ``DiffScope`` or ``"absent"``
    in ``DemoteReason`` as a routed word in every module that happened to compare
    against the same common English word, so typed reasons (rule 14) could not be
    adopted for any vocabulary containing one. A compare is a routing on a
    vocabulary only where that vocabulary is in reach — the declaring module and
    its importers.
    """
    trees = {path: _tree(root, path) for path in fork_production_files(root)}
    declared = {
        module_name(path): frozenset(w for w in _vocabulary_strings(tree) if w)
        for path, tree in trees.items()
        if tree is not None
    }
    declared = {module: words for module, words in declared.items() if words}
    out: dict[str, frozenset[str]] = {}
    for path, tree in trees.items():
        if tree is None:
            continue
        seen: set[str] = set(declared.get(module_name(path), ()))
        for module, name, _ in imports_of(path, tree):
            for candidate in (f"{module}.{name}" if name else module, module):
                if candidate in declared:
                    seen |= declared[candidate]
                    break
        out[path] = frozenset(seen)
    return out


def _vocab_compares(node: ast.AST, words: frozenset[str]) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Compare) and len(child.ops) == 1 and isinstance(
            child.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
        ):
            for side in (child.left, *child.comparators):
                if _is_str(side) and side.value in words:
                    yield side.value
                elif isinstance(side, (ast.Tuple, ast.Set, ast.List)):
                    yield from (e.value for e in side.elts if _is_str(e) and e.value in words)


def _own_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """A function's statements, excluding nested defs (they are their own unit)."""
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (*_FUNCS, ast.ClassDef)):
            continue
        yield current
        stack.extend(
            c for c in ast.iter_child_nodes(current) if isinstance(c, ast.stmt)
        )


def ladder_census(root: Path = ROOT) -> dict[tuple[str, str, str, str], int]:
    """``{(path, function, kind, subject): arms}`` — kinds ``ladder`` / ``isinstance`` / ``vocab``.

    A ``vocab`` row counts only the vocabularies the module can see
    (:func:`visible_vocabularies`), never the fork-wide union.
    """
    visible = visible_vocabularies(root)
    out: dict[tuple[str, str, str, str], int] = {}
    for path in fork_production_files(root):
        tree = _tree(root, path)
        if tree is None:
            continue
        words = visible.get(path, frozenset())
        for unit in iter_units(path, tree):
            for kind, subject, arms in _ladders_in(unit.node.body):
                key = (path, unit.qualname, kind, subject)
                out[key] = max(out.get(key, 0), arms)
            for word, hits in _unit_vocab(unit, words).items():
                out[(path, unit.qualname, "vocab", word)] = hits
    return out


def _unit_vocab(unit: Unit, words: frozenset[str]) -> dict[str, int]:
    """How often one function compares against each vocabulary member (nested defs excluded)."""
    hits: dict[str, int] = defaultdict(int)
    exprs = (e for stmt in _own_statements(unit.node) for e in ast.iter_child_nodes(stmt) if isinstance(e, ast.expr))
    for expr in exprs:
        for word in _vocab_compares(expr, words):
            hits[word] += 1
    return hits


# ── W0-G7: the legibility floor ─────────────────────────────────────────────


def floor_census(root: Path = ROOT) -> dict[tuple[str, str], tuple[int, int]]:
    """``{(path, qualname): (lines, depth)}`` for every function over either limit."""
    out = {}
    for path in fork_production_files(root):
        tree = _tree(root, path)
        if tree is None:
            continue
        for unit in iter_units(path, tree):
            lines, depth = unit.lines, nesting_depth(unit.node)
            if lines > MAX_FUNCTION_LINES or depth > MAX_NESTING:
                out[(path, unit.qualname)] = (lines, depth)
    return out


# ── W0-G3: duplicate bodies and helper names ────────────────────────────────


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr) and _is_str(body[0].value):
        return body[1:]
    return body


def _bound_names(node: ast.AST) -> Iterator[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            yield child.id
        elif isinstance(child, ast.ExceptHandler) and child.name:
            yield child.name


def _rename_name(node: ast.Name, mapping: dict[str, str]) -> None:
    node.id = mapping.get(node.id, node.id)


def _rename_arg(node: ast.arg, mapping: dict[str, str]) -> None:
    if node.arg in mapping:
        node.arg = mapping[node.arg]
        node.annotation = None


def _rename_handler(node: ast.ExceptHandler, mapping: dict[str, str]) -> None:
    if node.name:
        node.name = mapping.get(node.name, node.name)


#: Alpha-renaming as a table: one renamer per node type that carries a bindable name.
_RENAMERS: dict[type, Callable[..., None]] = {
    ast.Name: _rename_name,
    ast.arg: _rename_arg,
    ast.ExceptHandler: _rename_handler,
}


def normalized_body_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Hash of a unit with name, annotations, parameters AND locals alpha-renamed.

    ``None`` when the docstring-stripped body renders under the minimum.
    """
    clone = ast.parse(ast.unparse(node)).body[0]
    assert isinstance(clone, _FUNCS)
    clone.body = _strip_docstring(clone.body)
    if not clone.body:
        return None
    rendered = "\n".join(ast.unparse(stmt) for stmt in clone.body)
    if len(rendered.splitlines()) < MIN_DUPLICATE_BODY_LINES:
        return None
    clone.name = "_"
    clone.returns = None
    clone.decorator_list = []
    args = clone.args
    mapping: dict[str, str] = {}
    for arg in (
        *args.posonlyargs,
        *args.args,
        *([args.vararg] if args.vararg else []),
        *args.kwonlyargs,
        *([args.kwarg] if args.kwarg else []),
    ):
        mapping.setdefault(arg.arg, f"_v{len(mapping)}")
        arg.annotation = None
    for name in _bound_names(clone):  # locals, in first-binding order
        mapping.setdefault(name, f"_v{len(mapping)}")
    for child in ast.walk(clone):
        renamer = _RENAMERS.get(type(child))
        if renamer is not None:
            renamer(child, mapping)
    return hashlib.sha256(ast.unparse(clone).encode()).hexdigest()[:16]


def duplicate_census(root: Path = ROOT) -> tuple[set[tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """``(body groups, name groups)``.

    A body group is the sorted ``path::qualname`` members of one normalized hash
    (>= 2 members). A name group is a private module-level helper (``_x``, not
    dunder) with a >= 4-line body defined in >= 2 modules: ``{name: paths}``.
    """
    bodies: dict[str, list[str]] = defaultdict(list)
    names: dict[str, set[str]] = defaultdict(set)
    for path in fork_production_files(root):
        tree = _tree(root, path)
        if tree is None:
            continue
        for unit in iter_units(path, tree):
            digest = normalized_body_hash(unit.node)
            if digest is None:
                continue
            bodies[digest].append(f"{path}::{unit.qualname}")
            name = unit.node.name
            if unit.module_level and name.startswith("_") and not name.startswith("__"):
                names[name].add(path)
    body_groups = {tuple(sorted(m)) for m in bodies.values() if len(m) > 1}
    name_groups = {n: tuple(sorted(p)) for n, p in names.items() if len(p) > 1}
    return body_groups, name_groups


# ── W0-G6: import layers ────────────────────────────────────────────────────


def module_name(path: str) -> str:
    stem = path[:-3]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def _resolve_from(path: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module_name(path).split(".")
    if not path.endswith("__init__.py"):
        package = package[:-1]
    package = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    return ".".join([*package, *([node.module] if node.module else [])])


def imports_of(path: str, tree: ast.Module) -> Iterator[tuple[str, str | None, int]]:
    """``(module, imported name or None, line)`` for every import, module-level or deferred."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(path, node)
            for alias in node.names:
                yield base, alias.name, node.lineno


def _top_assignment(tree: ast.Module, name: str) -> ast.expr | None:
    """The value a module binds to ``name`` at top level, or None when it binds nothing."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return value
    return None


def map_members(tree: ast.Module) -> set[str]:
    """Submodule stems a package ``__init__`` lists in a literal ``__layers__`` dict."""
    value = _top_assignment(tree, "__layers__")
    if not isinstance(value, ast.Dict):
        return set()
    return {k.value for k in value.keys if _is_str(k)}


def declares_layer(root: Path, path: str) -> bool:
    """ENUMERATION only: does the module bind ``__layer__``, or does its package map list it?

    The VALUE is never read from the source — the gate reads it at runtime
    (:func:`runtime_layer`), so a layer that is spelled but not bound does not count.
    """
    tree = _tree(root, path)
    if tree is not None and _top_assignment(tree, "__layer__") is not None:
        return True
    package_init = str(Path(path).parent.as_posix()) + "/__init__.py"
    if package_init == path or not (root / package_init).is_file():
        return False
    init_tree = _tree(root, package_init)
    return init_tree is not None and Path(path).stem in map_members(init_tree)


def load_module(root: Path, path: str):
    """Import a repo module at runtime (by file for a non-identifier path such as the plugin)."""
    import importlib
    import importlib.util

    dotted = module_name(path)
    if all(part.isidentifier() for part in dotted.split(".")):
        return importlib.import_module(dotted)
    spec = importlib.util.spec_from_file_location(dotted.replace("-", "_"), root / path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_layer(root: Path, path: str) -> str | None:
    """The layer a module is BOUND to at runtime: its ``__layer__``, else its package map's entry."""
    module = load_module(root, path)
    layer = getattr(module, "__layer__", None)
    if layer is not None:
        return layer
    package_init = str(Path(path).parent.as_posix()) + "/__init__.py"
    if (root / package_init).is_file() and package_init != path:
        table = getattr(load_module(root, package_init), "__layers__", None) or {}
        return table.get(Path(path).stem)
    return None


def _upstream_module_path(module: str, upstream: frozenset[str]) -> str | None:
    stem = module.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in upstream:
            return candidate
    return None


def is_private_upstream_import(root: Path, upstream: frozenset[str], module: str, name: str | None) -> bool:
    """``from <module> import <name>`` reaches a ``_private`` NAME of an upstream module.

    Not when ``<module>.<name>`` is itself a module — upstream's or the fork's
    (``from hermes_cli import _boot_clock`` imports the fork file
    ``hermes_cli/_boot_clock.py``; the underscore is its filename, not a private
    upstream name).
    """
    if not (name and name.startswith("_") and not name.startswith("__")):
        return False
    if not _upstream_module_path(module, upstream):
        return False
    submodule = root / module.replace(".", "/") / name
    if submodule.with_suffix(".py").is_file() or (submodule / "__init__.py").is_file():
        return False
    return not _upstream_module_path(f"{module}.{name}", upstream)


def layer_census(root: Path = ROOT, manifest: Path = MANIFEST) -> dict[str, list]:
    """The three W0-G6 populations, as sorted lists of rows.

    ``undeclared``: layered-root modules with no ``__layer__``.
    ``harness_imports``: ``path -> hermes_cli.harness`` imports from a part.
    ``private_upstream_imports``: ``path|module|name`` for a ``_private`` name
    imported from an upstream module.
    """
    upstream = upstream_paths(manifest)
    undeclared, harness_imports, private = set(), set(), set()
    for path in fork_production_files(root, manifest):
        tree = _tree(root, path)
        if tree is None:
            continue
        if path.startswith(LAYERED_ROOTS) and not declares_layer(root, path):
            undeclared.add(path)
        for module, name, _line in imports_of(path, tree):
            full = f"{module}.{name}" if name else module
            if path.startswith(HARNESS_PARTS) and (
                module == "hermes_cli.harness" or full == "hermes_cli.harness"
            ):
                harness_imports.add(f"{path}|{full}")
            if is_private_upstream_import(root, upstream, module, name):
                private.add(f"{path}|{module}|{name}")
    return {
        "undeclared": sorted(undeclared),
        "harness_imports": sorted(harness_imports),
        "private_upstream_imports": sorted(private),
    }


def layer_violations(layers: dict[str, str], imports: dict[str, Iterable[str]]) -> list[str]:
    """Upward imports among DECLARED modules: ``importer (layer) -> imported (layer)``.

    ``layers`` maps a dotted module to its bound layer (read at RUNTIME by the
    gate, so a value that only looks bound in the source does not count);
    ``imports`` maps a dotted module to the dotted modules it imports. An
    unknown layer value is itself a violation.
    """
    problems = []
    rank = {name: index for index, name in enumerate(LAYERS)}
    for module, layer in sorted(layers.items()):
        if layer not in rank:
            problems.append(f"{module}: __layer__ = {layer!r} is not one of {LAYERS}")
            continue
        for target in sorted(set(imports.get(module, ()))):
            candidates = [t for t in (target, target.rsplit(".", 1)[0]) if t in layers and t != module]
            for hit in candidates[:1]:
                if layers[hit] in rank and rank[layers[hit]] > rank[layer]:
                    problems.append(f"{module} ({layer}) imports {hit} ({layers[hit]}) — an upward import")
    return problems


def declared_modules(root: Path = ROOT) -> dict[str, str]:
    """``{path: dotted module}`` for every layered-root module that declares a layer."""
    return {
        path: module_name(path)
        for path in fork_production_files(root)
        if path.startswith(LAYERED_ROOTS) and declares_layer(root, path)
    }


def module_imports(root: Path, path: str) -> list[str]:
    tree = _tree(root, path)
    if tree is None:
        return []
    return [f"{m}.{n}" if n else m for m, n, _ in imports_of(path, tree)]


# ── fixtures: read, compare, write ──────────────────────────────────────────


@dataclass(frozen=True)
class Drift:
    gate: str
    new: list[str]
    grew: list[str]
    stale: list[str]

    @property
    def red(self) -> bool:
        return bool(self.new or self.grew or self.stale)

    def render(self) -> str:
        parts = [f"{self.gate}: {len(self.new)} NEW, {len(self.grew)} GREW, {len(self.stale)} STALE"]
        parts += [f"  NEW    {x}" for x in self.new]
        parts += [f"  GREW   {x}" for x in self.grew]
        parts += [f"  STALE  {x} (no longer violates — delete its row)" for x in self.stale]
        return "\n".join(parts)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def compare_numbers(gate: str, live: dict[str, tuple[int, ...]], fixture: dict[str, tuple[int, ...]]) -> Drift:
    """The shrink-only comparison every numeric arm shares."""
    new = sorted(k for k in live if k not in fixture)
    grew = sorted(
        f"{k}: {list(fixture[k])} -> {list(live[k])}"
        for k in live
        if k in fixture and any(a > b for a, b in zip(live[k], fixture[k]))
    )
    stale = sorted(k for k in fixture if k not in live)
    return Drift(gate, new, grew, stale)


def compare_sets(gate: str, live: set[str], fixture: set[str]) -> Drift:
    return Drift(gate, sorted(live - fixture), [], sorted(fixture - live))


def size_live(root: Path = ROOT) -> dict[str, tuple[int, ...]]:
    return {p: (n,) for p, n in size_census(root).items()}


def size_fixture(path: Path = SIZE_FIXTURE) -> dict[str, tuple[int, ...]]:
    return {p: (n,) for p, n in _read(path)["files"].items()}


def ladder_live(root: Path = ROOT) -> dict[str, tuple[int, ...]]:
    return {"|".join(k): (v,) for k, v in ladder_census(root).items()}


def ladder_fixture(path: Path = LADDER_FIXTURE) -> dict[str, tuple[int, ...]]:
    return {r["site"]: (r["arms"],) for r in _read(path)["sites"]}


def floor_live(root: Path = ROOT) -> dict[str, tuple[int, ...]]:
    return {f"{p}|{q}": v for (p, q), v in floor_census(root).items()}


def floor_fixture(path: Path = FLOOR_FIXTURE) -> dict[str, tuple[int, ...]]:
    return {r["unit"]: (r["lines"], r["depth"]) for r in _read(path)["functions"]}


def duplicate_live(root: Path = ROOT) -> tuple[set[str], set[str]]:
    bodies, names = duplicate_census(root)
    return {" == ".join(g) for g in bodies}, {f"{n}: {', '.join(p)}" for n, p in names.items()}


def duplicate_fixture(path: Path = DUPLICATE_FIXTURE) -> tuple[set[str], set[str]]:
    data = _read(path)
    return set(data["body_groups"]), set(data["name_groups"])


def layer_fixture(path: Path = LAYER_FIXTURE) -> dict[str, set[str]]:
    return {k: set(v) for k, v in _read(path).items() if isinstance(v, list)}


def all_drift(root: Path = ROOT) -> list[Drift]:
    out = [
        compare_numbers("W0-G1 size ceiling", size_live(root), size_fixture()),
        compare_numbers("W0-G5 ladder routing", ladder_live(root), ladder_fixture()),
        compare_numbers("W0-G7 legibility floor", floor_live(root), floor_fixture()),
    ]
    bodies, names = duplicate_live(root)
    fixture_bodies, fixture_names = duplicate_fixture()
    out.append(compare_sets("W0-G3 duplicate bodies", bodies, fixture_bodies))
    out.append(compare_sets("W0-G3 helper names", names, fixture_names))
    layers = layer_census(root)
    fixture_layers = layer_fixture()
    for key in ("undeclared", "harness_imports", "private_upstream_imports"):
        out.append(compare_sets(f"W0-G6 {key}", set(layers[key]), fixture_layers.get(key, set())))
    return out


def write_fixtures(root: Path = ROOT, *, bootstrap: bool = False) -> int:
    """Rewrite every fixture from the live census. Refuses NEW / GREW unless bootstrapping."""
    if not bootstrap:
        growth = [d for d in all_drift(root) if d.new or d.grew]
        if growth:
            for drift in growth:
                print(drift.render(), file=sys.stderr)
            print("refused: a fixture only shrinks — fix the NEW/GREW sites, do not baseline them", file=sys.stderr)
            return 1
    _write(SIZE_FIXTURE, {
        "ceiling": CEILING_CODE_LINES,
        "counter": "code lines: non-blank, not '#'-led, docstrings count (ruling Q1)",
        "files": dict(sorted(size_census(root).items())),
    })
    _write(LADDER_FIXTURE, {
        "kinds": "ladder = >=3 arms comparing one subject to strings; isinstance = >=3 isinstance arms on one "
                 "subject; vocab = compares against a declared Final/Enum vocabulary member (arms = count)",
        "sites": [{"site": k, "arms": v[0]} for k, v in sorted(ladder_live(root).items())],
    })
    _write(FLOOR_FIXTURE, {
        "max_depth": MAX_NESTING,
        "max_lines": MAX_FUNCTION_LINES,
        "functions": [{"unit": k, "lines": v[0], "depth": v[1]} for k, v in sorted(floor_live(root).items())],
    })
    bodies, names = duplicate_live(root)
    _write(DUPLICATE_FIXTURE, {"body_groups": sorted(bodies), "name_groups": sorted(names)})
    _write(LAYER_FIXTURE, {"layers": list(LAYERS), **layer_census(root)})
    print("fixtures written")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────


def _print_table(root: Path, files: list[str]) -> None:
    print("| file | raw | code | defs | longest fn | chains/routed | str== | isinst |")
    print("|---|--:|--:|--:|---|---|--:|--:|")
    for path in files:
        r = file_row(root, path)
        name, length = r["longest"]
        print(
            f"| `{path}` | {r['raw']} | {r['code']} | {r['defs']} | `{name}` {length} | "
            f"{r['chains']}/{r['routed']} | {r['str_eq']} | {r['isinstance']} |"
        )


def _print_detail(root: Path, path: str) -> None:
    tree = _tree(root, path)
    if tree is None:
        print(f"{path}: syntax error")
        return
    for unit in iter_units(path, tree):
        print(f"{path}:{unit.node.lineno}  {unit.qualname}  lines={unit.lines} depth={nesting_depth(unit.node)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-lines", type=int, default=CEILING_CODE_LINES)
    parser.add_argument("--counter", choices=("raw", "code"), default="raw")
    parser.add_argument("--detail", nargs="+", metavar="FILE")
    parser.add_argument("--check", action="store_true", help="every gate arm vs its fixture; exit 1 on drift")
    parser.add_argument("--write-fixtures", action="store_true")
    parser.add_argument("--bootstrap", action="store_true", help="with --write-fixtures: allow NEW/GREW (Wave 0 only)")
    args = parser.parse_args(argv)
    root = ROOT
    if args.write_fixtures:
        return write_fixtures(root, bootstrap=args.bootstrap)
    if args.check:
        drifts = all_drift(root)
        print(size_ledger_line(root))
        for drift in drifts:
            print(drift.render())
        return 1 if any(d.red for d in drifts) else 0
    if args.detail:
        for path in args.detail:
            _print_detail(root, path)
        return 0
    counter: Callable[[str], int] = raw_lines if args.counter == "raw" else code_lines
    files = [p for p in fork_production_files(root) if counter(_source(root, p)) > args.min_lines]
    files.sort(key=lambda p: -raw_lines(_source(root, p)))
    _print_table(root, files)
    print(size_ledger_line(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
