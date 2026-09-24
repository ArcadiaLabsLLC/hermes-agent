"""Fork-owned half of ``tests/hermes_state/test_retired_wal_generation_capture.py``.

Upstream's ``test_close_refuses_to_settle_without_a_capture``, ``test_failed_capture_still_pins_the_handle_and_surfaces_through_the_registry`` call ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; they are skip rows in
``tests/_downstream/id_markers.py``. These are the same tests with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import pytest

import hermes_state
from hermes_state_dbfile import RetiredGenerationCaptureError
from tests.hermes_state.test_retired_wal_generation_capture import (  # noqa: F401 — upstream names the moved tests use
    _count,
    _recover,
    _wal_only_sentinel,
    force_wal,
    lose_sidecars,
    make_db,
    not_windows,
    require_wal,
)


@not_windows
def test_close_refuses_to_settle_without_a_capture(tmp_path, force_wal, monkeypatch):
    path = tmp_path / "state.db"
    db = make_db(path, "gw-0", "seed")
    require_wal(db)
    sentinel = _wal_only_sentinel(db, "gw-0")
    lose_sidecars(path, rename=False)

    def refuse(*args, **kwargs):
        raise RetiredGenerationCaptureError("no space left on device")

    with monkeypatch.context() as fault:
        fault.setattr(hermes_state, "capture_retired_wal_generation", refuse)
        with pytest.raises(RetiredGenerationCaptureError, match="no space left"):
            db.close()
        assert db._conn is not None, "shutdown must not settle while the retired generation is uncaptured"
        assert db._retired_generation_capture is None
    db.close()
    artifact = db._retired_generation_capture
    assert artifact is not None and db._conn is None
    recovered = _recover(artifact, "state.db", tmp_path / "recovered")
    try:
        assert _count(recovered, sentinel) == 1
    finally:
        recovered.close()


@not_windows
def test_failed_capture_still_pins_the_handle_and_surfaces_through_the_registry(tmp_path, force_wal, monkeypatch, caplog):
    """Production closes go through hermes_state_registry.release_or_close, which swallows close()
    errors. A failed capture must still (a) log above DEBUG and (b) on runtimes without setconfig take
    the retention pin, so an interpreter exit before the retry cannot checkpoint the stale frames."""
    from hermes_state_registry import release_or_close

    path = tmp_path / "state.db"
    db = make_db(path, "gw-0", "seed")
    require_wal(db)
    _wal_only_sentinel(db, "gw-0")
    lose_sidecars(path, rename=False)
    pins = []
    if db._retire_connection is not None:
        monkeypatch.setattr(db, "_retire_connection", pins.append)

    def refuse(*args, **kwargs):
        raise RetiredGenerationCaptureError("no space left on device")

    with monkeypatch.context() as fault:
        fault.setattr(hermes_state, "capture_retired_wal_generation", refuse)
        with caplog.at_level("ERROR"):
            release_or_close(db)  # must not raise
    assert db._conn is not None
    assert "no space left on device" in caplog.text
    if db._retire_connection is not None:  # no setconfig: the pin must already be taken
        assert pins == [db._conn]
        db.close()  # retry succeeds and must not pin a second time
        assert pins == [pins[0]]
    else:
        db.close()
    assert db._conn is None and db._retired_generation_capture is not None
