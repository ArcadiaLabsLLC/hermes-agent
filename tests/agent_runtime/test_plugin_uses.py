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
  plugin is loaded on the next build" red (retired 2026-11-23 with the forced
  re-discovery it guarded; its successor is "loaded once" below).

Lane w1123a-plugins (2026-11-23), red recorded, each alone, restored:
* ``_sync_active_manager`` without ``manager.load_admitted()`` -> "a newly
  needed plugin is loaded once, beside the ones already loaded" red;
* ``_live_load`` without ``_write_local_row`` -> "a plugin outside the
  committed record is recorded on first load, then held" red;
* ``ensure_plugin_tools_discovered`` without ``admit_for_toolsets`` -> "a tool
  list admits the plugins of the toolsets it asks for" red;
* ``_row_needed`` ignoring ``platforms`` -> "the serve keeps every platform
  plugin" red;
* the serve's warm-up back on ``get_tool_definitions(quiet_mode=True)`` ->
  "the serve's warm-up loads only Home's agent's plugins" red;
* ``PluginManager._gate_manifest`` without the ``_ADMIT_SKIP`` check -> "a
  newly needed plugin is loaded once, beside the ones already loaded" red.
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


# ── the serve and the local record (lane w1123a-plugins) ─────────────────────


def _plugin(home, name, body, version="1.0.0"):
    plugin = home / "plugins" / name
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(f'name: {name}\nversion: "{version}"\n', encoding="utf-8")
    lines = [
        "from pathlib import Path",
        "def _h(args, **kw):",
        "    return '{}'",
        "def register(ctx):",
        f"    with open(Path(__file__).parent.parent / 'loads.txt', 'a') as f: f.write('{name} ')",
        *(f"    {line}" for line in body),
    ]
    (plugin / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tool(name, toolset):
    schema = {"name": name, "description": "x", "parameters": {"type": "object", "properties": {}}}
    return f"ctx.register_tool(name={name!r}, toolset={toolset!r}, handler=_h, schema={schema!r})"


@pytest.fixture
def plugin_home(tmp_path, monkeypatch):
    from hermes_cli import plugins as plugin_mod

    home = tmp_path / "home"
    (tmp_path / "bundled").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(tmp_path / "bundled"))
    _plugin(home, "p-hook", ["ctx.register_hook('pre_tool_call', lambda **kw: None)"])
    _plugin(home, "p-lens", [_tool("p_lens_look", "p_lens")])
    _plugin(home, "p-ha", [_tool("p_ha_state", "p_ha")], version="2.0.1")
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [p-hook, p-lens, p-ha]\n  disabled: []\n", encoding="utf-8")
    monkeypatch.setattr(plugin_mod, "_plugin_managers_by_home", {})
    monkeypatch.setattr(plugin_mod, "_plugin_manager", None)
    yield home
    for manager in list(plugin_mod._plugin_managers_by_home.values()):
        manager.unload()


def _loads(home):
    path = home / "plugins" / "loads.txt"
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def _new_process():
    """A fresh serve process: no plugin_uses state, no plugin managers."""

    from hermes_cli import plugins as plugin_mod

    for manager in list(plugin_mod._plugin_managers_by_home.values()):
        manager.unload()
    plugin_mod._plugin_managers_by_home.clear()
    plugin_mod._plugin_manager = None
    plugin_uses._reset()


