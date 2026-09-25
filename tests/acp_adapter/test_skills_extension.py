from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from acp import RequestError

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager, SessionState
from acp_adapter.tools import build_tool_complete, build_tool_start


@pytest.mark.asyncio
async def test_capability_and_exact_live_session_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    manifest = tmp_path / "skills" / "example" / "SKILL.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("---\nname: example\ndescription: Complete document\n---\nLast line", encoding="utf-8")
    agent = SimpleNamespace(tools=[{"function": {"name": "skill_view"}}])
    state = SessionState("session-a", agent, cwd=str(tmp_path))
    manager = Mock(spec=SessionManager)
    manager.peek_session.side_effect = lambda sid: state if sid == state.session_id else None
    server = HermesACPAgent(manager)
    handshake = await server.initialize(1)
    assert handshake.agent_capabilities.field_meta["hermesSkills"]["version"] == 1
    rows = await server.ext_method("hermes/skills/list", {"sessionId": state.session_id})
    assert any(row["id"] == "example" for row in rows["skills"])
    detail = await server.ext_method("hermes/skills/detail", {
        "sessionId": state.session_id, "skillId": "example"})
    assert detail["sessionId"] == state.session_id
    assert detail["skill"]["content"].endswith("Last line")
    with pytest.raises(RequestError) as error:
        await server.ext_method("hermes/skills/list", {"sessionId": "other-session"})
    assert error.value.code == -32002
    manager.get_session.assert_not_called()
    with pytest.raises(RequestError) as unknown:
        await server.ext_method("not-implemented", {})
    assert unknown.value.code == -32601


def test_tool_metadata_carries_real_call_identity_and_success():
    start = build_tool_start("call-a", "skill_view", {"name": "example"})
    done = build_tool_complete("call-a", "skill_view", '{"success": true}', {"name": "example"})
    failed = build_tool_complete("call-a", "skill_view", '{"success": true}',
                                 {"name": "example"}, is_error=True)
    assert start.tool_call_id == done.tool_call_id == "call-a"
    assert start.field_meta["hermesSkill"] == {"id": "example", "status": "loading"}
    assert done.field_meta["hermesSkill"]["status"] == "loaded"
    assert failed.field_meta["hermesSkill"]["status"] == "failed"


def test_history_reads_the_existing_persisted_transcript(tmp_path):
    from hermes_state import SessionDB
    from agent_runtime.skill_activity import skill_load_history
    db = SessionDB(tmp_path / "state.db")
    manager = SessionManager(agent_factory=lambda: SimpleNamespace(model="test"), db=db)
    state = manager.create_session(cwd=str(tmp_path))
    state.history = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "load-a", "type": "function", "function": {
                "name": "skill_view", "arguments": '{"name":"example"}'}}]},
        {"role": "tool", "tool_call_id": "load-a", "content": '{"success":true}'},
    ]
    manager.save_session(state.session_id)
    state.history = []  # persistence, not the client's current projection, supplies the evidence
    history, complete = manager.skill_history(state.session_id)
    assert complete
    assert skill_load_history(history) == [{"id": "example", "count": 1}]
    assert manager.skill_history("unknown") == ([], False)
    db.close()
