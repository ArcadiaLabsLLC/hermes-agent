"""What one fork file can SEE — the scope W0-G5 judges a string compare in.

Split from ``scripts/god_file_probe.py`` (which imports it) so the probe stays
under the 800-code-line ceiling it enforces; this module imports nothing of the
probe's. It owns the parse cache and the three questions G5 asks of a file:

* what the file DECLARES as a vocabulary (``Final`` string collections and
  string ``Enum`` members — :func:`vocabulary_strings`);
* which names it binds to a string constant or an ``Enum`` class, its own and
  imported ones, re-exports followed to the module that declares them
  (:func:`module_bindings`) — so a ladder spelled over ``DELIVERY_*`` constants
  or ``PullAction.*`` members is still a ladder;
* which words it declares itself (:class:`FileScope` ``declares``), so a table
  reading its own vocabulary by name is not a re-spelling.

Which vocabularies are in a file's REACH is the probe's
``visible_vocabularies`` (lane Q-RUNTIME), which follows a re-export through
:func:`module_bindings`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping

_COLLECTIONS = (ast.Tuple, ast.Set, ast.List)
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"})
_STR_ENUM_BASES = frozenset({"Enum", "StrEnum"})

#: A name a module binds at top level: ``(kind, value, origin)`` — ``("str",
#: value, origin)`` for a string constant, ``("enum", "", origin)`` for an Enum
#: class, ``("module", "", dotted)`` for a module. ``origin`` is the dotted module
#: that DECLARES it; a re-export is followed to it.
Binding = tuple[str, str, str]


# ── parsing ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def source(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8", errors="replace")


@lru_cache(maxsize=None)
def tree(root: Path, path: str) -> ast.Module | None:
    try:
        return ast.parse(source(root, path), filename=path)
    except SyntaxError:
        return None


def is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def is_str_collection(node: ast.AST) -> bool:
    return isinstance(node, _COLLECTIONS) and any(is_str(e) for e in node.elts)


def module_name(path: str) -> str:
    stem = path[:-3]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def resolve_from(path: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module_name(path).split(".")
    if not path.endswith("__init__.py"):
        package = package[:-1]
    package = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    return ".".join([*package, *([node.module] if node.module else [])])


@lru_cache(maxsize=None)
def module_path(root: Path, dotted: str) -> str | None:
    """The repo file a dotted module resolves to, or None (stdlib, third party, a name)."""
    stem = dotted.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if dotted and (root / candidate).is_file():
            return candidate
    return None


# ── what a module declares ──────────────────────────────────────────────────


def _base_names(node: ast.ClassDef) -> set[str]:
    return {ast.unparse(b).rsplit(".", 1)[-1] for b in node.bases}


def final_strings(node: ast.stmt) -> set[str]:
    """``NAME: Final[...] = ("a", "b")`` (or ``frozenset({...})``) -> its strings."""
    if not (isinstance(node, ast.AnnAssign) and node.value is not None and "Final" in ast.unparse(node.annotation)):
        return set()
    value = node.value
    if isinstance(value, ast.Call) and value.args:  # frozenset((...)) / tuple([...])
        value = value.args[0]
    if not isinstance(value, _COLLECTIONS):
        return set()
    return {e.value for e in value.elts if is_str(e)}


def enum_strings(node: ast.stmt) -> set[str]:
    """A ``class X(str, Enum)`` / ``StrEnum`` -> its string member values."""
    if not (isinstance(node, ast.ClassDef) and _base_names(node) & _STR_ENUM_BASES):
        return set()
    return {stmt.value.value for stmt in node.body if isinstance(stmt, ast.Assign) and is_str(stmt.value)}


def vocabulary_strings(module: ast.Module) -> set[str]:
    """Strings a module declares as a vocabulary: ``Final`` str collections and str Enum members."""
    found: set[str] = set()
    for node in module.body:
        found |= final_strings(node) | enum_strings(node)
    return found


# ── what a module binds ─────────────────────────────────────────────────────

#: Modules whose bindings are being read right now: an import cycle stops here.
_READING: set[str] = set()


def _assign(root: Path, path: str, node: ast.Assign) -> dict[str, Binding]:
    if not is_str(node.value):
        return {}
    return {t.id: ("str", node.value.value, module_name(path)) for t in node.targets if isinstance(t, ast.Name)}


def _ann_assign(root: Path, path: str, node: ast.AnnAssign) -> dict[str, Binding]:
    if not (isinstance(node.target, ast.Name) and is_str(node.value)):
        return {}
    return {node.target.id: ("str", node.value.value, module_name(path))}


def _class(root: Path, path: str, node: ast.ClassDef) -> dict[str, Binding]:
    return {node.name: ("enum", "", module_name(path))} if _base_names(node) & _ENUM_BASES else {}


def _import(root: Path, path: str, node: ast.Import) -> dict[str, Binding]:
    """``import a.b as m`` binds ``m`` to a module (an un-aliased dotted import binds no short name)."""
    return {
        alias.asname: ("module", "", alias.name)
        for alias in node.names
        if alias.asname and module_path(root, alias.name)
    }


def _import_from(root: Path, path: str, node: ast.ImportFrom) -> dict[str, Binding]:
    base = resolve_from(path, node)
    origin = module_path(root, base) if base else None
    out: dict[str, Binding] = {}
    for alias in node.names:
        found = _imported(root, base, origin, alias.name)
        if found is not None:
            out[alias.asname or alias.name] = found
    return out


def _imported(root: Path, base: str, origin: str | None, name: str) -> Binding | None:
    if module_path(root, f"{base}.{name}"):
        return ("module", "", f"{base}.{name}")
    if origin is None or origin in _READING:
        return None
    return module_bindings(root, origin).get(name)


#: Statement type -> the bindings it introduces (routing is data, rule 12).
_BINDERS: Mapping[type, Callable[[Path, str, ast.AST], dict[str, Binding]]] = {
    ast.Assign: _assign,
    ast.AnnAssign: _ann_assign,
    ast.ClassDef: _class,
    ast.Import: _import,
    ast.ImportFrom: _import_from,
}


def statement_bindings(root: Path, path: str, node: ast.AST) -> dict[str, Binding]:
    binder = _BINDERS.get(type(node))
    return binder(root, path, node) if binder else {}


@lru_cache(maxsize=None)
def module_bindings(root: Path, path: str) -> Mapping[str, Binding]:
    """What ``path`` binds at top level that G5 can reason about, re-exports followed."""
    parsed = tree(root, path)
    out: dict[str, Binding] = {}
    _READING.add(path)
    try:
        for node in parsed.body if parsed is not None else ():
            out.update(statement_bindings(root, path, node))
    finally:
        _READING.discard(path)
    return out


# ── what a file sees ────────────────────────────────────────────────────────


def _dotted(node: ast.AST) -> str | None:
    return ast.unparse(node) if isinstance(node, (ast.Name, ast.Attribute)) else None


def _unwrap_value(node: ast.AST) -> ast.AST:
    """``E.M.value`` is ``E.M``."""
    return node.value if isinstance(node, ast.Attribute) and node.attr == "value" else node


@dataclass(frozen=True)
class FileScope:
    """The names one file binds to strings and Enums, and the vocabulary words it declares itself."""

    path: str
    str_names: Mapping[str, tuple[str, str]]  # spelling -> (value, origin module)
    enum_names: frozenset[str]
    declares: frozenset[str]

    def strlike(self, node: ast.AST) -> bool:
        """A literal, a collection holding one, a NAME bound to a string, or an Enum member."""
        if isinstance(node, _COLLECTIONS):
            return any(self.strlike(e) for e in node.elts)
        spelled = _dotted(_unwrap_value(node))
        return is_str(node) or spelled in self.str_names or (spelled or "").rpartition(".")[0] in self.enum_names

    def local_alias(self, node: ast.AST) -> tuple[str, str] | None:
        """``(value, origin)`` when ``node`` is a NAME this file binds to a string literal itself."""
        found = self.str_names.get(node.id) if isinstance(node, ast.Name) else None
        return found if found and found[1] == module_name(self.path) else None


@dataclass
class _ScopeBuilder:
    root: Path
    path: str
    str_names: dict[str, tuple[str, str]] = field(default_factory=dict)
    enum_names: set[str] = field(default_factory=set)

    def bind(self, spelling: str, binding: Binding) -> None:
        kind, value, origin = binding
        self._KINDS[kind](self, spelling, value, origin)

    def _bind_str(self, spelling: str, value: str, origin: str) -> None:
        self.str_names[spelling] = (value, origin)

    def _bind_enum(self, spelling: str, value: str, origin: str) -> None:
        self.enum_names.add(spelling)

    def _bind_module(self, spelling: str, value: str, origin: str) -> None:
        target = module_path(self.root, origin)
        inner = module_bindings(self.root, target) if target else {}
        for name, binding in inner.items():
            if binding[0] != "module":
                self.bind(f"{spelling}.{name}", binding)

    _KINDS = {"str": _bind_str, "enum": _bind_enum, "module": _bind_module}

    def bind_all(self, bindings: Mapping[str, Binding]) -> None:
        for spelling, binding in bindings.items():
            self.bind(spelling, binding)

    def scope(self, declares: frozenset[str]) -> FileScope:
        return FileScope(self.path, dict(self.str_names), frozenset(self.enum_names), declares)


@lru_cache(maxsize=None)
def file_scope(root: Path, path: str) -> FileScope:
    """One file's :class:`FileScope`: its top-level bindings plus every import, deferred ones too."""
    builder = _ScopeBuilder(root, path)
    builder.bind_all(module_bindings(root, path))
    parsed = tree(root, path)
    top = {id(node) for node in parsed.body} if parsed is not None else set()
    imports = [n for n in ast.walk(parsed) if isinstance(n, (ast.Import, ast.ImportFrom))] if parsed else []
    for node in imports:
        if id(node) not in top:  # a deferred import binds too
            builder.bind_all(statement_bindings(root, path, node))
    return builder.scope(frozenset(vocabulary_strings(parsed)) if parsed is not None else frozenset())
