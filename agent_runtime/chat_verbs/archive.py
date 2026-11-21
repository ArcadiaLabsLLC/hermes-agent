"""``runtime.persona.chat.archive`` / ``.unarchive`` — hide one saved agent chat from the Chat history, or bring it back.

Row ``RT-A-PERSONA-CHAT-CAN-BE-ARCHIVED-FROM-ETERNIA`` (owner 2026-11-21: "chat history ones should have ...
menu with the first option being archive chat"; review w1118a.74). The one primitive is the session store's
``set_session_archived(session_id, archived)``: the DELIBERATE archive, which flips the chat's whole
compression lineage and keeps every message. ``archive_sessions`` (a bulk filter) and
``unarchive_recoverable_session`` (which leaves a person's own archive alone on purpose) do not fit.

Refusals, each before anything is written:

- ``invalid_request``: no ``session_id``; ``invalid_client_scope``: a malformed account digest.
- ``status: not_found``: no saved chat by that id.
- ``foreign_chat_session``: the ``persona_instance_id`` / ``persona_id`` pin does not name the chat's owner
  (the delete's fence, ``chat_delete``); ``conversation_owner_changed``: another account's chat.
- ``chat_is_loaded`` (archive only): the chat is its instance's loaded chat (``default_chat_session_id``).
  The owner put Archive on Chat history rows only; an instance's open chat is not one of them.
- ``chat_busy`` (archive only): a turn holds the chat's root lease. The lease is held across the write, so a
  turn cannot start between the check and the archive.

The listing (``runtime.operator.conversation.list``) leaves a deliberately archived chat out unless asked
``include_archived``; the idle sweep's own archive (``auto_archived``) still lists, as it always did.
"""

from __future__ import annotations

from typing import Any

__layer__ = "lanes"
__all__ = ["CHAT_IS_LOADED", "apply_persona_chat_archived", "set_persona_chat_archived"]

#: The archive's refusal for an instance's loaded chat.
CHAT_IS_LOADED = "chat_is_loaded"


def set_persona_chat_archived(params: dict, *, archived: bool, caller: Any | None = None) -> dict:
    """Params: ``session_id`` (required); ``persona_instance_id``, ``persona_id``, ``client_scope``,
    ``requested_by``. Row: ``ok``, ``session_id``, ``persona_instance_id``, ``archived`` (the state
    now), ``changed`` (whether this call moved it)."""

    from ..conversation_owner import ConversationOwnerError, request_client_scope
    from ..mission_chat_outcome import ChatErrorKind
    from ..persona_assignments import safe_assignment_text, safe_assignment_token
    from .door import caller_requester

    session_id = safe_assignment_text(params.get("session_id"), limit=200)
    if not session_id:
        return {"ok": False, "error_kind": ChatErrorKind.INVALID_REQUEST, "error": "session_id is required"}
    try:
        asker_scope = request_client_scope(params)
    except ConversationOwnerError as exc:
        return {"ok": False, "error_kind": exc.reason, "error": "Invalid conversation owner."}
    return apply_persona_chat_archived(
        session_id, archived=archived, asker_scope=asker_scope,
        pinned_instance=safe_assignment_token(params.get("persona_instance_id")),
        pinned_persona=safe_assignment_text(params.get("persona_id"), limit=160),
        requester=safe_assignment_token(caller_requester(params, caller)),
    )


def apply_persona_chat_archived(session_id: str, *, archived: bool, asker_scope: str | None,
                                pinned_instance: str | None, pinned_persona: str | None,
                                requester: str | None) -> dict:
    """The archive itself, on validated values: the fences, then ``set_session_archived``."""

    from ..chat_heads import resolve_conversation_chat_scope
    from ..conversation_owner import ConversationOwnerError, require_session_owner
    from ..mission_chat_outcome import ChatErrorKind
    from ..persona_assignments import PersonaInstanceStore, normalize_persona_or_template_id, personas_equal
    from ..persona_chat_continuity import PersonaChatBusyError, persona_chat_root_lease
    from ..persona_chat_durability import (
        PersonaChatPersistenceError,
        default_persona_session_db,
        persona_session_db_for,
    )
    from ..persona_chat_session import _persona_chat_bound_owner, _persona_chat_session_owner

    try:
        session_db = persona_session_db_for(
            resolve_conversation_chat_scope(session_id=session_id), process=default_persona_session_db)
        row = session_db.get_session(session_id)
    except PersonaChatPersistenceError as exc:
        return {"ok": False, "session_id": session_id, "error_kind": ChatErrorKind.CHAT_SESSION_DB_UNAVAILABLE,
                "persistence_operation": exc.operation, "error": str(exc)}
    if row is None:
        return {"ok": False, "status": "not_found", "session_id": session_id,
                "error": f"persona chat session not found: {session_id}"}
    try:
        require_session_owner(row, asker_scope)
    except ConversationOwnerError as exc:
        return {"ok": False, "session_id": session_id, "error_kind": exc.reason,
                "error": "This conversation belongs to another account."}

    owner_id = _persona_chat_session_owner(session_db, session_id) or _persona_chat_bound_owner(session_id)
    try:
        owner = PersonaInstanceStore().get(owner_id) if owner_id else None
    except Exception:
        owner = None  # a retired holder: its saved chats stay archivable from the history
    pinned_persona = normalize_persona_or_template_id(pinned_persona) if pinned_persona else None
    if (not owner_id or (pinned_instance and pinned_instance != owner_id)
            or (pinned_persona and owner is not None and not personas_equal(owner.persona_id, pinned_persona))):
        return {"ok": False, "session_id": session_id, "error_kind": ChatErrorKind.FOREIGN_CHAT_SESSION,
                "error": "chat root is not owned by the requested persona instance",
                "persona_instance_id": pinned_instance or None}

    def write() -> dict:
        was = bool(row.get("archived"))
        session_db.set_session_archived(session_id, archived)
        return {"ok": True, "session_id": session_id, "persona_instance_id": owner_id, "archived": archived,
                "changed": was != archived}

    if not archived:
        return write()
    # MUTATION: drop this refusal and test_an_instances_loaded_chat_is_not_archived reddens.
    if owner is not None and owner.default_chat_session_id == session_id:
        return {"ok": False, "session_id": session_id, "error_kind": CHAT_IS_LOADED,
                "persona_instance_id": owner_id,
                "error": f"{owner.display_name}'s open chat is not archived; open another chat on it first."}
    try:
        # MUTATION: write without the lease and test_a_chat_a_turn_is_running_on_is_not_archived reddens.
        with persona_chat_root_lease(session_id, owner_id=requester, observer_kind="archive"):
            return write()
    except PersonaChatBusyError as exc:
        return {"ok": False, "session_id": session_id, "error_kind": ChatErrorKind.CHAT_BUSY,
                "lease_owner": exc.owner, "error": str(exc)}
