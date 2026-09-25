"""The ``hermes_cli/harness_parts/persona/`` package as ONE parseable text.

Lane H3 split ``hermes_cli/harness_parts/persona_commands.py`` into that
package. The AST pins that read the old file look functions up by NAME, and
keep doing so over the package: its files are concatenated in path order with
their ``from __future__`` lines blanked (a future import is legal only at the
top of a module), so ``ast.parse`` and ``ast.get_source_segment`` agree on the
one text these helpers return.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "hermes_cli" / "harness_parts" / "persona"

__all__ = ["PACKAGE", "package_files", "package_source", "package_tree"]


def package_files() -> list[Path]:
    """Every module of the persona package, in path order."""
    return sorted(PACKAGE.rglob("*.py"))


def package_source() -> str:
    """The package's modules joined into one text that parses as one module."""
    texts = []
    for path in package_files():
        lines = path.read_text(encoding="utf-8").split("\n")
        texts.append("\n".join("" if line == "from __future__ import annotations" else line for line in lines))
    return "\n".join(texts)


def package_tree() -> ast.Module:
    """``ast.parse(package_source())``."""
    return ast.parse(package_source())
