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

__all__ = ["PACKAGE", "TURN_COMMIT_PACKAGE", "package_files", "package_source", "package_tree", "turn_body"]


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


#: The turn commit's package inside ``persona/``: since lane H3's CHANGE,
#: ``_mission_chat_commit_turn`` is a two-line entry that runs ``TurnCommit``,
#: whose phases live in ``admit.py`` / ``run.py`` / ``settle.py`` beside it.
TURN_COMMIT_PACKAGE = PACKAGE / "chat_turn_commit"


def _file_line_spans() -> list[tuple[Path, int, int]]:
    """``(path, first_line, last_line)`` of each module inside :func:`package_source`."""

    spans, line = [], 1
    for path in package_files():
        count = path.read_text(encoding="utf-8").count("\n") + 1
        spans.append((path, line, line + count - 1))
        line += count
    return spans


def turn_body(tree: ast.Module, name: str) -> ast.AST | None:
    """The node a name-keyed pin walks, in a tree parsed from :func:`package_source`.

    A function by its name, as before — except ``_mission_chat_commit_turn``,
    which answers with the WHOLE turn commit: every top-level class, function
    and table of ``chat_turn_commit/`` (imports excluded), as one module node.
    ``None`` when nothing is found, so a caller's own "not found" message stands.
    """

    if name == "_mission_chat_commit_turn":
        ranges = [(a, b) for path, a, b in _file_line_spans() if TURN_COMMIT_PACKAGE in path.parents]
        body = [
            node
            for node in tree.body
            if not isinstance(node, (ast.Import, ast.ImportFrom))
            and any(a <= node.lineno <= b for a, b in ranges)
        ]
        return ast.Module(body=body, type_ignores=[]) if body else None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None
