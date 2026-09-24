"""Fork-owned half of ``tests/hermes_state/test_append_messages_batch.py``.

Upstream's ``test_atomicity_all_or_nothing`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import sqlite3

import pytest

from hermes_state import SessionDB
from tests.hermes_state.test_append_messages_batch import (  # noqa: F401 — upstream names the moved tests use
    _turn_messages,
    db,
)


class TestAppendMessagesBatch:

    def test_atomicity_all_or_nothing(self, db, monkeypatch):
        """A failure mid-batch leaves ZERO rows and untouched counters."""
        real_insert = SessionDB._insert_message_rows

        def failing_insert(self_db, conn, session_id, messages):
            real_conn_execute = conn.execute
            calls = {"n": 0}

            def exec_counting(sql, *args):
                if sql.lstrip().startswith("INSERT INTO messages"):
                    calls["n"] += 1
                    if calls["n"] == 3:
                        raise sqlite3.OperationalError("boom mid-batch")
                return real_conn_execute(sql, *args)

            conn.execute = exec_counting
            try:
                return real_insert(self_db, conn, session_id, messages)
            finally:
                conn.execute = real_conn_execute

        with monkeypatch.context() as fault:
            fault.setattr(SessionDB, "_insert_message_rows", failing_insert)
            with pytest.raises(sqlite3.OperationalError):
                db.append_messages_batch("sess-batch", _turn_messages())

        count = db._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 0
        row = db._conn.execute(
            "SELECT message_count, tool_call_count FROM sessions WHERE id = ?",
            ("sess-batch",),
        ).fetchone()
        assert row["message_count"] == 0
        assert row["tool_call_count"] == 0
