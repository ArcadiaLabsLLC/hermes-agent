"""Fork-owned half of ``tests/hermes_state/test_session_db_read_conn_pool.py``.

Upstream's ``test_permits_are_not_stranded_by_a_failed_open`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import pytest

from tests.hermes_state.test_session_db_read_conn_pool import (  # noqa: F401 — upstream names the moved tests use
    db,
)


@pytest.mark.requires_wal
def test_permits_are_not_stranded_by_a_failed_open(db, monkeypatch):
    """A failed open must return its permit, or the ceiling ratchets to zero.

    A permit leaked per failure is not a transient error: it permanently
    shrinks the read path, so a burst of transient open failures would silently
    demote every later read to the writer lock for the life of the process.
    """
    import sqlite3 as _sqlite3

    import hermes_state as _hs
    from hermes_state import _READ_POOL_MAX

    def boom(*a, **kw):
        raise _sqlite3.OperationalError("simulated open failure")

    with monkeypatch.context() as fault:
        fault.setattr(_hs, "_connect_tracked_db", boom)
        for _ in range(_READ_POOL_MAX * 3):
            assert db._get_read_conn() is None
            db._read_open_failed_at = 0.0    # defeat the backoff so every call opens

    db._read_open_failed_at = 0.0
    held = [db._checkout_read_conn() for _ in range(_READ_POOL_MAX)]
    try:
        assert all(c is not None for c in held), (
            "permits were stranded by failed opens -- the ceiling ratcheted down"
        )
    finally:
        for c in held:
            if c is not None:
                db._close_read_conn(c)
