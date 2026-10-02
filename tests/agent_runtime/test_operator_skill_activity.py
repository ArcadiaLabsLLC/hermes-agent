"""Live skill facts survive the real runner -> journal -> native read path."""
import pytest

from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.profile_runner.tool_payloads import _tool_started_payload, _tool_finished_payload
from agent_runtime.skill_activity import journal_skill_loads
from hermes_cli.harness_parts.persona.chat_events import _ChatProtocolV2Emitter
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


def test_concurrent_loads_keep_exact_evidence_after_reconstruction(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    emitter = _ChatProtocolV2Emitter(turn_id="turn", client_message_id="request", emit_frames=False)

    def read(state="running"):
        persist_mission_chat_turn(session_id=target["session_id"], client_message_id="request",
                                 turn_id="turn", state=state, elements=emitter.elements)
        result = call("read", target)
        assert "result" in result, result
        return {row["id"]: row for row in result["result"]["skill_loads"]}

    for name in ("alpha", "beta"):
        emitter.progress({**_tool_started_payload("run.tool.started", "skill_view",
                            invocation={"name": name}), "tool_call_id": name})
    started = read()
    assert {row["status"] for row in started.values()} == {"loading"}
    assert started["alpha"]["call_id"] != started["beta"]["call_id"]
    for name, success in (("beta", False), ("alpha", True)):
        emitter.progress({**_tool_finished_payload("run.tool.finished", "skill_view",
            invocation={"name": name}, result={"success": success}, duration=0.1, is_error=False),
            "tool_call_id": name})
    settled = read("completed")
    assert settled["alpha"] == {**started["alpha"], "status": "loaded"}
    assert settled["beta"] == {**started["beta"], "status": "failed"}
    assert call("read", target)["result"]["skill_loads"] == list(settled.values())
    assert "error" in call("read", {**target, "install_id": "other"})


@pytest.mark.parametrize("state", ["outcome_unknown", "interrupted", "completed", "native_committed"])
def test_unresolved_load_is_not_reported_as_running_or_success_after_turn_ends(state):
    element = dict(kind="tool", id="call", skill_load={"id": "review", "status": "loading"})
    assert journal_skill_loads([dict(turn_id="turn", state=state, elements=[element])]) == [
        {"call_id": "turn:call", "id": "review", "status": "unknown"}]


def test_only_actual_full_skill_loads_produce_evidence():
    for tool, arguments in (("read_file", {"name": "review"}),
                            ("skill_view", {"name": "review", "file_path": "notes.md"})):
        assert "skill_load" not in _tool_started_payload("run.tool.started", tool, invocation=arguments)
    assert journal_skill_loads([dict(turn_id="t", state="completed", elements=[
        dict(kind="tool", id="a", redacted=True, skill_load={"id": "secret", "status": "loaded"}),
        dict(kind="tool", id="b", skill_load={"id": "x" * 513, "status": "loaded"}),
        dict(kind="segment", id="c", skill_load={"id": "prose", "status": "loaded"}),
    ])]) == []
