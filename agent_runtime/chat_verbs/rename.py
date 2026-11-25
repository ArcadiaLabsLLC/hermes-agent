"""Set the user's title on one saved agent chat through SessionDB."""
from __future__ import annotations

from .saved_chat import SavedChatRefused, saved_chat

__layer__ = "lanes"


def rename_persona_chat(params: dict) -> dict:
    from ..conversation_owner import ConversationOwnerError, request_client_scope
    from ..persona_assignments import safe_assignment_text, safe_assignment_token

    session_id = safe_assignment_text(params.get("session_id"), limit=200)
    instance_id = safe_assignment_token(params.get("persona_instance_id"))
    persona_id = safe_assignment_text(params.get("persona_id"), limit=160)
    title = params.get("title")
    if not session_id or not instance_id or not persona_id or not isinstance(title, str):
        return {"ok": False, "error_kind": "invalid_request", "error": "A saved chat and title are required."}
    try:
        scope = request_client_scope(params)
    except ConversationOwnerError as exc:
        return {"ok": False, "error_kind": exc.reason, "error": "Invalid conversation owner."}
    if scope is None:
        return {"ok": False, "error_kind": "invalid_client_scope", "error": "A conversation owner is required."}
    try:
        with saved_chat(session_id, asker_scope=scope, pinned_instance=instance_id, pinned_persona=persona_id) as chat:
            return _write_title(chat.db, session_id, title)
    except SavedChatRefused as exc:
        return exc.row


def _write_title(db, session_id: str, title: str) -> dict:
    try:
        cleaned = db.sanitize_title(title)
    except ValueError as exc:
        return {"ok": False, "error_kind": "invalid_request", "error": str(exc)}
    if cleaned is None:
        return {"ok": False, "error_kind": "invalid_request", "error": "Enter a chat title."}
    try:
        if db.set_session_title(session_id, cleaned):
            return {"ok": True, "session_id": session_id, "title": cleaned}
    except ValueError:
        # The store can include another conversation's id in a title conflict.
        return {"ok": False, "error_kind": "chat_title_unavailable", "error": "Choose a different chat title."}
    return {"ok": False, "error_kind": "chat_session_persist_failed", "error": "The chat title could not be saved."}
