"""The gate directory (``docs/agent-runtime-harness/11-gate-directory.md``) is current.

Three arms. Every repo path the page names in backticks exists (a renamed or deleted
gate reds here instead of leaving a dead row). Every gate in the enumerated places --
``tests/tooling/test_*.py``, ``scripts/check*``, ``scripts/*_gate.py``,
``scripts/dump_*_contract.py`` and every test file carrying ``pytest.mark.gate`` -- has
a row (a new gate without one reds here). Every test file the page names carries the
``gate`` mark (a row whose file lost its mark reds here), so the enumeration is the
mark, not a list of directories: a gate written in ``tests/agent_runtime/`` joins it
the moment it is marked.

The mark is the module-level ``pytestmark`` of a fork file, read by
``scripts/gate_mark.py`` (the one reader; the bundled scope asks it too), or a
file-level row in ``tests/_downstream/id_markers/fork_marks.py`` for an upstream
file (which takes no edit), read here through ``ids_marked``.

Killing mutations (2026-10-18): delete the ``test_no_ladder_routing.py`` row ->
``test_every_enumerated_gate_has_a_row`` red; rename a named path to
``tests/tooling/test_gone.py`` -> ``test_every_named_path_exists`` red; drop
``pytest.mark.gate`` from ``tests/agent_runtime/test_s41_dead_import_bindings.py`` ->
``test_every_named_test_file_carries_the_gate_mark`` red; delete the
``test_s41_dead_import_bindings.py`` row -> ``test_every_enumerated_gate_has_a_row`` red
(the file sits outside every enumerated directory: only its mark finds it).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from scripts.gate_mark import GATE_MARK, carries_gate_mark, module_marks as _module_marks
from tests._downstream.id_markers import ids_marked

pytestmark = pytest.mark.gate

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "agent-runtime-harness" / "11-gate-directory.md"
_NAMED = re.compile(r"`((?:tests|scripts|\.github)/[^`\s]+)")


def _named() -> set[str]:
    # a glob the page quotes to describe the enumeration is not a path
    return {p for p in _NAMED.findall(PAGE.read_text(encoding="utf-8")) if "*" not in p}


def _marked(root: Path = REPO) -> set[str]:
    """Every tracked test file carrying the ``gate`` mark, by its ``pytestmark`` or by an id row."""
    out = subprocess.run(["git", "ls-files", "-z", "--", "tests"], cwd=root, capture_output=True, check=True)
    marked = {node for node in ids_marked(GATE_MARK) if "::" not in node}
    for rel in out.stdout.decode("utf-8").split("\0"):
        if not (rel.endswith(".py") and Path(rel).name.startswith("test_")):
            continue
        path = root / rel
        if path.is_file() and carries_gate_mark(path):
            marked.add(rel)
    return marked


def _enumerated() -> set[str]:
    found = {p for p in REPO.glob("tests/tooling/test_*.py")}
    for pattern in ("scripts/check*", "scripts/*_gate.py", "scripts/dump_*_contract.py"):
        found.update(p for p in REPO.glob(pattern) if p.is_file())
    return {p.relative_to(REPO).as_posix() for p in found} | _marked()


def test_every_named_path_exists():
    missing = sorted(p for p in _named() if not (REPO / p).exists())
    assert not missing, f"11-gate-directory.md names paths that do not exist: {missing}"


def test_every_enumerated_gate_has_a_row():
    unlisted = sorted(_enumerated() - _named())
    assert not unlisted, f"gates with no row in 11-gate-directory.md: {unlisted}"


def test_every_named_test_file_carries_the_gate_mark():
    named = {p for p in _named() if p.startswith("tests/") and p.endswith(".py") and Path(p).name.startswith("test_")}
    unmarked = sorted(named - _marked())
    assert not unmarked, (
        f"test files 11-gate-directory.md lists without `pytestmark = pytest.mark.{GATE_MARK}` "
        f"(or, for an upstream file, a file row in tests/_downstream/id_markers/fork_marks.py): {unmarked}"
    )


def test_the_mark_reader_sees_both_spellings_and_not_another_mark():
    assert _module_marks(ast.parse("import pytest\npytestmark = pytest.mark.gate\n")) == {"gate"}
    listed = "import pytest\npytestmark = [pytest.mark.timeout(9), pytest.mark.gate]\n"
    assert _module_marks(ast.parse(listed)) == {"timeout", "gate"}
    assert _module_marks(ast.parse("import pytest\nx = pytest.mark.gate\n")) == set()
    assert "tests/scripts/test_bash_shebangs.py" in _marked()  # the id-row arm (upstream file)
