"""tests/_downstream/plugin_module_keep.py: a kept plugin module is re-used only when a cold import would match.

Each case loads a toy bundled plugin through the keep wrapper around upstream's real
``_load_directory_module``; a re-use hands back the SAME module object, a cold load a new one.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import plugins
from hermes_cli.plugins_loader import PluginLoaderMixin

from tests._downstream import plugin_module_keep as keep

_TOY = "hermes_plugins.h3_keep_toy"


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """A toy bundled plugin plus a load function that goes through the keep wrapper (keep ON)."""

    monkeypatch.setenv(keep.ENV, "1")
    dep = types.ModuleType("h3_keep_toy_dep")
    dep.helper = lambda: "real"
    monkeypatch.setitem(sys.modules, "h3_keep_toy_dep", dep)
    root = tmp_path / "toy"
    root.mkdir()

    def write(body: str) -> None:
        (root / "__init__.py").write_text(body, encoding="utf-8")

    write("STATE = 'initial'\nREGISTRY = {}\n")
    load = keep._keeping_load(PluginLoaderMixin._load_directory_module)
    manifest = SimpleNamespace(source="bundled", path=str(root))
    keep.clear()

    def run():
        return load(SimpleNamespace(), manifest, module_name=_TOY)

    yield SimpleNamespace(write=write, load=run, dep=dep)
    keep.clear()
    for name in [n for n in sys.modules if n == _TOY or n.startswith(_TOY + ".")]:
        del sys.modules[name]


def test_an_unchanged_module_is_reused_and_its_rebound_globals_are_restored(toy):
    """Killing mutation: drop ``namespace.update(saved)`` from ``_reinstall``."""

    first = toy.load()
    first.STATE = "rebound by register()"
    first.EXTRA = 1
    second = toy.load()
    assert second is first
    assert second.STATE == "initial" and not hasattr(second, "EXTRA")


def test_a_mutated_module_level_container_loads_cold(toy):
    """Killing mutation: drop the ``kept.contents`` loop from ``_cold_reason``."""

    first = toy.load()
    first.REGISTRY["leaked"] = True
    second = toy.load()
    assert second is not first and second.REGISTRY == {}


def test_a_patched_import_capture_loads_cold(toy, monkeypatch):
    """Killing mutation: drop the ``kept.captures`` loop from ``_cold_reason``."""

    toy.write("from h3_keep_toy_dep import helper\n")
    first = toy.load()
    assert toy.load() is first
    monkeypatch.setattr(toy.dep, "helper", lambda: "patched")
    second = toy.load()
    assert second is not first and second.helper() == "patched"


def test_an_environment_change_the_module_names_loads_cold(toy, monkeypatch):
    """Killing mutation: drop the ``kept.env`` loop from ``_cold_reason``."""

    monkeypatch.delenv("H3_KEEP_TOY_FLAG", raising=False)
    toy.write("import os\nFLAG = os.environ.get('H3_KEEP_TOY_FLAG')\n")
    first = toy.load()
    assert toy.load() is first
    monkeypatch.setenv("H3_KEEP_TOY_FLAG", "on")
    second = toy.load()
    assert second is not first and second.FLAG == "on"


def test_a_module_holding_the_test_home_is_never_kept(toy):
    """Killing mutation: drop the ``kept.reasons`` check from ``_cold_reason``."""

    toy.write("from hermes_constants import get_hermes_home\nHOME = str(get_hermes_home())\n")
    first = toy.load()
    assert toy.load() is not first


def test_keep_is_off_by_default(toy, monkeypatch):
    """Killing mutation: make ``enabled()`` return True."""

    monkeypatch.delenv(keep.ENV)
    first = toy.load()
    assert toy.load() is not first


def test_the_cold_fixture_bypasses_the_keep(toy, cold_plugin_discovery):
    """Killing mutation: drop ``_bypassed()`` from the wrapper's guard."""

    first = toy.load()
    assert toy.load() is not first


def _registered():
    from tools.registry import registry

    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    manager = plugins.get_plugin_manager()
    return {
        "tools": sorted(registry.get_all_tool_names()),
        "hooks": {name: len(cbs) for name, cbs in manager._hooks.items() if cbs},
        "plugins": sorted((key, bool(p.enabled), p.error) for key, p in manager._plugins.items()),
    }


def test_kept_bundled_modules_register_what_a_cold_load_registers(monkeypatch):
    """The real bundled tree, keep ON: the second discovery re-uses modules and the registries match cold.
    Killing mutation: in ``_reinstall`` hand back the module without putting it in ``sys.modules``."""

    keep.install_if_imported()
    cold = _registered()
    monkeypatch.setenv(keep.ENV, "1")
    keep.clear()
    _registered()
    hits = keep.stats()["hits"]
    warm = _registered()
    assert keep.stats()["hits"] > hits, "no module was re-used: the comparison would prove nothing"
    assert cold["plugins"]
    assert warm == cold
    keep.clear()
