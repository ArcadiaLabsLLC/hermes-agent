"""Fork-owned half of ``tests/providers/test_entry_point_discovery.py``.

The fork split plugin discovery into ``hermes_cli.plugins_discovery``, which is
where ``_get_enabled_plugins`` / ``_get_disabled_plugins`` are read now.
Upstream's ``_enable`` patches them on ``hermes_cli.plugins``, so the two tests
that need an entry point ENABLED are strict xfail rows in
``tests/_downstream/id_markers.py``; these are the same tests with ``_enable``
patching the module discovery reads. The fakes and the autouse
``_restore_real_discovery`` are upstream's, imported by name.
"""

from __future__ import annotations

import providers
from tests.providers.test_entry_point_discovery import (  # noqa: F401 — upstream names the moved tests use
    _clear_provider_caches,
    _FakeEntryPoints,
    _FakeEP,
    _register_via_callable,
    _register_via_module,
    _restore_real_discovery,
)


def _enable(monkeypatch, *names, disabled=()):
    """Gate helper: mark entry-point names enabled/disabled in config.

    ``_discover_entry_point_providers`` enforces the PluginManager's
    ``plugins.enabled`` opt-in allow-list, so tests must enable their fake
    entry points explicitly.
    """
    import hermes_cli.plugins_discovery as hp

    monkeypatch.setattr(hp, "_get_enabled_plugins", lambda: set(names))
    monkeypatch.setattr(hp, "_get_disabled_plugins", lambda: set(disabled))


def test_entry_point_callable_and_module_targets(monkeypatch):
    fake_eps = _FakeEntryPoints(
        [
            _FakeEP("ep-callable", _register_via_callable),
            _FakeEP("ep-module", _register_via_module),
        ]
    )
    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda: fake_eps)
    _enable(monkeypatch, "ep-callable", "ep-module")
    _clear_provider_caches()
    try:
        assert providers.get_provider_profile("ep-callable") is not None
        assert providers.get_provider_profile("epc") is not None  # alias
        assert providers.get_provider_profile("ep-module") is not None
    finally:
        _clear_provider_caches()


def test_entry_point_failure_is_isolated(monkeypatch):
    def _boom():
        raise RuntimeError("broken plugin")

    fake_eps = _FakeEntryPoints(
        [
            _FakeEP("broken", _boom),
            _FakeEP("ep-callable", _register_via_callable),
        ]
    )
    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda: fake_eps)
    _enable(monkeypatch, "broken", "ep-callable")
    _clear_provider_caches()
    try:
        # A broken entry point must not prevent the good one from registering.
        assert providers.get_provider_profile("ep-callable") is not None
    finally:
        _clear_provider_caches()


def _ep_callable_loads(monkeypatch, *enabled, disabled=()) -> bool:
    fake_eps = _FakeEntryPoints([_FakeEP("ep-callable", _register_via_callable)])
    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", lambda: fake_eps)
    _enable(monkeypatch, *enabled, disabled=disabled)
    _clear_provider_caches()
    try:
        return providers.get_provider_profile("ep-callable") is not None
    finally:
        _clear_provider_caches()


def test_entry_point_not_enabled_is_skipped(monkeypatch):
    """Upstream's copy passes vacuously on the fork (its ``_enable`` never reaches
    the gate, so nothing is enabled); this one gates through the real reader,
    with the enabled case as its positive control."""

    assert _ep_callable_loads(monkeypatch, "ep-callable") is True
    assert _ep_callable_loads(monkeypatch, "some-other-plugin") is False


def test_entry_point_disabled_wins_over_enabled(monkeypatch):
    """Same vacuity as above; the enabled-only load is the control."""

    assert _ep_callable_loads(monkeypatch, "ep-callable") is True
    assert (
        _ep_callable_loads(monkeypatch, "ep-callable", disabled=("ep-callable",))
        is False
    )
