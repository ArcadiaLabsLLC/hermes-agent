"""Scoped console access through the native transcript reader."""
from __future__ import annotations

from .conversation_owner import ConversationOwnerError, request_client_scope
from .persona_chat_history.messages import existing_persona_chat_messages

__layer__ = "lanes"


def validate_conversation_access(params: dict) -> None:
    owner = request_client_scope(params)
    if owner is None:
        return
    session = params.get("session_id")
    if not isinstance(session, str) or not session:
        # A first send names no chat yet: one that MINTS (``new_session``) has no existing
        # conversation to guard, and the root it mints carries this scope
        # (RT-CHAT-MESSAGE-SCOPE-WITHOUT-SESSION). Without ``new_session`` a session-less send may
        # continue the agent's current chat, which may be another account's, so it stays refused.
        if params.get("new_session") is True:
            return
        raise ConversationOwnerError("conversation_identity_required")
    result = existing_persona_chat_messages(session_id=session,
        check_only=True, client_scope=owner)
    if not result.get("ok"):
        raise ConversationOwnerError(result.get("error_kind") or "conversation_unavailable")
