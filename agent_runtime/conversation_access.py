"""Scoped console access through the native transcript reader."""
from __future__ import annotations

from .conversation_owner import ConversationOwnerError, request_client_scope
from .persona_chat_history.messages import existing_persona_chat_messages

__layer__ = "lanes"


def require_scoped_conversation(params: dict) -> None:
    owner = request_client_scope(params)
    if owner is None:
        return
    session = params.get("session_id")
    if not isinstance(session, str) or not session:
        raise ConversationOwnerError("conversation_identity_required")
    result = existing_persona_chat_messages(session_id=session,
        check_only=True, client_scope=owner)
    if not result.get("ok"):
        raise ConversationOwnerError(result.get("error_kind") or "conversation_unavailable")
