"""The snapshot frame carries 10 recent chats, every live one pinned (owner ruling 2026-11-22).

"for starters i don't think it should load all the chats, it should just get the recent 10 chat
names". The chat lists page ``runtime.operator.conversation.list``; an older chat's transcript is
read when it is opened. Pinned above recency, and never cut: every live instance's bound chat (its
operator channel renders it), a chat with a turn in flight, and a chat with a waiting question.
The ``persona_chat_turn`` overlay ranks with the very same bound (``persona_chat_frame_history``).
"""

from __future__ import annotations

import json

from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_chat_history import persona_chat_frame_history
from agent_runtime.persona_chat_history.vocabulary import FRAME_RECENT_CHATS
from agent_runtime.states import WorkerSessionState
from tests.agent_runtime.test_persona_chat_history_curation import FakeHistorySessionDB
from tests.agent_runtime.test_stream_turn_section import home  # noqa: F401 - the fixture

INSTANCE = "personainst_dev_agent_1"


def _instance(instance_id: str, session_id: str) -> PersonaInstance:
    return PersonaInstance(
        id=instance_id, persona_id="dev", role="dev", display_name=instance_id, profile_id=None,
        runtime_root="test-runtime", state=WorkerSessionState.IDLE, mode="chat",
        session_id=session_id, default_chat_session_id=session_id,
    )


def _chats(count: int, instance_id: str = INSTANCE) -> list[dict]:
    """``chat_000`` is the oldest; activity follows creation."""

    return [
        {
            "id": f"chat_{index:03d}",
            "source": "agent_runtime_persona_chat",
            "title": f"Chat {index:03d}",
            "started_at": f"2026-11-{1 + index // 24:02d}T{index % 24:02d}:00:00Z",
            "last_active": f"2026-11-{1 + index // 24:02d}T{index % 24:02d}:30:00Z",
            "model_config": json.dumps({"persona_instance_id": instance_id}),
        }
        for index in range(count)
    ]


def _kept(instances, sessions) -> list[str]:
    rows = persona_chat_frame_history(persona_instances=instances, session_db=FakeHistorySessionDB(sessions))
    return sorted(row["session_id"] for row in rows)


def test_the_frame_carries_the_ten_most_recent_chats(isolate_agent_runtime_root):
    sessions = _chats(30)
    kept = _kept([_instance(INSTANCE, "chat_029")], sessions)

    assert FRAME_RECENT_CHATS == 10
    # The bound chat is the newest here; as a pin it rides beside ten, so eleven chats in all.
    assert kept == sorted(f"chat_{index:03d}" for index in range(19, 30))


def test_every_instances_bound_chat_stays_in_the_frame(isolate_agent_runtime_root):
    """Twelve instances bound to the twelve OLDEST chats: all twelve, and ten recent beside them.

    MUTATION (red recorded 2026-11-22): drop the ``keep_every_pin`` widening in
    ``HistorySummary.rows`` -> ten chats in all, every one of them a bound one.
    """

    sessions = _chats(40)
    instances = [_instance(f"personainst_dev_agent_{index}", f"chat_{index:03d}") for index in range(12)]
    for row in sessions:
        row["model_config"] = json.dumps({"persona_instance_id": "personainst_dev_agent_0"})

    kept = _kept(instances, sessions)

    assert kept == sorted([f"chat_{index:03d}" for index in range(12)] + [f"chat_{index:03d}" for index in range(30, 40)])


def test_an_old_chat_with_a_turn_in_flight_stays_in_the_frame(isolate_agent_runtime_root):
    """MUTATION (red recorded 2026-11-22): drop ``roots.update(inflight_chat_session_roots())`` in
    ``live_chat_roots`` -> ``chat_002`` is cut."""

    sessions = _chats(30)
    persist_mission_chat_turn(
        session_id="chat_002", client_message_id="client_old", turn_id="turn_old", elements=None,
        state="running", metadata={"root_chat_session_id": "chat_002"},
    )

    kept = _kept([_instance(INSTANCE, "chat_029")], sessions)

    assert "chat_002" in kept
    assert len(kept) == FRAME_RECENT_CHATS + 2  # the bound chat and the live one, beside ten


def test_an_old_chat_with_a_waiting_question_stays_in_the_frame(isolate_agent_runtime_root):
    """MUTATION (red recorded 2026-11-22): make the open-ticket arm in ``live_chat_roots`` never
    true -> ``chat_003`` is cut."""

    from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore

    sessions = _chats(30)
    assert PersonaChatClarifyTicketStore().mint(chat_session_id="chat_003", question="Which branch?")

    kept = _kept([_instance(INSTANCE, "chat_029")], sessions)

    assert "chat_003" in kept
    assert len(kept) == FRAME_RECENT_CHATS + 2


def test_the_core_and_the_overlay_keep_the_same_chats(isolate_agent_runtime_root, home):  # noqa: F811
    """Every root the core carries reads ``omitted: False`` in the overlay, every other one ``True``.

    MUTATION (red recorded 2026-11-22): call ``persona_chat_history_summary`` (its bound of 50) in
    ``turn_section_read.read_turn_sections`` -> the overlay carries the chats the core cut.
    """

    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_chat_durability import default_persona_session_db, ensure_persona_chat_session
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.turn_section_read import read_turn_sections

    db = default_persona_session_db()
    roots = [f"persona_chat_{INSTANCE}_{index:012d}" for index in range(FRAME_RECENT_CHATS + 4)]
    for root in roots:
        assert ensure_persona_chat_session(session_db=db, session_id=root, persona_id="dev", title=root,
                                           required=True)
        db.append_message(root, "user", f"hello {root}")
    PersonaInstanceStore().open_chat(persona_id="dev", persona_instance_id=INSTANCE, session_id=roots[-1])

    in_core = {row["session_id"] for row in build_snapshot()["persona_chat_history"]}

    assert len(in_core) == FRAME_RECENT_CHATS + 1  # the bound chat is a pin beside ten
    for root in roots:
        sections, _timings = read_turn_sections(root, named=(INSTANCE,))
        assert sections["omitted"] is (root not in in_core), root
