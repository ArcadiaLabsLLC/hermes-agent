"""A harness notice steered into a turn reaches the operator transcript as a typed, titled notice.

RT-RUNTIME-NOTICE-ROW-SHIPS-RAW-NOTE: a ``display_kind: runtime_notice`` row (the wall-budget
checkpoint, the MCP availability update) used to ship as a plain system message whose body was the
model-facing note, envelope and all, while its operator title went unused.
RT-ITERATION-LIMIT-NUDGE-STORED-AS-USER: the tool-iteration limit's summary request was a plain
role-user row the transcript served as the operator's own message.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.steering import RUNTIME_NOTE_ENVELOPE, PendingSteer
from agent_runtime.operator_channels.history_messages import _conversation_history_message
from agent_runtime.persona_chat_history.curation import _safe_curated_messages
from tools.process_registry_notifications import TimelineNotification

NOTE = "[harness] Wall budget nearly exhausted: 12s left. Wrap up."


def _project(rows):
    db = SimpleNamespace(get_messages=lambda _: rows)
    history, _, error = _safe_curated_messages(db, session_id="chat")
    assert error is None
    return [_conversation_history_message(row, channel_id="channel", index=index,
                                          persona_id="profile_dev", persona_instance_id="dev")
            for index, row in enumerate(history)]


def _notice_row(kind="runtime_notice", title="Time budget checkpoint"):
    row = PendingSteer.from_text(TimelineNotification(NOTE, title, kind, "diagnostic")).rows()[0]
    assert row["content"] == RUNTIME_NOTE_ENVELOPE + NOTE  # the model still reads the envelope
    return row


def test_a_runtime_notice_is_typed_and_titled_with_its_note_as_the_body():
    messages = _project([{"role": "user", "content": "Start", "platform_message_id": "prompt"}, _notice_row()])
    notice = messages[-1]
    assert notice["role"] == "system"
    assert notice["kind"] == "runtime_notice"
    assert notice["actor_persona_id"] == "harness" and notice["actor_instance_id"] is None
    assert notice["display_title"] == "Time budget checkpoint"
    assert notice["display_text"] == NOTE
    assert notice["notification_category"] == "diagnostic"


def test_another_timeline_notification_keeps_its_kind_and_gains_its_title():
    messages = _project([_notice_row(kind="process_completed", title="Build finished")])
    notice = messages[-1]
    assert notice["kind"] == "system_message"
    assert notice["display_title"] == "Build finished"
    assert notice["display_text"] == NOTE


def test_an_operator_message_carries_no_notice_fields():
    messages = _project([{"role": "user", "content": RUNTIME_NOTE_ENVELOPE + "typed by me",
                          "platform_message_id": "prompt"}])
    assert messages[0]["role"] == "operator"
    assert messages[0]["display_title"] == ""
    assert "notification_category" not in messages[0]


def test_the_iteration_limit_nudge_is_a_runtime_notice_not_an_operator_message(monkeypatch):
    from agent import chat_completion_helpers as helpers
    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    captured = []

    def stop(agent, api_messages):
        captured.extend(m for m in api_messages if m.get("content") == MAX_ITERATIONS_SUMMARY_REQUEST)
        raise RuntimeError("stop after the nudge")

    monkeypatch.setattr(helpers, "_iteration_summary_api_messages", stop)
    agent = SimpleNamespace(max_iterations=3, suppress_status_output=True, api_mode="chat_completions")
    messages = [{"role": "user", "content": "do the work", "platform_message_id": "prompt"}]
    try:
        helpers.handle_max_iterations(agent, messages, 3)
    except Exception:
        pass
    nudge = next(m for m in messages if m.get("content") == MAX_ITERATIONS_SUMMARY_REQUEST)
    assert nudge["role"] == "user"
    assert nudge["display_kind"] == "runtime_notice"
    assert nudge["display_metadata"] == {"display_text": "Tool-iteration limit reached",
                                         "notification_category": "diagnostic", "steering": True}
    projected = _project([messages[0], nudge])
    assert [m["kind"] for m in projected] == ["operator_message", "runtime_notice"]
    assert projected[1]["display_title"] == "Tool-iteration limit reached"
    assert projected[1]["display_text"] == MAX_ITERATIONS_SUMMARY_REQUEST
