"""An ``agent_runtime`` package split out of one god file, read as ONE parseable text.

Lane R3 (god-file program Wave 2) turned ``serve_rpc``, ``serve_socket``,
``core_cache``, ``profile_runner`` and ``snapshot`` into packages. A source pin
that used to read ``<module>.__file__`` reads the package through here: its
modules are concatenated in path order with their ``from __future__`` lines
blanked (a future import is legal only at the top of a module), so
``ast.parse`` over the result sees every definition the single file held.
The same shape as ``persona_source`` (lane H3), keyed by package.
"""

from __future__ import annotations

import ast
import functools
import sys
from pathlib import Path
from types import ModuleType

__all__ = ["fork_importers_of", "package_files", "package_source", "package_tree", "patch_where_bound"]


def package_files(package: ModuleType) -> list[Path]:
    """Every module of ``package`` (an imported package object), in path order."""
    return sorted(Path(package.__file__).resolve().parent.rglob("*.py"))


def package_source(package: ModuleType) -> str:
    """The package's modules joined into one text that parses as one module."""
    texts = []
    for path in package_files(package):
        lines = path.read_text(encoding="utf-8").split("\n")
        texts.append("\n".join("" if line == "from __future__ import annotations" else line for line in lines))
    return "\n".join(texts)


def package_tree(package: ModuleType) -> ast.Module:
    """``ast.parse(package_source(package))``."""
    return ast.parse(package_source(package))


@functools.lru_cache(maxsize=None)
def _fork_texts() -> tuple[tuple[str, str], ...]:
    """``(dotted module, source)`` for every fork production module, read once."""
    from scripts import god_file_probe as probe

    out = []
    for path in probe.fork_production_files(probe.ROOT):
        try:
            out.append((probe.module_name(path), (probe.ROOT / path).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return tuple(out)


@functools.lru_cache(maxsize=None)
def fork_importers_of(name: str) -> frozenset[str]:
    """Fork production modules that bind *name* by ``from … import`` (any scope).

    Walked with ``god_file_scope.imports_of`` over the fork population
    (``god_file_probe.fork_production_files``); only files whose text names
    *name* are parsed. An aliased import (``import … as other``) binds another
    local name and is not a module-global ``name`` — the silent-patch gate
    (``tests/tooling/test_no_silent_package_patches.py``) owns that case.
    """
    from scripts import god_file_scope as scope

    found = set()
    for dotted, text in _fork_texts():
        if name not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        path = dotted.replace(".", "/") + ".py"
        for _module, imported, _line in scope.imports_of(path, tree):
            if imported == name:
                found.add(dotted)
                break
    return frozenset(found)


def patch_where_bound(monkeypatch, package: ModuleType, name: str, value: object) -> None:
    """Stub ``name`` wherever ``package``, one of its modules, or a fork module that
    imported it BINDS it.

    A split package re-exports names its modules bound by import (lane B4's
    ``stream``); a stub on the package attribute alone reaches no module-global
    read, silently. Patched: the package itself when it binds ``name``, and every
    module of it whose ``name`` is the SAME object the package holds (or, when the
    package does not hold it, every module that binds it at all). Then, OUTSIDE
    the package (lane W3-D): every loaded fork module that bound ``name`` by
    import (``fork_importers_of``) and holds one of those same objects — a reader
    like ``agent_runtime.migrations`` binding ``load_agent_runtime_config`` from
    ``agent_runtime.config`` at module scope. A module not yet imported needs no
    patch: it binds from an already-patched module when it loads. Fails loudly
    when nothing binds it — a stub that reaches nothing is the defect.
    """
    import importlib
    import pkgutil

    original = vars(package).get(name)
    targets = [package] if name in vars(package) else []
    for info in pkgutil.walk_packages(getattr(package, "__path__", ()), package.__name__ + "."):
        module = importlib.import_module(info.name)
        bound = vars(module)
        if name in bound and (original is None or bound[name] is original):
            targets.append(module)
    assert targets, f"nothing in {package.__name__} binds {name!r}"
    objects = {id(vars(target)[name]) for target in targets}
    inside = {id(target) for target in targets}
    for dotted in sorted(fork_importers_of(name)):
        module = sys.modules.get(dotted)
        if module is None or id(module) in inside:
            continue
        bound = vars(module)
        if name in bound and id(bound[name]) in objects:
            targets.append(module)
    for target in targets:
        monkeypatch.setattr(target, name, value)
