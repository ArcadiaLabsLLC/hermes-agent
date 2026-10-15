"""Fixture-scoped keys for the modules that define fixtures (fast-gate §1, row 2026-10-15).

A green-result key used to hash every recorded module by its whole blob. The
session chain (``tests/_downstream/conftest_plugin.py``, the conftests) is
loaded by every test process, so editing ONE fixture in it changed every key:
land-w1015b's 29-line conftest edit missed 6,309 of 6,563 files as ``changed``.

When the dependency recorder knows the fixtures a test file set up (``fx``,
``scripts/_bundle_plugin/hermes_dep_record.py``), a fixture module is keyed by
what that file can reach instead of its blob: its CORE (every top-level
statement that is not a fixture definition — imports, hooks, helpers,
module-level code) plus the definitions of the fixtures the file used. An edit
to a fixture the file never set up leaves its key alone; an edit to a hook, a
helper or an autouse fixture (every test sets those up) still reaches every
file. The AST dump ignores comments and line numbers, so moving code or
editing a comment changes no key.

A fixture module the FILE itself opened (``own``: a test reading the source as
data) or a child process of it loaded keeps its whole-blob line: only an import
read is fingerprinted. Anything that will not parse, or whose bytes on disk are
not the snapshot's blob, keeps the whole-blob line too: every fallback can only
cost a miss, never a false hit.

Pure: the standard library only; ``run_tests_bundled_gate.py`` wires it in.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

#: prefixes whose ``.py`` modules define fixtures for other files (the session chain's)
FIXTURE_PREFIXES = ("tests/_downstream/", "tests/_fixtures/")


def is_fixture_module(rel: str) -> bool:
    """A module whose fixture definitions other test files set up."""

    if not rel.endswith(".py"):
        return False
    return rel.rsplit("/", 1)[-1] == "conftest.py" or rel.startswith(FIXTURE_PREFIXES)


def _fixture_name(node: ast.AST) -> Optional[str]:
    """The fixture name a top-level def registers, or None when it is not a fixture."""

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call is not None else decorator
        spelled = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if spelled != "fixture":
            continue
        for keyword in call.keywords if call is not None else ():
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
        return node.name
    return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ModuleShape:
    """One fixture module split into its core and its fixture definitions."""

    core: str
    fixtures: dict[str, str]  # name → digest of every definition of that name, in order

    def line(self, rel: str, used: Iterable[str]) -> str:
        reached = sorted(set(used) & set(self.fixtures))
        return f"fxmod\t{rel}\t{self.core}\t" + ",".join(f"{n}={self.fixtures[n]}" for n in reached)


def shape_of(source: bytes) -> Optional[ModuleShape]:
    """The module's core and fixture digests; None when it does not parse."""

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    core, defs = [], {}
    for node in tree.body:
        name = _fixture_name(node)
        if name is None:
            core.append(ast.dump(node))
        else:
            defs.setdefault(name, []).append(ast.dump(node))
    return ModuleShape(_sha("\n".join(core)), {name: _sha("\n".join(dumps)) for name, dumps in defs.items()})


class Fingerprints:
    """``rel`` → its :class:`ModuleShape` at the snapshot, read once per blob.

    ``blob_of`` is the snapshot's blob id for a path and ``blob_id`` hashes bytes
    the way git does; a file whose bytes no longer match the snapshot (edited
    mid-run) has no shape, so the caller keys it by blob."""

    def __init__(self, root: Path, blob_of: Callable[[str], str], blob_id: Callable[[bytes], str]) -> None:
        self.root = Path(root)
        self._blob_of = blob_of
        self._blob_id = blob_id
        self._shapes: dict[tuple[str, str], Optional[ModuleShape]] = {}

    @staticmethod
    def is_fixture_module(rel: str) -> bool:
        return is_fixture_module(rel)

    def shape(self, rel: str) -> Optional[ModuleShape]:
        blob = self._blob_of(rel)
        found = self._shapes.get((rel, blob), False)
        if found is False:
            try:
                data = (self.root / rel).read_bytes()
            except OSError:
                data = None
            found = shape_of(data) if data is not None and self._blob_id(data) == blob else None
            self._shapes[(rel, blob)] = found
        return found
