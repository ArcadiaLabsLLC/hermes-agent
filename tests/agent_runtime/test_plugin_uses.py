"""The snapshot worker loads only the plugins the readied agents use (owner 2026-11-22).

``agent_runtime/plugin_uses.json`` records what every plugin registers, and the
worker holds a plugin back only when that record proves no readied agent needs
it. The record must never forget a registration: ``eternia-harness`` registers
``skill_search`` into the builtin ``skills`` toolset, which no manifest names,
and a record without it would let the worker drop the tool.

Named mutations, red recorded 2026-11-22, each alone, restored:
* ``"skills"`` removed from ``eternia-harness``'s committed toolsets -> "the
  committed record holds everything each plugin registers here" red, and "a
  plugin feeding a builtin toolset is kept" red;
* ``plugin_uses.needed`` treating an unnamed registration as droppable -> "a
  plugin that registers anything else is admitted" red;
* ``hermes_cli.plugins.PluginManager._gate_manifest`` without the filter check
  -> "a held plugin is not loaded" red;
* ``plugin_uses.admit_for_toolsets`` never re-discovering -> "a newly needed
  plugin is loaded on the next build" red.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import plugin_uses
from agent_runtime.plugin_uses import committed_plugin_uses, needed


@pytest.fixture(autouse=True)
def _no_filter():
    from hermes_cli import plugins as plugin_mod

    plugin_uses._reset()
    plugin_mod.set_plugin_load_filter(None)
    yield
    plugin_uses._reset()
    plugin_mod.set_plugin_load_filter(None)


_RECORD = {
    "web/a": {"toolsets": (), "registers": ("register_web_search_provider",)},
    "lens": {"toolsets": ("lens",), "registers": ()},
    "hooks": {"toolsets": ("lens",), "registers": ("register_hook",)},
    "stateful": {"toolsets": (), "registers": ("state:_portable_mcp_servers",)},
    "quiet": {"toolsets": (), "registers": ()},
    "platform": {"toolsets": ("home",), "registers": ("register_platform",)},
}


def test_a_plugin_that_registers_anything_else_is_admitted():
    toolsets = frozenset({"file"})
    assert needed("web/a", toolsets, _RECORD) is False, "a web backend for an agent with no web tools"
    assert needed("web/a", frozenset({"web"}), _RECORD) is True
    assert needed("lens", toolsets, _RECORD) is False
    assert needed("lens", frozenset({"lens"}), _RECORD) is True
    assert needed("platform", toolsets, _RECORD) is False, "the worker runs no gateway"
    assert needed("hooks", toolsets, _RECORD) is True, "a hook reaches every turn"
    assert needed("stateful", toolsets, _RECORD) is True, "state the record cannot name"
    assert needed("quiet", toolsets, _RECORD) is True, "registered nothing where recorded"
    assert needed("not-recorded", toolsets, _RECORD) is True, "unknown to the record"


def test_a_plugin_feeding_a_builtin_toolset_is_kept():
    record = committed_plugin_uses()
    assert "skills" in record["eternia-harness"]["toolsets"]
    assert needed("eternia-harness", frozenset({"skills"})) is True


def test_the_committed_record_holds_everything_each_plugin_registers_here(tmp_path, monkeypatch):
    """Re-record live (every in-tree plugin enabled in a throwaway home) and compare."""

    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "dump_plugin_uses", Path(__file__).resolve().parents[2] / "scripts" / "dump_plugin_uses.py"
    )
    dump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dump)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    live = dump.live_record(tmp_path)
    assert live, "nothing loaded: the comparison would prove nothing"
    committed = json.loads(plugin_uses.PLUGIN_USES_PATH.read_text(encoding="utf-8"))["plugins"]
    missing = {
        key: {
            "toolsets": sorted(set(row["toolsets"]) - set(committed.get(key, {}).get("toolsets", ()))),
            "registers": sorted(set(row["registers"]) - set(committed.get(key, {}).get("registers", ()))),
        }
        for key, row in live.items()
        if key not in committed
        or set(row["toolsets"]) - set(committed[key]["toolsets"])
        or set(row["registers"]) - set(committed[key]["registers"])
    }
    assert not missing, f"run `python scripts/dump_plugin_uses.py --write`: {missing}"


class _Manifest:
    def __init__(self, key: str) -> None:
        self.key = key


def test_a_held_plugin_is_not_loaded(monkeypatch):
    from hermes_cli import plugins as plugin_mod

    manager = plugin_mod.PluginManager.__new__(plugin_mod.PluginManager)
    monkeypatch.setattr(plugin_mod, "gate_manifest", lambda *a: (_ for _ in ()).throw(AssertionError("gated")))
    plugin_mod.set_plugin_load_filter(lambda manifest: False)
    assert manager._gate_manifest(_Manifest("x"), set(), None) is False
    plugin_mod.set_plugin_load_filter(lambda manifest: True)
    with pytest.raises(AssertionError, match="gated"):
        manager._gate_manifest(_Manifest("x"), set(), None)


def test_the_filter_is_installed_only_where_selective_load_is_on(monkeypatch):
    from hermes_cli import plugins as plugin_mod

    plugin_uses.admit_for_toolsets(["file"])
    assert plugin_mod._plugin_load_filter is None, "the serve keeps every plugin"
    plugin_uses.enable_selective_load()
    plugin_uses.admit_for_toolsets(["file"])
    assert plugin_mod._plugin_load_filter is not None


def test_a_newly_needed_plugin_is_loaded_on_the_next_build(monkeypatch):
    from hermes_cli import plugins as plugin_mod

    monkeypatch.setattr(plugin_uses, "committed_plugin_uses", lambda: _RECORD)
    forced: list[bool] = []
    manager = type("M", (), {"_discovered": True, "discover_and_load": lambda self, force=False: forced.append(force)})()
    monkeypatch.setattr(plugin_mod, "get_plugin_manager", lambda: manager)
    plugin_uses.enable_selective_load()
    plugin_uses.admit_for_toolsets(["file"])
    plugin_uses.admit_for_toolsets(["file", "todo"])
    assert forced == [], "no held plugin is needed by the wider set"
    plugin_uses.admit_for_toolsets(["web"])
    assert forced == [True], "the web backend was held and is needed now"
