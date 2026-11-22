"""RT-GROUP-CHAT-OF-AGENTS-WITH-THEIR-OWN-PROFILE-REFUSES-EVERY-TURN.

A room member's session is written into the store its chat turn reads: the
member's own profile home for a ``per_profile`` record (every agent
``runtime.agent.create`` places), the head home for a process record. Before,
``NativeContext.ensure_session`` always wrote the head home's ``state.db`` while
the turn's ``unknown_chat_session`` guard read the profile's, so every member
turn of such a room was refused.
"""

from __future__ import annotations

import pytest

from agent_runtime import paths
from agent_runtime.chat_heads import resolve_conversation_chat_scope
from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, CHAT_HEAD_KIND_PROCESS
from agent_runtime.persona_assignments import PersonaInstanceStore
from hermes_state import SessionDB

FIRST_ROOT = "persona_chat_personainst_qa_agent_1_0123456789ab"


@pytest.fixture
def homes(tmp_path, monkeypatch):
    head = tmp_path / ".hermes"
    alice = head / "profiles" / "alice"
    for path in (head / "agent-runtime", alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(head / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(head))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    return {"head": head, "alice": alice}


def _member(kind: str, home) -> dict:
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="qa", persona_instance_id="personainst_qa_agent_1", session_id=FIRST_ROOT)
    instance.chat_head_home = str(home)
    instance.chat_head_kind = kind
    store.update(instance)
    return {"instance_id": instance.id, "persona_id": "qa", "handle": "qa-1",
            "session_id": f"persona_chat_{instance.id}_fedcba987654"}


def _ensure(homes, member) -> None:
    context = NativeContext(paths.store_root(), homes["head"], "install")
    context.ensure_session({"run_id": "discussion-0011223344556677", "initial": {}}, member)


def _has(db_path, session_id) -> bool:
    if not db_path.exists():
        return False
    db = SessionDB(db_path=db_path)
    try:
        return db.get_session(session_id) is not None
    finally:
        db.close()


def _turn_guard_sees(member) -> bool:
    """The read the chat turn's ``unknown_chat_session`` guard makes."""
    scope = resolve_conversation_chat_scope(session_id=member["session_id"],
                                            persona_instance_id=member["instance_id"])
    db = open_chat_session_db(scope, access=SessionDbAccess.READ)
    try:
        return db is not None and db.get_session(member["session_id"]) is not None
    finally:
        if db is not None:
            db.close()


def test_a_per_profile_members_room_session_lands_in_its_own_profile_store(homes):
    member = _member(CHAT_HEAD_KIND_PER_PROFILE, homes["alice"])

    _ensure(homes, member)

    assert _has(homes["alice"] / "state.db", member["session_id"])
    assert not _has(homes["head"] / "state.db", member["session_id"])
    assert _turn_guard_sees(member)


def test_positive_control_a_process_members_room_session_stays_in_the_head_store(homes):
    member = _member(CHAT_HEAD_KIND_PROCESS, homes["alice"])

    _ensure(homes, member)

    assert _has(homes["head"] / "state.db", member["session_id"])
    assert not _has(homes["alice"] / "state.db", member["session_id"])
    assert _turn_guard_sees(member)


def test_a_per_profile_member_whose_home_is_gone_is_refused_not_written_to_the_head(homes):
    member = _member(CHAT_HEAD_KIND_PER_PROFILE, homes["head"] / "profiles" / "gone")

    with pytest.raises(DiscussionError, match="profile unavailable"):
        _ensure(homes, member)

    assert not _has(homes["head"] / "state.db", member["session_id"])
