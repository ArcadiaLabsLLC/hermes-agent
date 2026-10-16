"""A function-local ``from <fork module> import <name>`` must name something the module binds.

Evidence: ``fb3fb9d749f`` renamed ``persona_open_chat._text`` to ``_first_text`` and
left three deferred imports of the old name; ``runtime.persona.chat.delete`` and
``runtime.persona.instance.create`` answered ``ERR_HANDLER_FAILED`` (ImportError)
on every call until ``f87546f0783``. A deferred import is invisible to ruff and
to import-time loading, so nothing reddened.

"This name resolves" is a POSITIVE guarantee, so it is asked of the runtime: the
source walk only ENUMERATES the sites (every ``ImportFrom`` inside a function body
of a fork-production file, ``scripts/god_file_probe.fork_production_files``); the
target module is imported and the name read with ``getattr`` (or imported as a
submodule). Only targets inside this repository's fork-owned trees are asked —
an optional third-party import is the environment's question, not this gate's.

Killing mutation: rename a target (``persona_open_chat._first_text`` back to
``_text`` in one importer) -> ``test_every_function_local_import_resolves`` red.
"""

from __future__ import annotations

import ast
import importlib
from functools import lru_cache

from scripts import god_file_probe as probe
from scripts import god_file_scope as scope

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


@lru_cache(maxsize=1)
def _fork_modules() -> frozenset[str]:
    return frozenset(scope.module_name(path) for path in probe.fork_production_files())


def _local_imports(path: str, tree: ast.Module):
    """``(line, target module, name)`` for each ImportFrom nested in a function body."""
    seen: set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, _FUNCS):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.ImportFrom) or id(node) in seen or node.module == "__future__":
                continue
            seen.add(id(node))
            target = scope.resolve_from(path, node)
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, target, alias.name


def _sites(paths) -> list[tuple[str, int, str, str]]:
    fork = _fork_modules()
    sites = []
    for path in paths:
        tree = scope.tree(probe.ROOT, path)
        if tree is None:
            continue
        sites.extend((path, line, target, name) for line, target, name in _local_imports(path, tree) if target in fork)
    return sites


def _unresolved(sites) -> tuple[list[str], dict[str, str]]:
    broken, missing = [], {}
    for path, line, target, name in sites:
        try:
            module = importlib.import_module(target)
        except ModuleNotFoundError as exc:
            missing[target] = exc.name or str(exc)
            continue
        if hasattr(module, name):
            continue
        try:
            importlib.import_module(f"{target}.{name}")
        except ModuleNotFoundError:
            broken.append(f"{path}:{line}: from {target} import {name}")
    return broken, missing


def test_every_function_local_import_resolves():
    sites = _sites(probe.fork_production_files())
    assert sites, "the walk found no function-local fork import — the enumeration is broken"
    broken, missing = _unresolved(sites)
    assert broken == [], "function-local imports naming a name the module does not bind:\n" + "\n".join(broken)
    assert not missing, f"the test venv cannot import these fork modules (a dependency, not a rename): {missing}"


def test_the_gate_reds_a_renamed_target():
    """Positive control: one real fork module, one function-local import of a name it lacks."""
    real = ("agent_runtime/harness_query/core.py", 1, "agent_runtime.harness_query.core", "observer")
    renamed = ("agent_runtime/harness_query/core.py", 1, "agent_runtime.harness_query.core", "_no_such_name")
    assert _unresolved([real]) == ([], {})
    broken, _ = _unresolved([renamed])
    assert broken == ["agent_runtime/harness_query/core.py:1: from agent_runtime.harness_query.core import _no_such_name"]


def test_the_walk_sees_a_deferred_relative_import():
    tree = ast.parse("def f():\n    if True:\n        from .core import observer\n\nfrom .core import x\n")
    found = list(_local_imports("agent_runtime/harness_query/serve_route.py", tree))
    assert found == [(3, "agent_runtime.harness_query.core", "observer")]
