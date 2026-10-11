"""The writer preflight does not call a vanished WAL sidecar read-only (D3.02 = L4.05).

``hermes_state_repair.preflight_db_writability`` lists the sidecars that are files, then asks
``os.access`` of each. SQLite unlinks ``state.db-wal`` / ``-shm`` when the last connection to a
WAL database closes, and ``os.access`` is False for a missing path, so a sidecar that vanished
between the listing and the check raised ``state.db is not writable: file ...-wal is
read-only`` — the message the 2026-10-01 observer saw while a native reader came and went.

The race is made deterministic: the first ``os.access`` call on the ``-wal`` path unlinks it
and then asks the real ``os.access``.

Mutation: delete the fork's ``if not is_dir and not p.exists(): continue`` guard in
``preflight_db_writability`` -> ``test_a_wal_unlinked_after_the_listing_is_not_a_permission_error``
raises ``OperationalError ... -wal is read-only``.
"""

from __future__ import annotations

import os
import sqlite3
import stat

import pytest

import hermes_state_repair
from hermes_state_repair import preflight_db_writability


def _db_with_wal(tmp_path):
    db = tmp_path / "state.db"
    db.write_bytes(b"")
    wal = tmp_path / "state.db-wal"
    wal.write_bytes(b"")
    return db, wal


def test_a_wal_unlinked_after_the_listing_is_not_a_permission_error(tmp_path, monkeypatch):
    db, wal = _db_with_wal(tmp_path)
    real_access = os.access
    seen = []

    def access_after_checkpoint(path, mode, *args, **kwargs):
        if os.fspath(path) == os.fspath(wal) and not seen:
            seen.append(path)
            os.unlink(wal)  # the last connection closed: SQLite removed the sidecar
        return real_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(hermes_state_repair.os, "access", access_after_checkpoint)

    preflight_db_writability(db)

    assert seen, "the preflight never checked the -wal sidecar it listed"
    assert not wal.exists()


def test_a_sidecar_that_exists_and_is_read_only_still_refuses(tmp_path, monkeypatch):
    # The guard skips only a MISSING sidecar: an out-of-home read-only -wal still raises.
    monkeypatch.setattr(hermes_state_repair, "get_hermes_home", lambda: tmp_path / "elsewhere")
    db, wal = _db_with_wal(tmp_path)
    wal.chmod(stat.S_IRUSR)
    try:
        if os.access(wal, os.W_OK):
            pytest.skip("running as a user that bypasses permission bits")
        with pytest.raises(sqlite3.OperationalError, match=r"-wal is read-only"):
            preflight_db_writability(db)
    finally:
        wal.chmod(stat.S_IRUSR | stat.S_IWUSR)
