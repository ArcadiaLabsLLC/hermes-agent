"""SessionDB opens its connections with ``PRAGMA synchronous=OFF`` under test (suite-speed, lane r-state).

The test venv's SQLite (3.50.4) carries the WAL-reset bug, so ``hermes_state`` runs every
store in ``journal_mode=DELETE``; ``SessionDB``'s writer connection is ``isolation_level=None``,
so each schema statement and each autocommitted row is a journal create + fsync + delete.
Measured 2026-10-18 on the test-tmp drive: the schema script 0.20 s at the compile-time
``synchronous=FULL`` against 0.017 s at ``OFF``; ``test_hermes_state.py``'s 2,500-row
``executemany`` ran past the 30 s per-test timeout. Under the bundled gate's load that is
~10 s of SETUP per test (diagnosis.jsonl, features run 2026-10-17).

``synchronous`` only decides whether a commit survives an OS crash or power loss. No test
can observe one, so every assertion keeps its meaning; what a test CAN read is the
``PRAGMA synchronous`` value, so the level is set right after ``sqlite3.connect`` and before
``apply_database_pragmas``: a test that configures ``database.synchronous`` still gets its
level on the connection. macOS is left alone (``_enforce_macos_synchronous_full`` is a
subject there). Scope: connections ``hermes_state`` opens through ``_connect_tracked_db``
(writer, read pool, repair); raw ``sqlite3.connect`` calls in tests are untouched.
"""

from __future__ import annotations

import contextlib
import sys

import pytest

#: What the sandbox sets; the chain contract pins it.
TEST_SYNCHRONOUS_LEVEL = 0


def _no_fsync(original):
    def connect_tracked_db_no_fsync(path, tracking_path=None, **kwargs):
        conn = original(path, tracking_path=tracking_path, **kwargs)
        with contextlib.suppress(Exception):  # a test's connection double may not speak SQL
            conn.execute(f"PRAGMA synchronous={TEST_SYNCHRONOUS_LEVEL}")
        return conn

    connect_tracked_db_no_fsync.__wrapped__ = original
    return connect_tracked_db_no_fsync


@pytest.fixture(autouse=True)
def _state_db_no_fsync(monkeypatch):
    if sys.platform == "darwin":
        return
    hermes_state = sys.modules.get("hermes_state")
    if hermes_state is None:
        return
    original = getattr(hermes_state, "_connect_tracked_db", None)
    if original is None or getattr(original, "__wrapped__", None) is not None:
        return
    monkeypatch.setattr(hermes_state, "_connect_tracked_db", _no_fsync(original))
