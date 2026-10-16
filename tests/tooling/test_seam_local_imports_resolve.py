"""A function-local import of a FORK module inside an UPSTREAM file must resolve.

The fork's seams into upstream files are mostly deferred imports (e.g.
``from agent_runtime.gateway.session_execution import admit`` inside a handler of
``tui_gateway/methods_prompt.py``). ``test_function_local_imports_resolve`` walks fork
production files only, and a deferred import is invisible to ruff and to import-time
loading, so a fork rename or move left these sites unproved until the call fired.

"This import resolves" is a POSITIVE guarantee, so it is asked of the runtime: the
source walk only ENUMERATES the sites (every ``Import`` / ``ImportFrom`` nested in a
function body of a production file — not under ``tests/`` or ``docs/`` — in the upstream
manifest, ``tests/fixtures/upstream_manifest.txt``, the one ``scripts/upstream_footprint.py``
reads). A target is FORK when it is, or sits
under, a module of a tracked file outside that manifest, or under ``agent_runtime`` /
``hermes_cli.harness*`` — the prefix rule keeps a target whose module was deleted in
the population, so a vanished module reds instead of dropping out. The target module is
imported and each name read with ``getattr`` (or imported as a submodule).

Killing mutation: point the ``methods_prompt.py`` import at ``admit_missing`` ->
``test_every_seam_local_import_resolves`` red.
"""

from __future__ import annotations

import ast
import importlib
import re
from functools import lru_cache, cache

from scripts import god_file_probe as probe
from scripts import god_file_scope as scope

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFERRED = re.compile(r"^[ \t]+(?:from[ \t]+([\w.]+)[ \t]+import|import[ \t]+([\w.]+))", re.MULTILINE)
_FORK_PREFIXES = ("agent_runtime", "hermes_cli.harness")


@lru_cache(maxsize=1)
def _upstream_files() -> tuple[str, ...]:
    upstream = probe.upstream_paths()
    tracked = probe._git(probe.ROOT, "ls-files", "-z", "--", "*.py").split("\0")
    return tuple(
        sorted(p for p in tracked if p in upstream and probe.is_fork_production(p) and (probe.ROOT / p).is_file())
    )


@lru_cache(maxsize=1)
def _fork_modules() -> frozenset[str]:
    upstream = probe.upstream_paths()
    tracked = probe._git(probe.ROOT, "ls-files", "-z", "--", "*.py").split("\0")
    return frozenset(scope.module_name(p) for p in tracked if p and p not in upstream)


@cache
def _may_reach_fork(module: str) -> bool:
    """Over-approximate prefilter: relative, fork, or a package with a fork module beneath it."""
    if module.startswith(".") or _is_fork(module):
        return True
    return any(m.startswith(module + ".") for m in _fork_modules())


@cache
def _is_fork(target: str) -> bool:
    if target.startswith(_FORK_PREFIXES):
        return True
    parts = target.split(".")
    fork = _fork_modules()
    return any(".".join(parts[:i]) in fork for i in range(len(parts), 0, -1))


def _local_imports(path: str, tree: ast.Module):
    """``(line, target module, name | None)`` for each import nested in a function body."""
    stack = [(child, False) for child in tree.body]
    while stack:
        node, in_func = stack.pop()
        if in_func and isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, None
        elif in_func and isinstance(node, ast.ImportFrom) and node.module != "__future__":
            target = scope.resolve_from(path, node)
            for alias in node.names:
                yield node.lineno, target, (None if alias.name == "*" else alias.name)
        inner = in_func or isinstance(node, _FUNCS)
        stack.extend((child, inner) for child in ast.iter_child_nodes(node))


def _sites(paths) -> list[tuple[str, int, str, str | None]]:
    sites = []
    for path in paths:
        source = scope.source(probe.ROOT, path)
        if not any(_may_reach_fork(f or i) for f, i in _DEFERRED.findall(source)):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        sites.extend((path, line, t, n) for line, t, n in _local_imports(path, tree) if _is_fork(t) or (n and _is_fork(f"{t}.{n}")))
    return sites


def _unresolved(sites) -> list[str]:
    broken = []
    for path, line, target, name in sites:
        stmt = f"from {target} import {name}" if name else f"import {target}"
        try:
            module = importlib.import_module(target)
        except ModuleNotFoundError as exc:
            broken.append(f"{path}:{line}: {stmt} (no module {exc.name})")
            continue
        if name is None or hasattr(module, name):
            continue
        try:
            importlib.import_module(f"{target}.{name}")
        except ModuleNotFoundError:
            broken.append(f"{path}:{line}: {stmt}")
    return broken


def test_every_seam_local_import_resolves():
    sites = _sites(_upstream_files())
    assert any(
        p == "tui_gateway/methods_prompt.py" and t == "agent_runtime.gateway.session_execution" for p, _, t, _ in sites
    ), "the walk missed the methods_prompt seam — the enumeration is broken"
    broken = _unresolved(sites)
    assert broken == [], "function-local fork imports in upstream files that do not resolve:\n" + "\n".join(broken)


def test_the_gate_reds_a_missing_name_and_a_missing_module():
    real = ("tui_gateway/methods_prompt.py", 1, "agent_runtime.gateway.session_execution", "admit")
    renamed = ("tui_gateway/methods_prompt.py", 1, "agent_runtime.gateway.session_execution", "admit_missing")
    gone = ("tui_gateway/methods_prompt.py", 1, "agent_runtime.gateway.no_such_module", "admit")
    assert _unresolved([real]) == []
    assert _unresolved([renamed]) == [
        "tui_gateway/methods_prompt.py:1: from agent_runtime.gateway.session_execution import admit_missing"
    ]
    assert _is_fork(gone[2])
    assert len(_unresolved([gone])) == 1


def test_the_walk_sees_deferred_imports_only():
    tree = ast.parse(
        "import agent_runtime\n"
        "def f():\n    if True:\n        from agent_runtime.gateway import session_execution\n"
        "        import agent_runtime.gateway.session_execution as s\n"
    )
    found = sorted(_local_imports("tui_gateway/methods_prompt.py", tree))
    assert found == [
        (4, "agent_runtime.gateway", "session_execution"),
        (5, "agent_runtime.gateway.session_execution", None),
    ]
    assert not _is_fork("json") and not _is_fork("hermes_cli.config")
