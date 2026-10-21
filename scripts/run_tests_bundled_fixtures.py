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

A ROW naming a test file — a string literal ``tests/<…>.py`` or
``tests/<…>.py::<node>`` in a tuple, list, set or dict key (the id-marker
tables, ``tests/_downstream/id_markers/``) — is taken out of the core and keyed
only into the file it names (r-fastgate, owner ruling 2026-10-16: key each file
on the session-chain modules it actually loaded, not the whole chain). Adding or
retiring one upstream-red row used to miss every file the session loaded the
table into — all of them; it now misses the file the row names.

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
import re
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


#: a string naming a test file or one of its nodes: a table row that reaches that file only
_ROW = re.compile(r"^(tests/[^\s:]+\.py)(?:::.*)?$")


class _Rows(ast.NodeTransformer):
    """Takes every row out of the module's tuples, lists, sets and dict keys, by the file it names."""

    def __init__(self) -> None:
        self.rows: dict[str, list[str]] = {}

    @staticmethod
    def _names(node: Optional[ast.AST]) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found = _ROW.match(node.value)
            return found.group(1) if found else None
        return None

    def _sequence(self, node):
        self.generic_visit(node)
        kept = []
        for elt in node.elts:
            name = self._names(elt)
            if name is None:
                kept.append(elt)
            else:
                self.rows.setdefault(name, []).append(ast.dump(elt))
        node.elts = kept
        return node

    visit_Tuple = visit_List = visit_Set = _sequence

    def visit_Dict(self, node):
        self.generic_visit(node)
        keys, values = [], []
        for key, value in zip(node.keys, node.values):
            name = self._names(key)
            if name is None:
                keys.append(key)
                values.append(value)
            else:
                self.rows.setdefault(name, []).append(ast.dump(key) + "=" + ast.dump(value))
        node.keys, node.values = keys, values
        return node


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ModuleShape:
    """One fixture module split into its core and its fixture definitions."""

    core: str
    fixtures: dict[str, str]  # name → digest of every definition of that name, in order
    rows: Optional[dict[str, str]] = None  # test file → digest of the rows naming it, in order

    def line(self, rel: str, used: Iterable[str], test: str = "") -> str:
        reached = sorted(set(used) & set(self.fixtures))
        row = (self.rows or {}).get(test, "")
        fixtures = ",".join(f"{n}={self.fixtures[n]}" for n in reached)
        return f"fxmod\t{rel}\t{self.core}\t{fixtures}\trows={row}"


def shape_of(source: bytes) -> Optional[ModuleShape]:
    """The module's core and fixture digests; None when it does not parse."""

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    rows = _Rows()
    tree = rows.visit(tree)
    core, defs = [], {}
    for node in tree.body:
        name = _fixture_name(node)
        if name is None:
            core.append(ast.dump(node))
        else:
            defs.setdefault(name, []).append(ast.dump(node))
    return ModuleShape(
        _sha("\n".join(core)), {name: _sha("\n".join(dumps)) for name, dumps in defs.items()},
        {name: _sha("\n".join(texts)) for name, texts in rows.rows.items()},
    )


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
