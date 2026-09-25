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

__all__ = ["package_files", "package_source", "package_tree"]


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
