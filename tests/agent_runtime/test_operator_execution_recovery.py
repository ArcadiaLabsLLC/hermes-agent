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
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture

SEND = "runtime.chat.message"
STOP = "runtime.operator.conversation.stop"


@pytest.mark.parametrize("instance_pin", [True, False])
def test_resolved_console_send_stops_without_tools_and_keeps_admission_identity(
        tmp_path, monkeypatch, instance_pin):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    send = {**target, "turn_request_id": "resolved-send", "message": "Ordinary reply"}
    send.pop("session_id")  # The console's continue-this-thread wire shape.
    if not instance_pin:
        send.pop("persona_instance_id")
    stopped = []
    responses = []

    def dispatch(argv):
        persist_mission_chat_turn(session_id=target["session_id"],
            client_message_id="resolved-send", turn_id="resolved-send", state="running",
            elements=[], metadata={"root_chat_session_id": target["session_id"],
                                  "persona_instance_id": target["persona_instance_id"]})
        agent = SimpleNamespace(hard_interrupt=lambda reason, **kw: stopped.append(reason))
        with track_in_interrupt_scope(agent):
            response = lane.rpc(STOP, {**target, "turn_request_id": "resolved-send"})
            responses.append(response)
            if "result" not in response:
                return 1
            assert response["result"]["owner_observed"] is True
            assert stopped == ["Stopped by the user"]
            assert call("read", target)["result"]["executions"][0]["outcome"] == "stop_requested"
            persist_mission_chat_turn(session_id=target["session_id"],
                client_message_id="resolved-send", turn_id="resolved-send", state="interrupted",
                elements=[], metadata={"root_chat_session_id": target["session_id"],
                                      "persona_instance_id": target["persona_instance_id"]})
        return 130

    lane = OperatorLane(tmp_path / "home", dispatch)
    assert lane.rpc(SEND, send)["result"]["accepted"]
    original = read_chat_turn_receipt("resolved-send")
    lane.advance()
    assert "result" in responses[0], responses[0]
    assert read_chat_turn_receipt("resolved-send").exit_code == 130
    assert execution_status(target["session_id"], "resolved-send")["outcome"] == "stopped"
    receipt = read_chat_turn_receipt("resolved-send")
    assert receipt.session_scope == original.session_scope
    assert receipt.payload_fingerprint == original.payload_fingerprint
    assert lane.rpc(SEND, send)["result"]["idempotent_replay"]
    assert lane.jobs == []


@pytest.mark.parametrize("evidence, reason", [
    ("missing", "execution_scope_unresolved"),
    ("other-instance", "turn_request_conflict"),
    ("other-root", "turn_request_conflict"),
    ("explicit-other-root", "turn_request_conflict"),
])
def test_resolved_stop_requires_exact_journal_evidence(tmp_path, monkeypatch, evidence, reason):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    send = {**target, "turn_request_id": "guarded", "message": "Work"}
    send.pop("session_id")
    if evidence == "explicit-other-root":
        send["session_id"] = "different-root"
    lane = OperatorLane(tmp_path / "home", lambda _: pytest.fail("Refusal must not dispatch"))
    assert lane.rpc(SEND, send)["result"]["accepted"]
    if evidence != "missing":
        persist_mission_chat_turn(session_id=target["session_id"], client_message_id="guarded",
            turn_id="guarded", state="running", elements=[], metadata={
                "root_chat_session_id": "different-root" if evidence == "other-root" else target["session_id"],
                "persona_instance_id": "different-instance" if evidence == "other-instance" else target["persona_instance_id"],
            })
    result = lane.rpc(STOP, {**target, "turn_request_id": "guarded"})
    assert result["error"]["data"]["reason"] == reason
    assert not read_chat_turn_receipt("guarded").stop_requested
    requested = call("read", {**target, "turn_request_id": "guarded"})
    assert requested["error"]["data"]["reason"] == reason


def test_missing_admission_never_claims_or_creates_a_stop(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    lane = OperatorLane(tmp_path / "home", lambda _: 0)
    result = lane.rpc(STOP, {**target, "turn_request_id": "never-admitted"})
    assert result["error"]["data"]["reason"] == "execution_not_admitted"
    assert read_chat_turn_receipt("never-admitted") is None


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
    assert original.rpc(SEND, params)["result"]["accepted"]
    for state in ("pending", "executing", "outcome_unknown"):
        assert transition_mission_chat_turn(session_id=target["session_id"], client_message_id="uncertain",
            turn_id="uncertain", elements=[], state=state) is MissionChatTurnPersistOutcome.PERSISTED
    restarted = OperatorLane(tmp_path / "home", lambda _: 0)
    result = restarted.rpc(STOP, params)["result"]
    assert result["outcome"] == "stop_requested" and result["owner_observed"] is False
    assert read_chat_turn_receipt("uncertain").stop_requested
    assert restarted.rpc(SEND, params)["result"]["idempotent_replay"]
    assert restarted.jobs == []
    assert execution_status(target["session_id"], "uncertain")["outcome"] == "stop_requested"
