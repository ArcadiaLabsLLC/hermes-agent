"""The harness uses upstream's one steer buffer without promoting machine notices."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from agent.interrupt_control import InterruptControlMixin
from agent.agent_runtime_helpers import apply_pending_steer_to_tool_results
from tools.process_registry_notifications import TimelineNotification
from agent_runtime.native_persistence import project_native_message


class Agent(InterruptControlMixin):
    def __init__(self):
        self._pending_steer = None
        self._pending_steer_lock = threading.Lock()
        self._turn_user_intervened = False


def test_machine_notice_keeps_its_provenance_through_the_real_steer_drain():
    agent = Agent()
    agent.steer(TimelineNotification("Build finished: 0", "Build finished", "process_completed"))
    messages = [{"role": "tool", "content": "still working", "tool_call_id": "tool"}]
    apply_pending_steer_to_tool_results(agent, messages, 1)
    assert messages[-1]["display_kind"] == "process_completed"
    assert "OUT-OF-BAND USER MESSAGE" not in messages[-1]["content"]
    assert not agent._turn_user_intervened


def test_a_notice_and_a_user_steer_are_not_coalesced_into_user_authority():
    agent = Agent()
    agent.steer(TimelineNotification("Build finished: 0", "Build finished", "process_completed"))
    agent.steer("Please check the tests too")
    messages = [{"role": "tool", "content": "done"}]
    apply_pending_steer_to_tool_results(agent, messages, 1)
    assert len(messages) == 3
    assert messages[1]["display_kind"] == "process_completed"
    assert messages[2]["display_kind"] == "steer"
    assert "Build finished" not in messages[2]["content"]
    assert agent._turn_user_intervened


def test_native_steer_keeps_identity_and_parent_turn_position():
    agent = SimpleNamespace(_persona_chat_root_session_id="chat",
                            _persona_chat_client_message_id="prompt", _persona_chat_turn_id="prompt")
    row = {"role": "user", "content": "Check tests", "display_kind": "steer",
           "platform_message_id": "steer-1",
           "display_metadata": {"turn_id": "prompt", "turn_seq": 3}}
    project_native_message(agent, row, row["content"], 8)
    assert row["platform_message_id"] == "steer-1"
    assert row["display_metadata"] == {"turn_id": "prompt", "turn_seq": 3}


def test_steer_stays_between_tools_and_reply_after_projection(isolate_agent_runtime_root):
    from agent.prompt_builder import steer_user_row
    from agent_runtime.persona_chat_history.curation import _safe_curated_messages
    from agent_runtime.operator_channels.history_messages import _conversation_history_message
    from agent_runtime.persona_chat_history.markers import _ordered_message_rows

    rows = [
        {"role": "user", "content": "Start", "platform_message_id": "prompt"},
        {**steer_user_row("Check tests"), "platform_message_id": "steer-1",
         "display_metadata": {"turn_id": "prompt", "turn_seq": 3}},
        {"role": "assistant", "content": "Done", "platform_message_id": "prompt:assistant:8"},
    ]
    db = SimpleNamespace(get_messages=lambda _: rows)
    history, _, error = _safe_curated_messages(db, session_id="chat")
    assert error is None
    projected = [_conversation_history_message(row, channel_id="channel", index=index,
                 persona_id="profile_dev", persona_instance_id="dev") for index, row in enumerate(history)]
    projected.extend([{"id": "before", "turn_id": "prompt", "turn_seq": 2},
                      {"id": "after", "turn_id": "prompt", "turn_seq": 4}])
    ordered = _ordered_message_rows(projected)
    assert [row.get("client_message_id", row["id"]) for row in ordered] == [
        "prompt", "before", "steer-1", "after", "prompt:assistant:8"]
    steer = ordered[2]
    assert steer["display_text"] == "Check tests"
    assert steer["steered"] is True


def test_requeue_keeps_arrival_order_and_notification_identity():
    from agent.agent_runtime_helpers import _requeue_pending_steer
    agent = Agent()
    agent.steer(TimelineNotification("done", "Done", "process_completed"))
    earlier = agent._drain_pending_steer()
    agent.steer("new user input")
    _requeue_pending_steer(agent, earlier)
    messages = [{"role": "tool", "content": "done"}]
    apply_pending_steer_to_tool_results(agent, messages, 1)
    assert [row.get("display_kind") for row in messages[1:]] == ["process_completed", "steer"]


def test_separate_pre_api_drains_preserve_arrival_order():
    from agent.turn_iteration_prep import _inject_steer_after_newest_tool_result
    agent = Agent()
    messages = [{"role": "tool", "content": "done"}]
    _inject_steer_after_newest_tool_result(agent, messages, "first")
    _inject_steer_after_newest_tool_result(agent, messages, "second")
    assert "first" in messages[1]["content"]
    assert "second" in messages[2]["content"]


def test_real_inbox_flush_and_reopen_keep_user_and_notice_separate(tmp_path, isolate_agent_runtime_root):
    from agent.session_persistence import SessionPersistenceMixin
    from agent_runtime.mission_chat_steer import start_active_mission_chat_turn, submit_mission_chat_steer
    from agent_runtime.persona_chat_history.curation import _safe_curated_messages
    from hermes_state import SessionDB
    from hermes_cli.harness_parts.persona.chat_events import _ChatProtocolV2Emitter

    class NativeAgent(Agent, SessionPersistenceMixin):
        pass

    with SessionDB(tmp_path / "state.db") as db:
        db.create_session("chat", "test")
        agent = NativeAgent()
        agent.session_id = "chat"
        agent._session_db = db
        agent._session_db_created = True
        agent._last_flushed_db_idx = 0
        agent._persona_chat_root_session_id = "chat"
        agent._persona_chat_client_message_id = "prompt"
        agent._persona_chat_turn_id = "prompt"
        emitter = _ChatProtocolV2Emitter(turn_id="prompt", client_message_id="prompt", emit_frames=False)
        handle = start_active_mission_chat_turn(runtime_root=tmp_path, session_id="chat", agent=agent,
                                               input_position=emitter.input_position)
        try:
            for client, text, notification in [("notice", "Build finished", True), ("steer", "Check tests", False)]:
                receipt = submit_mission_chat_steer(runtime_root=tmp_path, session_id="chat", message=text,
                                                    client_message_id=client, notification=notification)
                assert receipt["ok"]
                assert receipt["turn_id"] == "prompt"
        finally:
            handle.close()
        messages = [{"role": "user", "content": "Start"}, {"role": "tool", "content": "done"}]
        apply_pending_steer_to_tool_results(agent, messages, 1)
        messages.append({"role": "assistant", "content": "Finished"})
        assert agent._flush_messages_to_session_db(messages)
        history, _, error = _safe_curated_messages(db, session_id="chat")
        assert error is None
        by_id = {row.get("client_message_id"): row for row in history}
        assert by_id["notice"]["role"] == "system"
        assert by_id["steer"]["role"] == "operator"
        assert by_id["steer"]["text"] == "Check tests"
        assert by_id["steer"]["turn_id"] == "prompt"
        assert 0 < by_id["notice"]["turn_seq"] < by_id["steer"]["turn_seq"] < history[-1]["turn_seq"]
