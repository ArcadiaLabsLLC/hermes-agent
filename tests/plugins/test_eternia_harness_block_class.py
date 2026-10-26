"""RT-SAFETY-BLOCK-CLASS-FIELD — a blocked terminal result says ``block_class``.

Plan ``planned/safety-block-recovery-2026-10-25.md`` §2.2-2.3. The plugin's real
``register`` runs against a recording context, so the hook under test is the one
the plugin registers. Killing mutations (recorded in the landing commit):
``block_class`` answering ``final`` always -> the fixable case reds; drop the
``transform_tool_result`` registration -> the registered-hook walk reds.
"""

import importlib.util
import json
from pathlib import Path

from agent_runtime.terminal_block_class import SAFETY_BLOCK_GUIDANCE
from tools.self_repo_guard import _block_message
from tools.self_repo_guard_vars import UNRESOLVED_ROOT, unresolved_operation
from tools.terminal_tool_guards import _blocked_json

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
ROOT = Path("X:/live/hermes-agent")


def _plugin():
    spec = importlib.util.spec_from_file_location("_eternia_harness_block_class_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _transformers():
    hooks = []

    class RecordingCtx:
        def register_hook(self, name, callback):
            hooks.append((name, callback))

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    _plugin().register(RecordingCtx())
    return [callback for name, callback in hooks if name == "transform_tool_result"]


def _classified(result: str) -> list:
    """Every registered transformer's answer; the first string wins, as in model_tools."""
    answers = [callback(tool_name="terminal", args={"command": "git checkout x"}, result=result)
               for callback in _transformers()]
    return [answer for answer in answers if isinstance(answer, str)]


def test_an_unresolved_variable_block_is_fixable():
    unresolved = unresolved_operation("git checkout", UNRESOLVED_ROOT / "lr")
    (answer,) = _classified(_blocked_json(_block_message(unresolved, ROOT), "blocked"))
    assert json.loads(answer)["block_class"] == "fixable"


def test_a_live_checkout_block_is_final():
    """Positive control: the same envelope, the guard's other message."""
    (answer,) = _classified(_blocked_json(_block_message("git checkout", ROOT), "blocked"))
    payload = json.loads(answer)
    assert payload["block_class"] == "final" and payload["status"] == "blocked" and payload["exit_code"] == 1


def test_other_results_are_left_alone():
    assert _classified(json.dumps({"output": "ok", "exit_code": 0, "error": None})) == []
    assert _classified(_blocked_json("Blocked: gateway lifecycle", "error")) == []


def test_the_guidance_line_renders_only_with_the_terminal_on_the_t6b_wire():
    module = _plugin()
    assert SAFETY_BLOCK_GUIDANCE in module.render_tool_guidance({"tool_names": "read_file,terminal,tool_describe"})
    assert SAFETY_BLOCK_GUIDANCE not in module.render_tool_guidance({"tool_names": "read_file,tool_describe"})
    # Off the T6b wire the section stays empty: upstream's exact prompt bytes hold.
    assert SAFETY_BLOCK_GUIDANCE not in module.render_tool_guidance({"tool_names": "read_file,terminal"})
