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
from pathlib import Path
from types import ModuleType

__all__ = ["package_files", "package_source", "package_tree", "patch_where_bound"]


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


def patch_where_bound(monkeypatch, package: ModuleType, name: str, value: object) -> None:
    """Stub ``name`` wherever ``package`` or one of its modules BINDS it.

    A split package re-exports names its modules bound by import (lane B4's
    ``stream``); a stub on the package attribute alone reaches no module-global
    read, silently. Patched: the package itself when it binds ``name``, and every
    module of it whose ``name`` is the SAME object the package holds (or, when the
    package does not hold it, every module that binds it at all). Fails loudly
    when nothing binds it — a stub that reaches nothing is the defect.
    """
    import importlib
    import pkgutil

    original = vars(package).get(name)
    targets = [package] if name in vars(package) else []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        bound = vars(module)
        if name in bound and (original is None or bound[name] is original):
            targets.append(module)
    assert targets, f"nothing in {package.__name__} binds {name!r}"
    for target in targets:
        monkeypatch.setattr(target, name, value)
