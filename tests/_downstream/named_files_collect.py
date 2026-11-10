"""A run that names its test FILES never builds a node for a file it did not name.

pytest (8+) collects a named file through its directory: ``Dir``/``Package.collect`` lists the WHOLE directory
and calls ``pytest_ignore_collect``, ``pytest_collect_file`` and ``pytest_pycollect_makemodule`` for every
entry, then keeps the one node the argument matches. Every bundle process names its files, so each paid a
full walk of each directory it touched: 1,866 entries and ~0.9 CPU-s for ONE file of ``tests/hermes_cli``
(lane h6-collect, 2026-10-18), ~400 processes in a features run.

When every argument is a file (``path`` or ``path::node``), ``pytest_ignore_collect`` answers first: an entry
that is neither a named file nor a directory on the way to one is ignored before any other hook sees it.
``__init__.py`` and ``conftest.py`` are never ignored here, and a run naming any directory (or ``--pyargs``)
is left exactly as pytest has it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_KEY = pytest.StashKey[object]()
_NEVER = frozenset({"__init__.py", "conftest.py"})


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def named_scope(args, invocation_dir) -> tuple[frozenset[str], frozenset[str]] | None:
    """``(named files, their ancestor directories)``, or ``None`` when any argument is not a file."""

    files: set[str] = set()
    for arg in args:
        base = str(arg).split("::", 1)[0]
        path = Path(base) if os.path.isabs(base) else Path(invocation_dir) / base
        if not path.is_file():
            return None
        files.add(_norm(path))
    if not files:
        return None
    ancestors: set[str] = set()
    for name in files:
        parent = os.path.dirname(name)
        while parent and parent not in ancestors:
            ancestors.add(parent)
            up = os.path.dirname(parent)
            if up == parent:
                break
            parent = up
    return frozenset(files), frozenset(ancestors)


@pytest.hookimpl(specname="pytest_ignore_collect", tryfirst=True)
def pytest_ignore_collect_named_files(collection_path, config):  # pytest hook
    scope = config.stash.get(_KEY, False)
    if scope is False:
        scope = None if config.getoption("pyargs", False) else named_scope(config.args, config.invocation_params.dir)
        config.stash[_KEY] = scope
    if scope is None or collection_path.name in _NEVER:
        return None
    files, ancestors = scope
    name = _norm(collection_path)
    if name in files or name in ancestors:
        return None
    return True



def contiguous_args(args, invocation_dir) -> list[str]:
    """*args* regrouped so every directory's arguments are adjacent, in first-appearance order
    (FH-WORK-STORE-FIXTURE-LOST-IN-ONE-PROCESS).

    pytest 9.1 parses a directory conftest's fixtures onto the FIRST ``Dir`` node collected for that
    directory (``FixtureManager._pending_conftests`` is popped once). Arguments that leave a directory
    and come back (``work_store/a.py agent_runtime/b.py work_store/c.py``) build a second ``Dir`` node
    for it, and every test under that node errors ``fixture '…' not found``. Grouping by the path tree
    gives each directory one node; the relative order inside a directory is kept."""

    tree: dict = {}
    for arg in args:
        base = str(arg).split("::", 1)[0]
        path = Path(base) if os.path.isabs(base) else Path(invocation_dir) / base
        node = tree
        for part in Path(_norm(path)).parts:
            node = node.setdefault(part, {})
        node.setdefault(None, []).append(str(arg))

    ordered: list[str] = []

    def emit(node: dict) -> None:
        for key, child in node.items():
            if key is None:
                ordered.extend(child)
            else:
                emit(child)

    emit(tree)
    return ordered


@pytest.hookimpl(specname="pytest_collection", tryfirst=True)
def pytest_collection_contiguous_args(session):  # pytest hook
    config = session.config
    if config.getoption("pyargs", False):
        return
    config.args[:] = contiguous_args(config.args, config.invocation_params.dir)
    return
