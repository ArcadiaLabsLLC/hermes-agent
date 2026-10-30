"""The assembler and the pytest hooks that apply the id table.

``_merge`` builds ``ID_MARKS`` from the four class tables by CONCATENATING marks per key
in table order (fork, posix, upstream_reds, upstream_reds_v0216, upstream_reds_v0217, upstream_reds_v0222, upstream_reds_v0224, distributions): a key in two tables is a
MERGE, never an override. ``SHARED_KEYS`` names those keys, so a cross-class row is a
fact a test can pin. The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
import os
from pathlib import Path

import pytest

from tests._downstream.id_markers import (
    distributions, fork_marks, posix_marks, upstream_reds, upstream_reds_v0216, upstream_reds_v0217,
    upstream_reds_v0222, upstream_reds_v0224,
)
from tests._downstream.id_markers.distributions import REQUIRES_DISTRIBUTION
from tests._downstream.id_markers.posix_marks import IMPORT_TIME_POSIX_MODULES, IMPORT_TIME_POSIX_SHIMS
from tests._downstream.id_markers.reasons import NO_LIVE_GATEWAY_MARK, SCOPED_MONKEYPATCH_UNDO_MARK, _SCOPED_UNDO

__layer__ = "lanes"


Table = dict[str, tuple[pytest.MarkDecorator, ...]]


def _merge(*tables: Table) -> Table:
    """One id table from the class tables: marks CONCATENATED per key, in argument order."""
    merged: Table = {}
    for table in tables:
        for node, marks in table.items():
            merged[node] = (*merged.get(node, ()), *marks)
    return merged


def _shared_keys(*tables: Table) -> frozenset[str]:
    """Keys written by more than one class table -- each is a MERGE, on purpose."""
    seen: set[str] = set()
    shared: set[str] = set()
    for table in tables:
        shared |= seen & table.keys()
        seen |= table.keys()
    return frozenset(shared)


_TABLES = (
    fork_marks.ROWS, posix_marks.ROWS, upstream_reds.ROWS, upstream_reds_v0216.ROWS, upstream_reds_v0217.ROWS,
    upstream_reds_v0222.ROWS, upstream_reds_v0224.ROWS, distributions.ROWS,
)
ID_MARKS: Table = _merge(*_TABLES)
SHARED_KEYS: frozenset[str] = _shared_keys(*_TABLES)


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):  # pytest hook
    """Lend ``IMPORT_TIME_POSIX_SHIMS`` to one module's import, then take them back;
    turn a collection that failed on a ``REQUIRES_DISTRIBUTION`` import into a skip."""
    shims = IMPORT_TIME_POSIX_SHIMS.get(collector.nodeid)
    lent = [name for name in (shims or {}) if not hasattr(os, name)]
    for name in lent:
        setattr(os, name, shims[name])
    try:
        report = yield
    finally:
        for name in lent:
            delattr(os, name)
    return _skip_if_posix_module_missing(
        collector, _skip_if_distribution_missing(collector, report)
    )


def _skip_if_posix_module_missing(collector, report):
    """Turn a collection that failed on its row's POSIX-only import into a skip."""
    module = IMPORT_TIME_POSIX_MODULES.get(collector.nodeid)
    if not (report.failed and module and f"No module named '{module}'" in str(report.longrepr)):
        return report
    reason = f"Skipped: POSIX-only module `{module}` is imported at collection (no Windows build)"
    return pytest.CollectReport(report.nodeid, "skipped", (str(collector.path), 0, reason), [])


def _skip_if_distribution_missing(collector, report):
    if not report.failed:
        return report
    for prefix, (module, distribution) in REQUIRES_DISTRIBUTION.items():
        if (
            collector.nodeid.startswith(prefix)
            and importlib.util.find_spec(module) is None
            and f"No module named '{module}'" in str(report.longrepr)
        ):
            reason = f"Skipped: optional distribution {distribution} is not installed (no `{module}`)"
            return pytest.CollectReport(report.nodeid, "skipped", (str(collector.path), 0, reason), [])
    return report


def _base_id(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]


def _keys_for(base: str) -> list[str]:
    """``a::B::c`` -> ``["a::B::c", "a::B", "a"]``: the test id, each enclosing class, the file."""
    parts = base.split("::")
    return ["::".join(parts[:n]) for n in range(len(parts), 0, -1)]


