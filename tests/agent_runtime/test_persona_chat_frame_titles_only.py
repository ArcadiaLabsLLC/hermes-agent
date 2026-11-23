"""The agent-list frame's chats carry titles only (owner ruling 2026-11-23, "Yes, titles only").

RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT: every reply's
``persona_chat_turn`` overlay curated every stored row of the live chat (3.6–5.2 s on the
owner's Neko chat) to fill a 40-row tail the frame then threw away for its history rows and
kept only for the channel's ``conversation.messages``. The frame's chat rows are now the
session row; a chat's transcript is its own read when it is opened; the banners read the
chat's dispatch deliveries off their stored markers.
"""

from __future__ import annotations

import json

from agent_runtime.models import PersonaInstance
from agent_runtime.persona_chat_history import curation, persona_chat_frame_history
from agent_runtime.persona_chat_history.deliveries import chat_dispatch_deliveries
from agent_runtime.relay_policy import build_harness_delivery_marker
from agent_runtime.snapshot.receipts import _operator_channels_frame
from agent_runtime.states import WorkerSessionState
from hermes_state import SessionDB
from tests.agent_runtime.test_persona_chat_history_curation import FakeHistorySessionDB

INSTANCE = "personainst_dev_agent_1"


def _instance(session_id: str) -> PersonaInstance:
    return PersonaInstance(
        id=INSTANCE, persona_id="dev", role="dev", display_name=INSTANCE, profile_id=None,
        runtime_root="test-runtime", state=WorkerSessionState.IDLE, mode="chat",
        session_id=session_id, default_chat_session_id=session_id,
    )


def test_a_frame_chat_row_reads_no_transcript(isolate_agent_runtime_root, monkeypatch):
    """MUTATION (red recorded 2026-11-23): read the transcript whatever ``transcript`` says in
    ``history_rows._history_row`` -> the curation is called and the row carries messages."""

    sessions = [{
        "id": "chat_1", "source": "agent_runtime_persona_chat", "title": "Plan the release",
        "preview": "Ready when you are.", "message_count": 2,
        "started_at": "2026-11-23T10:00:00Z", "last_active": "2026-11-23T10:05:00Z",
        "model_config": json.dumps({"persona_instance_id": INSTANCE}),
    }]
    db = FakeHistorySessionDB(sessions, messages=[
        {"id": "m1", "session_id": "chat_1", "role": "user", "content": "Go"},
        {"id": "m2", "session_id": "chat_1", "role": "assistant", "content": "Done."},
    ])
    curated: list[str] = []
    real = curation._safe_curated_messages

    def counting(session_db, *, session_id, preview=True):
        curated.append(session_id)
        return real(session_db, session_id=session_id, preview=preview)

    monkeypatch.setattr("agent_runtime.persona_chat_history.history_rows._safe_curated_messages", counting)

    row = persona_chat_frame_history(persona_instances=[_instance("chat_1")], session_db=db)[0]

    assert curated == []
    assert row["messages"] == []
    assert "visible_message_count" not in row
    assert row["title"] == "Plan the release"
    assert row["last_message_preview"] == "Ready when you are."
    assert row["redaction_status"] == "safe"
    # Positive control: the on-demand summary still reads the transcript.
    from agent_runtime.persona_chat_history import persona_chat_history_summary

    full = persona_chat_history_summary(persona_instances=[_instance("chat_1")], session_db=db)[0]
    assert curated == ["chat_1"]
    assert [message["text"] for message in full["messages"]] == ["Go", "Done."]


def test_a_frame_channel_carries_no_transcript():
    """MUTATION (red recorded 2026-11-23): keep the conversation's messages in
    ``receipts._operator_channels_frame`` -> the channel still carries the transcript."""

    deliveries = [{"dispatch_id": "dispatch_1", "notify_operator": True, "state": "completed",
                   "target_session_id": "", "target_name": ""}]
    channel = {
        "channel_id": "chan_1", "message_count": 7,
        "history": {"session_id": "chat_1", "messages": [], "dispatch_deliveries": deliveries},
        "conversation": {"title": "Plan the release", "state": "open", "messages": [{"id": "m1"}]},
    }

    framed = _operator_channels_frame([channel])[0]

    assert framed["conversation"] == {
        "title": "Plan the release", "state": "open", "messages": [], "messages_evicted": True}
    assert framed["dispatch_deliveries"] == deliveries
    assert framed["message_count"] == 7
    # The channel the summary built is left as it was (the parity checks read it).
    assert channel["conversation"]["messages"] == [{"id": "m1"}]


def test_chat_dispatch_deliveries(tmp_path):
    """One indexed read of the markers across the chat's lineage, oldest first, one per dispatch.

    MUTATION (red recorded 2026-11-23): drop the ``seen`` check in ``chat_dispatch_deliveries``
    -> the resent delivery of ``dispatch_2`` is listed twice.
    """

    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("chat_1", "agent_runtime_persona_chat")
        db.append_message("chat_1", "user", "Go")
        for dispatch_id, notify, state in (
            ("dispatch_1", True, "completed"),
            ("dispatch_2", False, "error"),
            ("dispatch_2", False, "error"),
        ):
            db.append_message("chat_1", "user", f"[BACKGROUND DISPATCH COMPLETE — {dispatch_id}]",
                              finish_reason=build_harness_delivery_marker(
                                  dispatch_id, notify, state, "child_1", "Child"))
        db.append_message("chat_1", "assistant", "Both are back.")
        db.create_session("chat_other", "agent_runtime_persona_chat")
        db.append_message("chat_other", "user", "[elsewhere]",
                          finish_reason=build_harness_delivery_marker("dispatch_9", True, "completed"))

        assert chat_dispatch_deliveries(db, "chat_1") == [
            {"dispatch_id": "dispatch_1", "notify_operator": True, "state": "completed",
             "target_session_id": "child_1", "target_name": "Child"},
            {"dispatch_id": "dispatch_2", "notify_operator": False, "state": "error",
             "target_session_id": "child_1", "target_name": "Child"},
        ]
        assert chat_dispatch_deliveries(db, "chat_none") == []
        # No store to ask: no answer, never "no deliveries".
        assert chat_dispatch_deliveries(object(), "chat_1") is None
    finally:
        db.close()
