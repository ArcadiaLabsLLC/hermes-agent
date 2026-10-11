"""A resolved call graph over Python source — the AST and each file's imports,
nothing executed (D3.17).

A call is resolved to ``(module, name)`` through the calling file's own
bindings: a function defined at the top of the same module, a name bound by
``from X import name [as alias]`` (relative imports resolved against the
file's package), or an attribute on a module bound by ``import X [as m]`` /
``from P import submodule``. Imports inside a function's body bind for that
function. A name that resolves to none of those is RECORDED as unresolved,
never dropped, so a reader can see what the graph could not follow (dynamic
dispatch, ``self.method()``, a callable held in a table).

:func:`reaches` / :meth:`CallGraph.reaching` answer "does this function's body
reach that one" as a fixpoint over the resolved graph with a visited set, so a
cycle terminates. A symbol a module re-exports (``from Y import name`` at its
top) is followed to ``Y``. Parsing is on demand and bounded to the module
prefixes in ``limit_to``.

Pure functions over ``ast``; tested on the fixture modules under
``tests/fixtures/call_graph/`` (``tests/_downstream/test_call_graph.py``).
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["CallGraph", "CallTable", "Symbol", "module_file", "module_name", "reaches", "resolve_calls"]

#: ``(dotted module, top-level function name)``.
Symbol = tuple[str, str]

_BUILTINS = frozenset(dir(builtins))


def module_file(root: Path, module: str) -> Path | None:
    """The source file of ``module`` under ``root``, or ``None``."""

    base = root.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def module_name(root: Path, path: Path) -> str:
    """The dotted name of the module at ``path`` (a package's ``__init__`` is the package)."""

    parts = list(path.resolve().relative_to(root.resolve()).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass
class CallTable:
    """One module's resolved calls: function -> callees, and what did not resolve."""

    module: str
    calls: dict[str, set[Symbol]] = field(default_factory=dict)
    unresolved: dict[str, set[str]] = field(default_factory=dict)
    #: top-level names this module imports rather than defines: name -> the symbol it binds.
    reexports: dict[str, Symbol] = field(default_factory=dict)


#: An import binding: ``(module, None)`` names a module, ``(module, name)`` a symbol in one.
_Binding = tuple[str, "str | None"]


def _import_bindings(nodes: Iterable[ast.AST], package: list[str], root: Path) -> dict[str, _Binding]:
    bound: dict[str, _Binding] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = (alias.name, None)
                else:
                    head = alias.name.split(".")[0]
                    bound[head] = (head, None)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else list(package)
                head = ".".join(base + ([node.module] if node.module else []))
            else:
                head = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                as_module = f"{head}.{alias.name}" if head else alias.name
                is_module = module_file(root, as_module) is not None
                bound[alias.asname or alias.name] = (as_module, None) if is_module else (head, alias.name)
    return bound


def _attribute_chain(node: ast.AST) -> list[str] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return parts[::-1]


def _resolve_callee(func: ast.AST, module: str, defined: set[str], bound: dict[str, _Binding], root: Path) -> Symbol | str:
    """The callee's symbol, or the spelling that did not resolve."""

    parts = _attribute_chain(func)
    if parts is None:
        return "<expr>." + func.attr if isinstance(func, ast.Attribute) else "<expr>"
    head, *rest = parts
    if not rest:
        if head in bound and bound[head][1] is not None:
            return bound[head]  # type: ignore[return-value]
        if head in defined:
            return (module, head)
        return head
    binding = bound.get(head)
    if binding is None or binding[1] is not None:
        return ".".join(parts)
    # ``import a`` then ``a.b.c.f()``: the longest prefix that is a module owns ``f``.
    target = binding[0]
    for index in range(len(rest) - 1):
        candidate = ".".join([target, *rest[: index + 1]])
        if module_file(root, candidate) is None:
            return ".".join(parts)
        target = candidate
    return (target, rest[-1])


def resolve_calls(path: Path, root: Path) -> CallTable:
    """Every top-level function in ``path`` -> the symbols it calls (see the module doc)."""

    module = module_name(root, path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    top_imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    top_imports += [n for block in tree.body if isinstance(block, (ast.If, ast.Try))
                    for n in ast.walk(block) if isinstance(n, (ast.Import, ast.ImportFrom))]
    module_bound = _import_bindings(top_imports, package, root)
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    defined = {n.name for n in defs}
    table = CallTable(module, reexports={
        name: binding for name, binding in module_bound.items()  # type: ignore[misc]
        if binding[1] is not None and name not in defined
    })
    for node in defs:
        bound = {**module_bound, **_import_bindings((n for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom))),
                                         package, root)}
        calls: set[Symbol] = set()
        missed: set[str] = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            callee = _resolve_callee(sub.func, module, defined, bound, root)
            if isinstance(callee, tuple):
                calls.add(callee)
            elif callee not in _BUILTINS:
                missed.add(callee)
        table.calls[node.name] = calls
        table.unresolved[node.name] = missed
    return table


class CallGraph:
    """The graph over every module under ``root`` whose name starts with a ``limit_to`` prefix."""

    def __init__(self, root: Path, limit_to: tuple[str, ...]) -> None:
        self.root = root
        self.limit_to = limit_to
        self._tables: dict[str, CallTable | None] = {}

    def table(self, module: str) -> CallTable | None:
        if module not in self._tables:
            inside = any(module == p or module.startswith(p + ".") for p in self.limit_to)
            path = module_file(self.root, module) if inside else None
            self._tables[module] = resolve_calls(path, self.root) if path is not None else None
        return self._tables[module]

    def callees(self, symbol: Symbol) -> set[Symbol]:
        table = self.table(symbol[0])
        if table is None:
            return set()
        if symbol[1] in table.calls:
            return table.calls[symbol[1]]
        if symbol[1] in table.reexports:
            return {table.reexports[symbol[1]]}
        return set()

    def reaching(self, targets: set[Symbol], starts: Iterable[Symbol]) -> set[Symbol]:
        """The members of ``starts`` from which some symbol in ``targets`` is reachable."""

        starts = set(starts)
        edges: dict[Symbol, set[Symbol]] = {}
        frontier = list(starts)
        while frontier:
            symbol = frontier.pop()
            if symbol in edges:
                continue  # the visited set: a cycle terminates here
            edges[symbol] = self.callees(symbol)
            frontier.extend(edges[symbol] - edges.keys())
        callers: dict[Symbol, set[Symbol]] = {}
        for caller, called in edges.items():
            for callee in called:
                callers.setdefault(callee, set()).add(caller)
        hit: set[Symbol] = set()
        frontier = [t for t in targets if t in callers or t in starts]
        while frontier:
            symbol = frontier.pop()
            if symbol in hit:
                continue
            hit.add(symbol)
            frontier.extend(callers.get(symbol, ()))
        return hit & starts


def reaches(root_module: str, root_name: str, start: Symbol, limit_to: tuple[str, ...], *, root: Path) -> bool:
    """Does ``start``'s body reach ``root_module.root_name``?"""

    return bool(CallGraph(root, limit_to).reaching({(root_module, root_name)}, [start]))
