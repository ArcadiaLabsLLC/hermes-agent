"""The eternia-harness plugin registers no ``on_kanban_*`` hook (Work W5, plan
``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` §6.5).

Work is the markdown todo board written through git; the fork's kanban observers (blocked-card PM
routing, crash evidence) are retired. The plugin's real ``register`` runs against a recording
context, so the walk reads the hook list the plugin actually registers.
"""

import importlib.util
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"


def _registered_hooks() -> list[str]:
    spec = importlib.util.spec_from_file_location("_eternia_harness_no_kanban_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks: list[str] = []

    class RecordingCtx:
        def register_hook(self, name, _callback):
            hooks.append(name)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    module.register(RecordingCtx())
    return hooks


def test_the_plugin_registers_no_kanban_hook():
    hooks = _registered_hooks()
    assert "pre_tool_call" in hooks, f"positive control: the walk saw the real hook list, got {hooks}"
    assert [name for name in hooks if name.startswith("on_kanban_")] == []
