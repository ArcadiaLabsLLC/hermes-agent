"""The assembler and the pytest hooks that apply the id table.

``_merge`` builds ``ID_MARKS`` from the four class tables by CONCATENATING marks per key
in table order (fork, posix, upstream_reds, distributions): a key in two tables is a
MERGE, never an override. ``SHARED_KEYS`` names those keys, so a cross-class row is a
fact a test can pin. The map is ``tests/_downstream/id_markers/__init__.py``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from tests._downstream.id_markers import distributions, fork_marks, posix_marks, upstream_reds
from tests._downstream.id_markers.distributions import REQUIRES_DISTRIBUTION
from tests._downstream.id_markers.posix_marks import IMPORT_TIME_POSIX_SHIMS
from tests._downstream.id_markers.reasons import NO_LIVE_GATEWAY_MARK

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


_TABLES = (fork_marks.ROWS, posix_marks.ROWS, upstream_reds.ROWS, distributions.ROWS)
ID_MARKS: Table = _merge(*_TABLES)
SHARED_KEYS: frozenset[str] = _shared_keys(*_TABLES)


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):  # noqa: D401 — pytest hook
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
    return _skip_if_distribution_missing(collector, report)


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


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):  # noqa: D401 — pytest hook
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
def pytest_runtest_setup(item):  # noqa: D401 — pytest hook
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
