"""One agent's prompt details, built when its panel opens (``runtime.prompt_observability.agent``).

Owner ruling 2026-11-22: the ``prompt_observability`` section leaves the agent-list frame and is built
for ONE agent, on open. These pin the one-agent build (only that agent's row, no other lane's persisted
row) and the read verb's honest miss.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime import prompt_observability as po
from agent_runtime.serve_rpc import console_operations as rpc
from agent_runtime.serve_rpc.registry import method_tier
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401  (fixtures)


def _persona(persona_id: str):
    return SimpleNamespace(id=persona_id, hermes_profile=persona_id, display_name=persona_id.title(),
                           role=persona_id, skills=["alpha"])


def _instance(persona_id: str):
    return SimpleNamespace(id=f"personainst_{persona_id}", persona_id=persona_id,
                           session_id=f"sess_{persona_id}", current_task_id=None, goal_id=None)


def _rows_by_instance(section) -> set[str]:
    return {row.get("persona_instance_id") for row in section["chat_contexts"]}


def test_one_agent_builds_only_that_agents_row(isolate_agent_runtime_root):
    personas = [_persona("dev"), _persona("ops")]
    roster = [_instance("dev"), _instance("ops")]

    whole = po.snapshot_prompt_observability(personas=personas, persona_instances=roster)
    one = po.snapshot_prompt_observability(personas=personas, persona_instances=roster,
                                           only_instance_id="personainst_ops")

    assert _rows_by_instance(whole) == {"personainst_dev", "personainst_ops"}
    assert _rows_by_instance(one) == {"personainst_ops"}
    # The section keeps its shape: the panels read one agent's answer exactly as they read the frame's.
    assert set(one) == set(whole)
    assert one["skills_catalogs_ref"]["hashes"]


def test_one_agents_read_loads_no_other_lanes_persisted_row(isolate_agent_runtime_root):
    # A legacy row keyed by its session alone: live for whichever build counts that session as live.
    po.persist_prompt_observability_context({
        "context_id": "ctx_dev_turn",
        "persona_id": "dev",
        "session_id": "sess_dev",
        "prompt_layers": [],
    })
    roster = [_instance("dev"), _instance("ops")]

    one = po.snapshot_prompt_observability(personas=[_persona("dev"), _persona("ops")],
                                           persona_instances=roster, only_instance_id="personainst_ops")

    assert "ctx_dev_turn" not in {row.get("context_id") for row in one["chat_contexts"]}
    assert _rows_by_instance(one) == {"personainst_ops"}
    assert one["chat_contexts_ref"]["live_count"] == 1


def test_the_read_verb_builds_a_placed_agent_and_misses_honestly(placed_agent):
    identifier = placed_agent["persona_instance_id"]

    reply = rpc.prompt_observability_agent("one", {"instance_id": identifier})

    assert "result" in reply, reply
    result = reply["result"]
    assert result["found"] is True and result["instance_id"] == identifier
    assert _rows_by_instance(result) == {identifier}
    assert rpc.prompt_observability_agent("gone", {"instance_id": "personainst_gone"})["result"] == {
        "found": False, "instance_id": "personainst_gone"}
    assert method_tier("runtime.prompt_observability.agent") == "read"
