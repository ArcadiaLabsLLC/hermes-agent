"""The id-marked fixture ``tests/_downstream/state_db_unsynced.py`` (lane r-gateway).

Killing mutation: drop the ``PRAGMA synchronous=OFF`` line from the fixture ->
``test_a_marked_test_commits_unsynced`` red (synchronous reads back 2, NORMAL).
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import STATE_DB_COMMITS_UNSYNCED_MARK


def _synchronous(tmp_path) -> int:
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        return db._conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        db.close()


@getattr(pytest.mark, STATE_DB_COMMITS_UNSYNCED_MARK)
def test_a_marked_test_commits_unsynced(tmp_path):
    assert _synchronous(tmp_path) == 0


def test_an_unmarked_test_keeps_the_production_level(tmp_path):
    assert _synchronous(tmp_path) != 0
