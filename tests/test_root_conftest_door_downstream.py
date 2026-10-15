"""The fork plugin reaches the home-I/O guard's root list only through ``tests/conftest.py``'s
public ``real_hermes_root_candidates()`` door, on the module the fork root ``conftest.py``
handed over (row L7.06, lane 1011-M4)."""

from __future__ import annotations

import os

import tests._downstream as downstream
from tests._downstream import conftest_plugin


def test_the_handed_over_module_is_the_registered_root_conftest():
    from tests import conftest

    assert downstream.root_conftest is conftest


def test_a_recorded_root_joins_the_live_guard_list(monkeypatch, tmp_path):
    from tests import conftest

    recorded = (tmp_path / "recorded-real-root").resolve()
    monkeypatch.setattr(conftest, "_REAL_HERMES_ROOT_CANDIDATES", [])
    monkeypatch.setattr(conftest_plugin, "_RECORDED_REAL_ROOT", str(recorded))

    conftest_plugin._home_io_guard_covers_recorded_root()

    assert conftest.real_hermes_root_candidates() == [recorded]
    assert conftest_plugin._real_hermes_roots() == [os.path.normcase(str(recorded))]


def test_a_half_imported_hermes_state_is_left_alone_not_a_setup_error(monkeypatch, tmp_path):
    """``hermes_state`` seen in ``sys.modules`` before its body binds the deny roots."""
    import types

    recorded = str(tmp_path / "recorded-real-root")
    half = types.ModuleType("hermes_state")

    assert conftest_plugin._deny_recorded_root_on_state_db_guard(half, recorded, monkeypatch) is False
    assert not hasattr(half, "_STATE_DB_GUARD_EXTRA_DENY_ROOTS")

    # Positive control: the same module once its body has bound the guard's names.
    half._STATE_DB_GUARD_BYPASS = False
    half._STATE_DB_GUARD_EXTRA_DENY_ROOTS = ()
    assert conftest_plugin._deny_recorded_root_on_state_db_guard(half, recorded, monkeypatch) is True
    assert half._STATE_DB_GUARD_EXTRA_DENY_ROOTS == (
        (tmp_path / "recorded-real-root").expanduser().resolve(),
    )
