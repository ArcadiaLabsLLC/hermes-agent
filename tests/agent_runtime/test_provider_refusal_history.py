"""Known provider setup failures remain visible after Console remount."""
from agent_runtime.mission_chat_turns import persist_mission_chat_turn, transition_mission_chat_turn
from agent_runtime.persona_chat_history.markers import _terminal_turn_marker_rows
from agent_runtime.operator_channels.history_messages import _conversation_history_message


def test_unavailable_turn_projects_a_durable_setup_recovery_marker(isolate_agent_runtime_root):
    persist_mission_chat_turn(session_id="base", client_message_id="failed", turn_id="failed", elements=[], state="pending", write_ahead=True)
    transition_mission_chat_turn(session_id="base", client_message_id="failed", turn_id="failed", elements=[], state="executing")
    refusal = {"status_code": 0, "reason": "provider_unavailable"}
    transition_mission_chat_turn(session_id="base", client_message_id="failed", turn_id="failed", elements=[], state="provider_refused", metadata={"provider_refusal": refusal})
    rows = _terminal_turn_marker_rows(session_id="base", assistant_client_message_ids=set())
    assert len(rows) == 1
    marker = rows[0]
    assert marker["kind"] == "provider_refused"
    assert marker["provider_refusal"] == refusal
    assert "never left Hermes" in marker["text"]
    assert "provider setup" in marker["text"]
    message = _conversation_history_message(marker, channel_id="base", index=0, persona_id="profile_base", persona_instance_id=None)
    assert message["status"] == "provider_refused"
    assert message["provider_refusal"] == refusal
    assert message["client_message_id"] == "failed"
    assert _terminal_turn_marker_rows(session_id="base", assistant_client_message_ids={"failed"}) == []


def test_provider_http_refusal_does_not_claim_setup_was_unavailable():
    record = {"state": "provider_refused", "client_message_id": "refused", "provider_refusal": {"status_code": 429, "reason": "usage_limit_reached"}}
    rows = _terminal_turn_marker_rows(session_id="base", assistant_client_message_ids=set(), records=[record])
    assert len(rows) == 1
    assert "never left Hermes" not in rows[0]["text"]
    assert rows[0]["provider_refusal"]["status_code"] == 429


def test_uncertain_execution_does_not_project_a_setup_refusal():
    assert _terminal_turn_marker_rows(session_id="base", assistant_client_message_ids=set(), records=[{"state": "outcome_unknown", "client_message_id": "unknown"}]) == []
