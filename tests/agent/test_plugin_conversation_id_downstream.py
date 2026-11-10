"""Fork half of ``tests/agent/test_plugin_conversation_id.py``.

The bundled eternia-harness plugin (kind backend, auto-loaded) registers its own
``pre_tool_call`` hook (``refuse_tool_call``) ahead of the probe plugin's, so upstream's
fixture, which reads the event list off the FIRST ``pre_tool_call`` hook, reaches the
harness module and finds no ``events``. Upstream's two probe tests run here unchanged
against a fixture that takes the probe plugin's own hook; the upstream ids carry an
xfail row in ``tests/_downstream/id_markers/fork_marks.py``.

Killing mutation (applied, red recorded, reverted): drop ``conversation_id`` from
``model_tools._CallIds.hook_kwargs`` -> all three re-run cases red (3 failed).
"""
import pytest

from tests.agent.test_plugin_conversation_id import (  # upstream tests re-run with the fork fixture
    PLUGIN,
    test_conversation_id_survives_compression_rotation,
    test_delegated_child_reports_its_delegators_conversation,
)

__all__ = [
    "test_conversation_id_survives_compression_rotation",
    "test_delegated_child_reports_its_delegators_conversation",
]


@pytest.fixture
def probe(tmp_path, monkeypatch):
    from hermes_cli import plugins
    from tools.registry import registry

    home = tmp_path / "home"
    plugin = home / "plugins" / "conv_probe"
    plugin.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text("plugins:\n  enabled: [conv_probe]\n")
    (plugin / "plugin.yaml").write_text("name: conv_probe\nversion: '0.1.0'\n")
    (plugin / "__init__.py").write_text(PLUGIN)
    manager = plugins.PluginManager()
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)
    manager.discover_and_load()
    (hook,) = [h for h in manager._hooks["pre_tool_call"] if "events" in h.__globals__]
    yield hook.__globals__["events"]
    registry.deregister("conv_probe")
