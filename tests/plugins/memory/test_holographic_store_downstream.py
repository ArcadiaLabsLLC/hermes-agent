"""Fork-owned half of ``tests/plugins/memory/test_holographic_store.py``.

Upstream's ``test_failed_write_does_not_pin_write_lock`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import pytest

from plugins.memory.holographic.store import MemoryStore
from tests.plugins.memory.test_holographic_store import (  # noqa: F401 — upstream names the moved tests use
    _clean_shared_registry,
    db_path,
)


class TestConcurrency:

    def test_failed_write_does_not_pin_write_lock(self, db_path):
        """A write that raises mid-method must not leave an open transaction
        holding the SQLite write lock (autocommit isolation_level=None)."""
        broken = MemoryStore(db_path)
        sibling = MemoryStore(db_path)
        try:
            # SCOPED (EG-0.1 / ML-4). The throwing ``_rebuild_bank`` must be
            # gone before the sibling write below, which needs the REAL rebuild
            # to run — that is the whole point of the second half. The old
            # spelling reached that state with ``monkeypatch.undo()``, which
            # unwinds the SHARED per-test instance: it also dropped the root
            # conftest's ``_hermetic_environment`` pins (HERMES_HOME redirected
            # to a tempdir, credential env vars blanked). Nothing below is
            # env-bound, so that was safe by accident rather than by
            # construction — which is precisely the accident this stage stops
            # relying on.
            with pytest.MonkeyPatch.context() as patched:
                patched.setattr(
                    MemoryStore,
                    "_rebuild_bank",
                    lambda self, category: (_ for _ in ()).throw(RuntimeError("boom")),
                )
                with pytest.raises(RuntimeError, match="boom"):
                    broken.add_fact("write that fails after the INSERT")

            # No dangling transaction: the connection reports autocommit state
            # and the sibling can write immediately.
            assert broken._conn.in_transaction is False
            sibling.add_fact("sibling write right after the failure")
        finally:
            broken.close()
            sibling.close()
