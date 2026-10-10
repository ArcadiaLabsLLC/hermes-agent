"""The kanban write guard also denies the runner's recorded real root (``HERMES_TEST_REAL_ROOT``).

``tests/conftest.py::_REAL_KANBAN_ROOT`` is captured from the pre-sandbox
``HERMES_HOME`` at import, which the runner has already blanked, so upstream's
guard covers ``~/.hermes`` only. ``tests/_downstream/conftest_plugin.py::
_kanban_guard_denies_recorded_root`` adds the recorded root, read per call.
"""

from __future__ import annotations

import pytest

import tests._downstream.conftest_plugin as plugin
from hermes_cli import kanban_db
from hermes_cli import kanban_db_connect as kbc


def test_a_write_under_the_recorded_real_root_is_refused(tmp_path, monkeypatch):
    real = tmp_path / "operator-home"
    real.mkdir()
    monkeypatch.setattr(plugin, "_RECORDED_REAL_ROOT", str(real))
    with pytest.raises(RuntimeError, match="recorded real root"):
        kbc.connect(real / "kanban.db")
    monkeypatch.setattr(kanban_db, "kanban_db_path", lambda board=None: real / "kanban" / "kanban.db")
    with pytest.raises(RuntimeError, match="recorded real root"):
        kbc.connect()
    assert not (real / "kanban.db").exists()


def test_a_write_beside_the_recorded_root_still_connects(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin, "_RECORDED_REAL_ROOT", str(tmp_path / "operator-home"))
    conn = kbc.connect(tmp_path / "sandbox" / "kanban.db")
    conn.close()