def ids_marked(mark_name: str) -> set[str]:
    """Table ids carrying *mark_name* on this host (read by the fork's gates)."""
    return {
        node for node, marks in ID_MARKS.items()
        if any(mark.name == mark_name for mark in marks)
    }


def _narrowed_files(config) -> set[str]:
    """Files the command line narrowed to single ids (``file::test``)."""
    out: set[str] = set()
    for arg in config.args:
        if "::" not in arg:
            continue
        path = Path(arg.split("::", 1)[0])
        try:
            path = path.resolve().relative_to(config.rootpath.resolve())
        except (OSError, ValueError):
            pass
        out.add(path.as_posix())
    return out


@functools.cache
def _undo_calling_def_lines(path: str) -> frozenset[int]:
    """Every line a ``def`` (or one of its decorators) starts on, for each function in *path*
    whose body calls ``<expr>.undo()``, directly or through a same-file function it calls by
    name. A file without the text ``.undo(`` is never parsed."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return frozenset()
    if ".undo(" not in text:
        return frozenset()
    defs = [n for n in ast.walk(ast.parse(text)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    calls = {id(d): [c for c in ast.walk(d) if isinstance(c, ast.Call)] for d in defs}
    undoing = {
        id(d) for d in defs
        if any(isinstance(c.func, ast.Attribute) and c.func.attr == "undo" for c in calls[id(d)])
    }
    # A def that calls (by bare name) a same-file def that undoes, undoes too: upstream's
    # display-read tests hand ``monkeypatch`` to a module helper that calls ``.undo()``.
    while True:
        names = {d.name for d in defs if id(d) in undoing}
        grown = {
            id(d) for d in defs
            if any(isinstance(c.func, ast.Name) and c.func.id in names for c in calls[id(d)])
        } - undoing
        if not grown:
            break
        undoing |= grown
    lines: set[int] = set()
    for d in defs:
        if id(d) in undoing:
            lines.update({d.lineno, *(deco.lineno for deco in d.decorator_list)})
    return frozenset(lines)


def body_calls_monkeypatch_undo(item) -> bool:
    """True when *item* takes ``monkeypatch`` and its test function's body calls ``.undo()``,
    directly or through a same-file helper."""
    func = getattr(item, "function", None)
    if func is None or "monkeypatch" not in getattr(item, "fixturenames", ()):
        return False
    code = getattr(inspect.unwrap(func), "__code__", None)
    return code is not None and code.co_firstlineno in _undo_calling_def_lines(code.co_filename)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):  # pytest hook
    """Apply ``ID_MARKS`` before upstream's own modifyitems reads the marks."""
    matched: set[str] = set()
    collected_files: set[str] = set()
    for item in items:
        base = _base_id(item.nodeid)
        collected_files.add(base.split("::", 1)[0])
        exact = [item.nodeid] if item.nodeid != base else []
        for key in exact + _keys_for(base):
            marks = ID_MARKS.get(key)
            if marks is None:
                continue
            matched.add(key)
            for mark in marks:
                item.add_marker(mark)
        # A mid-body ``monkeypatch.undo()`` is found by the AST, never kept by id per release.
        if item.get_closest_marker(SCOPED_MONKEYPATCH_UNDO_MARK) is None and body_calls_monkeypatch_undo(item):
            item.add_marker(_SCOPED_UNDO)
    checkable = collected_files - _narrowed_files(config)
    stale = sorted(
        node for node in ID_MARKS
        if node not in matched and node.split("::", 1)[0] in checkable
    )
    if stale:
        raise pytest.UsageError(
            "tests/_downstream/id_markers/ names test ids that no longer exist "
            "in their (collected) file; delete or re-point the rows:\n  "
            + "\n  ".join(stale)
        )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):  # pytest hook
    """Skip a ``requires_no_live_gateway`` test on a machine running a gateway.

    Runs before any fixture, so it reads the real process table the test will
    read. A live gateway there (the operator's, or a sibling lane's) is found by
    the fleet-wide liveness poll and vouches for whatever the test relaunched.
    """
    if item.get_closest_marker(NO_LIVE_GATEWAY_MARK) is None:
        return
    from hermes_cli.gateway import find_gateway_pids

    live = sorted(find_gateway_pids(all_profiles=True))
    if live:
        pytest.skip(
            f"a hermes gateway runs on this machine (pid {live}); the test needs "
            "a fleet with none, because the liveness poll it asserts on is fleet-wide"
        )
