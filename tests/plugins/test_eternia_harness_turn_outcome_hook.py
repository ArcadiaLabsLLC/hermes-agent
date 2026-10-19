"""The eternia-harness plugin feeds the turn-outcome fold from ``post_tool_call``
(``RT-TURN-LEFT-BEHIND-RECORD``, plan ``planned/p10-turn-2026-10-19.md`` §1.5 test 9).

The plugin's real ``register`` runs against a recording context, so the walk reads
the hook list the plugin actually registers. Killing mutation: drop the
``register_hook("post_tool_call", …)`` line -> the hook name is missing.
"""

import importlib.util
import json
from pathlib import Path

from agent_runtime.turn_outcome import bind_turn_outcome

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"


def _registered_hooks() -> list[tuple[str, object]]:
    spec = importlib.util.spec_from_file_location("_eternia_harness_turn_outcome_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks: list[tuple[str, object]] = []

    class RecordingCtx:
        def register_hook(self, name, callback):
            hooks.append((name, callback))

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    module.register(RecordingCtx())
    return hooks


def test_the_plugin_registers_post_tool_call_once_and_it_feeds_the_fold():
    hooks = _registered_hooks()
    names = [name for name, _ in hooks]
    assert "post_api_request" in names, f"positive control: the walk saw the real hook list, got {names}"
    assert names.count("post_tool_call") == 1
    callback = dict(hooks)["post_tool_call"]
    with bind_turn_outcome() as fold:
        callback(tool_name="terminal", args={"command": "pytest -q"}, status="error",
                 result=json.dumps({"output": "", "exit_code": 2, "error": None}))
    assert fold.block()["tests"] == [{"command": "pytest -q", "exit_code": 2, "verdict": "failed"}]
