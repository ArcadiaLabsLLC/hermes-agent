"""Commit ``state.db`` without fsync for the ids the table marks (lane r-gateway, 2026-10-17).

The test venv's SQLite (3.50.4) carries the WAL-reset bug, so ``hermes_state`` opens every
new store in ``journal_mode=DELETE``: each autocommit statement creates, syncs and deletes
a rollback journal. On the fork's test-tmp drive that measured 5.3 ms a commit at rest and
far more while sibling lanes saturate the drive (220 % disk time, 2026-10-17), against
0.64 ms with ``synchronous=OFF``. Tests that mint several fresh stores or write hundreds of
rows then cross the fork's 30 s per-test cap on I/O alone: the child-notice profile matrix
(three schema inits a test, 3.5 s at rest, 27 s measured under contention) and the
500-row session paging test (17.6 s at rest).

For a marked test, every ``SessionDB`` connection gets ``PRAGMA synchronous=OFF`` after the
production pragmas run (``hermes_state.apply_database_pragmas``). Durability across a crash
is the only thing given up; no marked test asserts it. Journal mode, schema, locking and
every query are unchanged.
"""

from __future__ import annotations

import sys

import pytest

from tests._downstream.id_markers.reasons import STATE_DB_COMMITS_UNSYNCED_MARK as _MARK


@pytest.fixture(autouse=True)
def _state_db_commits_unsynced(request, monkeypatch):
    if request.node.get_closest_marker(_MARK) is None:
        return
    import hermes_state

    production = hermes_state.apply_database_pragmas

    def _pragmas_then_unsynced(conn, *args, **kwargs):
        production(conn, *args, **kwargs)
        conn.execute("PRAGMA synchronous=OFF")

    monkeypatch.setattr(hermes_state, "apply_database_pragmas", _pragmas_then_unsynced)


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_state_db_unsynced(config):  # noqa: D401 — pytest hook
    config.addinivalue_line(
        "markers",
        f"{_MARK}: SessionDB connections commit with PRAGMA synchronous=OFF, so fsync on the "
        "test-tmp drive cannot push the test past its cap (applied by id from "
        "tests/_downstream/id_markers/).",
    )
