"""RT-RELAY-THREAD-REFUSES-ITS-OWN-OPERATOR: a relay's teammate thread belongs to the dispatching chat's owner.

Seen live 2026-11-12 (Eternia MC-NATIVE-ACCEPT-REPAIRS step 4): Base relayed to QA Agent A by
``agent_chat_send``; the thread the relay minted for A had no ``client_scope`` while Base's chat
had the app's, so the app's Open thread was refused "belongs to another account"
(``require_session_owner`` → ``conversation_owner_changed``). A relay reaches the send lane with
the sender's chat root as ``requested_by_session`` and no scope of its own; the mint now takes the
dispatching chat's owner. Another account's scope is still refused.
"""

from __future__ import annotations

from argparse import Namespace

import pytest

from agent_runtime.conversation_owner import ConversationOwnerError, require_session_owner
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import ensure_persona_chat_session
from hermes_cli.harness_parts.persona import chat_turn_message
from hermes_state import SessionDB

OPERATOR = "a" * 64
OTHER_ACCOUNT = "c" * 64
SENDER_ROOT = "persona_chat_personainst_base_806e36791ba2"


def _relay_mint(db, *, args: Namespace, requested_by_session: str | None):
    minted, refused = chat_turn_message._mint_send_root(
        args, instance_store=PersonaInstanceStore(), session_db=db, normalized_persona="qa",
        persona_instance_id="personainst_qa", client_message_id="agent-relay-1", session_id=None,
        mint_title="QA chat", existing_root=None, requested_by_session=requested_by_session,
    )
    assert refused is None
    return db.get_session(minted.session_id)


@pytest.fixture
def db(isolate_agent_runtime_root, tmp_path):
    db = SessionDB(tmp_path / "state.db")
    assert ensure_persona_chat_session(
        session_db=db, session_id=SENDER_ROOT, persona_id="base", client_scope=OPERATOR, required=True,
    )
    return db


def test_a_relay_thread_opens_for_the_dispatching_chats_owner(db):
    # The relay's args carry no client_scope (tools/agent_chat/send.py relay_args, detached argv).
    row = _relay_mint(db, args=Namespace(), requested_by_session=SENDER_ROOT)
    assert require_session_owner(row, OPERATOR) == OPERATOR


def test_another_account_is_still_refused_the_relay_thread(db):
    row = _relay_mint(db, args=Namespace(), requested_by_session=SENDER_ROOT)
    with pytest.raises(ConversationOwnerError) as refused:
        require_session_owner(row, OTHER_ACCOUNT)
    assert refused.value.reason == "conversation_owner_changed"


def test_a_sender_on_another_chat_head_is_read_there(db, tmp_path, monkeypatch):
    # The target's head lacks the sender's row: the owner is read on the sender's own head.
    target_db = SessionDB(tmp_path / "target.db")
    monkeypatch.setattr(
        "agent_runtime.chat_session_scope.open_chat_session_db", lambda scope, *, access: db,
    )
    row = _relay_mint(target_db, args=Namespace(), requested_by_session=SENDER_ROOT)
    assert require_session_owner(row, OPERATOR) == OPERATOR


def test_an_unscoped_operator_send_mints_unscoped_as_before(db):
    row = _relay_mint(db, args=Namespace(), requested_by_session=None)
    assert require_session_owner(row, None) is None
    with pytest.raises(ConversationOwnerError):
        require_session_owner(row, OPERATOR)


def test_a_relayed_thread_names_who_sent_it(db, monkeypatch):
    """Eternia MC-RELAY-PROVENANCE: the target thread's history row says which chat (and agent) asked
    for it, from the mint's ``_dispatched_from`` record — the app's "From <agent>" header reads it.
    KILLING MUTATION: ``_dispatched_from`` answers {} -> no ``dispatched_from``, red (run)."""

    import json

    from agent_runtime.persona_chat_history import history_rows

    meta = json.loads(db.get_session(SENDER_ROOT)["model_config"] or "{}")
    meta["persona_instance_id"] = "personainst_base"
    db.update_session_meta(SENDER_ROOT, json.dumps(meta, sort_keys=True))
    monkeypatch.setattr(history_rows, "persona_instance_display_name",
                        lambda instance: {"personainst_base": "Base"}.get(instance, ""))

    relayed = _relay_mint(db, args=Namespace(), requested_by_session=SENDER_ROOT)
    row = history_rows._history_row(relayed, persona_id="qa", instance_id="personainst_qa",
                                    session_id=relayed["id"], session_db=db)
    assert row["dispatched_from"] == {"session_id": SENDER_ROOT, "persona_instance_id": "personainst_base",
                                      "display_name": "Base"}
    sender = history_rows._history_row(db.get_session(SENDER_ROOT), persona_id="base",
                                       instance_id="personainst_base", session_id=SENDER_ROOT, session_db=db)
    assert "dispatched_from" not in sender, "a thread nobody dispatched names no sender"
