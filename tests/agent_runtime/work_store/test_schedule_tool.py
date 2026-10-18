"""``runtime.schedule.arm | disarm | list`` and the ``schedule_manage`` tool (dispatcher plan §2.3, §4, B4).

Both drive ``work_store.schedule_ops`` over this test's isolated ``store/schedules/``; the machine id is
the test home's own gateway install id.

Killing mutation: register ``schedule_manage`` into ``harness_core``'s ``agent_chat`` toolset instead of
the opt-in ``schedule`` toolset → ``test_the_tool_is_opt_in_never_harness_core`` red.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from agent_runtime.serve_rpc import _METHODS, _METHOD_TIERS
from agent_runtime.work_store import schedule_store
from agent_runtime.work_store.schedule_tool import SCHEDULE_TOOLSET, handle_schedule_manage

from tests.agent_runtime._serve_rpc_manifest import expected_manifest

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "eternia-harness" / "__init__.py"
VERBS = ("arm", "disarm", "list")
PROMPT_ACTION = {"type": "persona_prompt", "persona_instance_id": "inst-1", "prompt": "Say what is READY."}


def _call(verb, **params):
    replies: list = []
    context = SimpleNamespace(spawn_reply=lambda reply: replies.append(reply()) or True, caller=None)
    assert _METHODS[f"runtime.schedule.{verb}"](7, params, context) == {"deferred": True}
    [reply] = replies
    return reply


def test_the_three_verbs_are_console_methods_in_the_manifest():
    manifest = expected_manifest()
    for verb in VERBS:
        name = f"runtime.schedule.{verb}"
        assert _METHOD_TIERS[name] == "console" and name in manifest["methods"]


def test_arm_list_disarm_round_trip():
    reply = _call("arm", key="morning", trigger={"kind": "every", "minutes": 30}, action=PROMPT_ACTION)
    schedule = reply["result"]["schedule"]
    assert schedule["key"] == "morning" and schedule["action"] == PROMPT_ACTION
    assert schedule["trigger"]["kind"] == "every" and schedule["next_fire"] and schedule["armed_by"] == "operator"
    assert [s["key"] for s in _call("list")["result"]["schedules"]] == ["morning"]
    assert _call("disarm", key="morning")["result"] == {"key": "morning", "disarmed": True}
    assert _call("list")["result"]["schedules"] == []


def test_arm_reads_an_upstream_cron_job():
    job = {"schedule": {"kind": "interval", "minutes": 15}}
    reply = _call("arm", key="from-cron", cron_job=job, action=PROMPT_ACTION)
    assert reply["result"]["schedule"]["trigger"]["minutes"] == 15


def test_refusals_carry_their_reason():
    bad = _call("arm", key="x", trigger={"kind": "every", "minutes": 0}, action=PROMPT_ACTION)
    assert bad["error"]["code"] == -32602 and bad["error"]["data"]["reason"] == "schedule_invalid"
    off = _call("arm", key="b", trigger={"kind": "every", "minutes": 5},
                action={"type": "start_batch", "workspace_id": "ws", "plan_id": "BATCH-ABCDEF"})
    assert off["error"]["code"] == 4090 and off["error"]["data"]["reason"] == "automation_off"
    assert _call("arm", key="", trigger={}, action={})["error"]["data"]["reason"] == "invalid_request"


def test_the_tool_arms_only_a_persona_prompt():
    out = json.loads(handle_schedule_manage({"action": "arm", "key": "t1", "persona_instance_id": "inst-1",
                                             "prompt": "ping", "trigger": {"kind": "at",
                                                                           "at": "2026-10-19T08:00:00+00:00"}},
                                            task_id="sess-1"))
    assert out["schedule"]["action"]["type"] == "persona_prompt"
    assert out["schedule"]["armed_by"] == "tool:schedule_manage:sess-1"
    assert [r.key for r in schedule_store.load_all()] == ["t1"]
    refused = json.loads(handle_schedule_manage({"action": "arm", "key": "t2", "trigger": {"kind": "every",
                                                                                         "minutes": 5}}))
    assert refused["error"] == "schedule_invalid"
    assert json.loads(handle_schedule_manage({"action": "list"}))["schedules"][0]["key"] == "t1"


def _plugin_tools() -> dict[str, str]:
    """The plugin's real ``register`` against a recording context: tool name -> toolset."""

    spec = importlib.util.spec_from_file_location("_eternia_harness_schedule_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools: dict[str, str] = {}

    class RecordingCtx:
        def register_tool(self, name, toolset, **_kwargs):
            tools[name] = toolset

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    module.register(RecordingCtx())
    return tools


def test_the_tool_is_opt_in_never_harness_core():
    from agent_runtime.harness_toolset import HARNESS_CORE_INCLUDES

    tools = _plugin_tools()
    assert "skill_search" in tools, f"positive control: the walk saw the real tool list, got {tools}"
    assert tools["schedule_manage"] == SCHEDULE_TOOLSET == "schedule"
    assert SCHEDULE_TOOLSET not in HARNESS_CORE_INCLUDES
