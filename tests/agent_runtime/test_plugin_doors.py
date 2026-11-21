"""The fork plugins reach the fork runtime only through their published doors (``agent_runtime/plugin_doors/``).

Row RT-FU-THE-FORK-PLUGINS-REACH-HERMES-CORE-ONLY-THROUGH-ITS-PUBLIC-DOORS; plan
``docs/agent-runtime-harness/planned/fork-plugins-public-doors-2026-11-21.md``. Upstream's boundary lint
counts a plugin's import of any Hermes package not on the published plugin API; the fork publishes ONLY
its door modules (``hermes_cli/data/plugin_api_fork.json``), and each door hands its plugin the runtime
objects themselves.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK_API = ROOT / "hermes_cli" / "data" / "plugin_api_fork.json"
DOORS = ROOT / "agent_runtime" / "plugin_doors"


def _fork_entries() -> list[str]:
    return [entry for group in json.loads(FORK_API.read_text(encoding="utf-8"))["groups"] for entry in group["entries"]]


def test_the_fork_list_publishes_exactly_the_door_modules():
    """KILLING MUTATION: add ``agent_runtime.lens.tool`` to plugin_api_fork.json (publishing an internal
    instead of a door) -> red; delete ``plugin_doors/lens.py``'s entry -> red."""
    doors = sorted(f"agent_runtime.plugin_doors.{p.stem}" for p in DOORS.glob("*.py") if p.stem != "__init__")
    assert doors, "no door modules found"
    assert sorted(_fork_entries()) == doors


def test_the_lint_reads_a_door_as_published_and_a_direct_runtime_import_as_core():
    """KILLING MUTATION: drop the fork hunk in ``hermes_cli/plugin_validate_private_imports.py::_public_api``
    -> the door import reads as a core crossing -> red."""
    from hermes_cli.plugin_validate_private_imports import _hermes_packages, _private_target, _public_api

    _public_api.cache_clear()
    core = _hermes_packages()
    for door in _fork_entries():
        assert _private_target(door, "anything", core, set()) == ""
    assert _private_target(door, "_private", core, set()) == f"{door}._private"
    assert _private_target("agent_runtime.lens.tool", "LENS_TOOLSET", core, set()) == "agent_runtime.lens.tool.LENS_TOOLSET"


def test_the_lens_door_hands_out_the_lens_tool_objects():
    door = importlib.import_module("agent_runtime.plugin_doors.lens")
    tool = importlib.import_module("agent_runtime.lens.tool")
    assert door.__all__
    for name in door.__all__:
        assert getattr(door, name) is getattr(tool, name), name


def test_a_lazy_door_serves_its_table_and_refuses_anything_else():
    """KILLING MUTATION: ``lazy_door`` ignoring the ``:attr`` rename (``attr or name`` -> ``name``) -> red."""
    from agent_runtime.plugin_doors import lazy_door

    getattr_ = lazy_door("demo", {"dumps": "json", "parse": "json:loads"})
    assert getattr_("dumps") is json.dumps
    assert getattr_("parse") is json.loads
    with pytest.raises(AttributeError, match="'demo' has no attribute 'loads'"):
        getattr_("loads")


def test_the_lens_plugin_registers_its_tools_through_the_door():
    """The plugin's own ``register`` still registers the three pull-door tools in the ``lens`` toolset."""
    spec = importlib.util.spec_from_file_location("eternia_lens_plugin", ROOT / "plugins" / "eternia-lens" / "__init__.py")
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    registered = []

    class Ctx:
        def register_tool(self, name, **kw):
            registered.append((name, kw["toolset"], kw["handler"].__name__))

    plugin.register(Ctx())
    assert registered == [("lens_read", "lens", "handle_lens_read"), ("lens_propose", "lens", "handle_lens_propose"),
                          ("lens_propose_repair", "lens", "handle_lens_propose_repair")]