def test_a_plugin_outside_the_committed_record_is_recorded_on_first_load_then_held(plugin_home, caplog):
    from hermes_cli import plugins as plugin_mod

    plugin_uses.enable_selective_load(serve=True)
    plugin_mod.discover_plugins()
    assert sorted(_loads(plugin_home)) == ["p-ha", "p-hook", "p-lens"], "unknown to both records: loaded"
    local = json.loads(plugin_uses.local_record_path(plugin_home).read_text(encoding="utf-8"))["plugins"]
    assert local["p-ha"] == {"version": "2.0.1", "toolsets": ["p_ha"], "registers": []}
    assert "register_hook" in local["p-hook"]["registers"]

    _new_process()
    caplog.set_level("INFO", logger="agent_runtime.plugin_uses")
    plugin_uses.enable_selective_load(serve=True)
    plugin_mod.discover_plugins()
    assert sorted(_loads(plugin_home)) == ["p-ha", "p-hook", "p-hook", "p-lens"], \
        "recorded: held when no readied agent uses its toolset; the hook still loads"
    assert "p-ha" not in plugin_mod.get_plugin_manager()._plugins
    assert "op=recorded" not in caplog.text, "a recorded plugin is not recorded again"

    # A new version is a plugin the record does not know yet.
    (plugin_home / "plugins" / "p-ha" / "plugin.yaml").write_text('name: p-ha\nversion: "2.1.0"\n', encoding="utf-8")
    _new_process()
    plugin_uses.enable_selective_load(serve=True)
    plugin_mod.discover_plugins()
    assert _loads(plugin_home).count("p-ha") == 2


def test_a_newly_needed_plugin_is_loaded_once_beside_the_ones_already_loaded(plugin_home):
    from hermes_cli import plugins as plugin_mod
    from tools.registry import registry

    plugin_uses.enable_selective_load(serve=True)
    plugin_mod.discover_plugins()  # records all three
    _new_process()
    plugin_uses.enable_selective_load(serve=True)
    plugin_mod.discover_plugins()
    before = _loads(plugin_home)
    plugin_uses.admit_for_toolsets(["file"])
    assert _loads(plugin_home) == before, "no held plugin is needed by this widening"
    plugin_uses.admit_for_toolsets(["p_lens"])
    added = _loads(plugin_home)[len(before):]
    assert added == ["p-lens"], f"only the newly admitted plugin loads, once: {added}"
    assert registry.get_toolset_for_tool("p_lens_look") == "p_lens"
    plugin_uses.admit_for_toolsets(None)
    assert _loads(plugin_home)[len(before) + 1:] == ["p-ha"], "every toolset: the rest, once"


def test_a_tool_list_admits_the_plugins_of_the_toolsets_it_asks_for(monkeypatch):
    from tools import tool_defs_observability

    asked: list = []
    monkeypatch.setattr(plugin_uses, "admit_for_toolsets", lambda toolsets: asked.append(toolsets))
    monkeypatch.setattr("hermes_cli.plugins.discover_plugins", lambda: None)
    tool_defs_observability.ensure_plugin_tools_discovered(["web"])
    tool_defs_observability.ensure_plugin_tools_discovered()
    assert asked == [["web"], None]


def test_a_composite_or_every_toolset_admits_its_members(monkeypatch):
    monkeypatch.setattr(plugin_uses, "_sync_active_manager", lambda: None)
    plugin_uses.enable_selective_load()
    plugin_uses.admit_for_toolsets(["safe"])
    assert {"safe", "web", "image_gen"} <= plugin_uses._state["toolsets"]
    plugin_uses.admit_for_toolsets(["all"])
    assert plugin_uses._state["all"] is True


def test_the_serve_keeps_every_platform_plugin():
    assert needed("platform", frozenset({"file"}), _RECORD, platforms=True) is True
    assert needed("platform", frozenset({"file"}), _RECORD) is False


def test_the_serves_warm_up_loads_only_home_agents_plugins(monkeypatch):
    import model_tools

    from hermes_cli.harness_parts.serve import boot

    asked: list = []
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **kw: asked.append(kw))
    monkeypatch.setattr(boot, "_home_agent_toolsets", lambda: ["skills", "file"])
    monkeypatch.setattr("hermes_cli.harness_parts._upstream_doors.load_openai_cls", lambda: None)
    monkeypatch.setattr("agent_runtime.first_turn_warmup.warm_process_once_costs", lambda: {})
    boot._provider_warm_steps()
    assert asked == [{"enabled_toolsets": ["skills", "file"], "quiet_mode": True}]
