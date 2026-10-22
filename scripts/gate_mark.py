"""Which test file carries the ``gate`` mark at module level: the one reader.

A fork gate is a test file whose module-level ``pytestmark`` names
``pytest.mark.gate``, alone or in a list. Two consumers ask this module, and no
other scanner answers the question:

* the gate directory (``tests/tooling/test_gate_directory_current.py``), which
  enumerates every gate the page must list;
* the bundled scope (``scripts/run_tests_bundled_scope.py::select_scope``), which
  keeps every fork-owned gate selected while a session-chain change samples, as it
  keeps the chain's contract (fork-hygiene FH-SCOPE-FORK-DROPS-SOURCE-GATES:
  land/w1021j's chain-only scope dropped all of them and missed three gate reds).

An upstream file takes no edit, so its gate mark is a file row in
``tests/_downstream/id_markers/fork_marks.py`` instead; that arm is the gate
directory's, through ``ids_marked``. ``GATE_MARK`` is spelled here and re-exported
by ``tests/_downstream/id_markers/reasons.py``, the mark vocabulary. Generic:
stdlib and ``source_cache`` only, so the runner can import it without pytest.
"""

from __future__ import annotations

import ast
import os

try:  # imported as ``scripts.gate_mark`` (the tests)
    from scripts import source_cache
except ImportError:  # loaded by the runner: ``scripts/`` is sys.path[0]
    import source_cache

GATE_MARK = "gate"


def module_marks(tree: ast.Module) -> set[str]:
    """Mark names in the module-level ``pytestmark`` (``pytest.mark.<name>``, alone or listed)."""

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Attribute) and sub.value.attr == "mark":
                    names.add(sub.attr)
    return names


def carries_gate_mark(path: os.PathLike[str] | str) -> bool:
    """True when ``path``'s module-level ``pytestmark`` names the gate mark.

    A text probe first (one read, kept by ``source_cache``), the parse only for a
    file whose text mentions the mark. A file that cannot be read or parsed is not
    a gate here; its own run says why.
    """

    try:
        if f"mark.{GATE_MARK}" not in source_cache.source(path):
            return False
        tree = source_cache.tree(path, keep=False)
    except OSError:
        return False
    return tree is not None and GATE_MARK in module_marks(tree)
