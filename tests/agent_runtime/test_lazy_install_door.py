"""Owner ruling 2026-09-24 (1): lazy installs go through upstream's door, defaulted shut.

The fork's turn-scoped barrier (`deny_venv_installs`, the `run_conversation` wrapper) is
gone; the eternia-harness plugin sets `HERMES_DISABLE_LAZY_INSTALLS=1` so upstream's
`tools.lazy_deps._allow_lazy_installs` refuses to mutate the running venv — in a turn or
out of one — unless `HERMES_LAZY_INSTALL_TARGET` names a durable side target.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tools import lazy_deps


def _register_plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_lazy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _NullCtx:
        def __getattr__(self, name):
            return lambda *a, **k: None

    module.register(_NullCtx())


class _Installed(Exception):
    """Raised by the stub installer: the install was REACHED (nothing is installed)."""


@pytest.fixture
def missing_feature(monkeypatch):
    installs: list[tuple] = []

    def _install(specs, **kw):
        installs.append(specs)
        raise _Installed()

    monkeypatch.setattr(lazy_deps, "feature_missing", lambda feature: ("some-pkg==1.0",))
    monkeypatch.setattr(lazy_deps, "_unsupported_feature_reason", lambda feature: None)
    monkeypatch.setattr(lazy_deps, "_lazy_install_target", lambda: None)
    monkeypatch.setattr(lazy_deps, "_spec_is_safe", lambda spec: True)
    monkeypatch.setattr(lazy_deps, "_venv_pip_install", _install)
    monkeypatch.setattr("hermes_cli.config.get_managed_system", lambda: "", raising=False)
    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    return installs


def test_the_plugin_shuts_the_door_so_no_lazy_install_touches_the_venv(missing_feature):
    _register_plugin()
    feature = next(iter(lazy_deps.LAZY_DEPS))
    with pytest.raises(lazy_deps.FeatureUnavailable, match="lazy installs disabled"):
        lazy_deps.ensure(feature, prompt=False)
    assert missing_feature == []


def test_the_operator_env_reopens_it(missing_feature, monkeypatch):
    """Positive control: same missing feature, operator set `0` before the plugin -> installer runs."""
    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "0")
    _register_plugin()
    feature = next(iter(lazy_deps.LAZY_DEPS))
    with pytest.raises(_Installed):
        lazy_deps.ensure(feature, prompt=False)
    assert len(missing_feature) == 1
