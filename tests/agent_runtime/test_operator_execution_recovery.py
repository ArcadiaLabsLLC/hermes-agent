"""Exact Stop crosses clients without replacing the operator execution owner."""
from types import SimpleNamespace
import pytest

from agent.interrupt_scope import track_in_interrupt_scope
from agent_runtime.chat_turn_reservations import read_chat_turn_receipt
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.mission_chat_turns.journal import transition_mission_chat_turn
from agent_runtime.mission_chat_turns.states import MissionChatTurnPersistOutcome
from agent_runtime.operator_execution import execution_status
from tests.agent_runtime.operator_lane_fixture import OperatorLane
from tests.agent_runtime.test_operator_conversation_attachment import fixture

SEND = "runtime.chat.message"
STOP = "runtime.operator.conversation.stop"


def test_queued_stop_lost_ack_repeated_stop_and_newer_turn_are_isolated(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    monkeypatch.setattr("agent_runtime.persona_chat_history.messages._safe_curated_messages",
                       lambda *a, **kw: pytest.fail("Control must not load transcript history"))
    calls = []
    lane = OperatorLane(tmp_path / "home", lambda argv: calls.append(argv) or 0)
    old = {**target, "turn_request_id": "old", "message": "First"}
    assert lane.rpc(SEND, old)["result"]["accepted"]
    assert lane.rpc(SEND, {**old, "message": "Changed"})["error"]["data"]["reason"] == "turn_payload_conflict"
    assert lane.rpc(STOP, old)["result"]["outcome"] == "stop_requested"
    # Lose that acknowledgement and reconstruct against the same native receipt.
    assert execution_status(target["session_id"], "old")["outcome"] == "stop_requested"
    assert lane.rpc(STOP, old)["result"]["outcome"] == "stop_requested"
    lane.advance()
    assert calls == [] and read_chat_turn_receipt("old").exit_code == 130
    assert execution_status(target["session_id"], "old")["outcome"] == "stopped"
    new = {**target, "turn_request_id": "new", "message": "Second"}
    assert lane.rpc(SEND, new)["result"]["accepted"]
    assert lane.rpc(STOP, old)["result"]["outcome"] == "stopped"
    lane.advance()
    assert len(calls) == 1 and "new" in calls[0]
    assert read_chat_turn_receipt("new").exit_code == 0


def test_running_stop_uses_upstream_scope_and_completion_wins_late_stop(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    params = {**target, "turn_request_id": "running", "message": "Work"}
    interrupted = []

    def dispatch(argv):
        key = argv[argv.index("--client-message-id") + 1]
        persist_mission_chat_turn(session_id=target["session_id"], client_message_id=key,
                                 turn_id=key, elements=[], state="running")
        agent = SimpleNamespace(interrupt=lambda reason: interrupted.append(reason))
        with track_in_interrupt_scope(agent):
            wrong = lane.rpc(STOP, {**params, "workspace_id": "other"})
            assert wrong["error"]["data"]["reason"] == "workspace_changed"
            assert not interrupted
            assert lane.rpc(STOP, params)["result"]["outcome"] == "stop_requested"
            assert len(interrupted) == 1
            persist_mission_chat_turn(session_id=target["session_id"], client_message_id=key,
                                     turn_id=key, elements=[], state="completed")
            assert lane.rpc(STOP, params)["result"]["outcome"] == "finished"
            assert len(interrupted) == 1
        return 0

    lane = OperatorLane(tmp_path / "home", dispatch)
    assert lane.rpc(SEND, params)["result"]["accepted"]
    lane.advance()
    assert execution_status(target["session_id"], "running")["outcome"] == "finished"
    assert not lane.inflight


def test_restart_cannot_turn_uncertain_execution_into_confirmed_stop(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    params = {**target, "turn_request_id": "uncertain", "message": "Work"}
    original = OperatorLane(tmp_path / "home", lambda _: 0)
    ack = original.rpc(SEND, params)["result"]
    assert ack["accepted"]
    for state in ("pending", "executing", "outcome_unknown"):
        assert transition_mission_chat_turn(session_id=target["session_id"], client_message_id="uncertain",
            turn_id="uncertain", elements=[], state=state) is MissionChatTurnPersistOutcome.PERSISTED
    restarted = OperatorLane(tmp_path / "home", lambda _: 0)
    result = restarted.rpc(STOP, params)["result"]
    assert result["request_id"] == ack["request_id"]
    assert result["outcome"] == "stop_requested" and result["owner_observed"] is False
    assert read_chat_turn_receipt("uncertain").stop_requested
    assert restarted.rpc(SEND, params)["result"]["idempotent_replay"]
    assert restarted.jobs == []
    assert execution_status(target["session_id"], "uncertain")["outcome"] == "stop_requested"
