"""Resolve a saved agent chat for a metadata write without opening the chat."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

__layer__ = "lanes"


class SavedChatRefused(Exception):
    def __init__(self, session_id: str, reason: str, message: str, **facts: Any):
        super().__init__(message)
        self.row = {"ok": False, "session_id": session_id, "error_kind": reason, "error": message, **facts}


@dataclass(frozen=True)
class SavedChat:
    db: Any
    instance_id: str
    instance: Any


@contextmanager
def saved_chat(session_id: str, *, asker_scope: str | None, pinned_instance: str | None,
               pinned_persona: str | None) -> Iterator[SavedChat]:
    """Share the archive and title writers' exact account and holder checks."""
    from ..conversation_owner import ConversationOwnerError, require_session_owner
    from ..mission_chat_outcome import ChatErrorKind
    from ..persona_assignments import PersonaInstanceStore, normalize_persona_or_template_id, personas_equal
    from ..persona_chat_durability import PersonaChatPersistenceError, _acquired_persona_session_db
    from ..persona_chat_session import _persona_chat_bound_owner, _persona_chat_session_owner

    with ExitStack() as lease:
        try:
            db = lease.enter_context(_acquired_persona_session_db(session_id))
            row = db.get_session(session_id)
        except PersonaChatPersistenceError as exc:
            raise SavedChatRefused(session_id, ChatErrorKind.CHAT_SESSION_DB_UNAVAILABLE, str(exc),
                                   persistence_operation=exc.operation) from exc
        if row is None:
            raise SavedChatRefused(session_id, "not_found", "This chat is no longer saved.", status="not_found")
        try:
            require_session_owner(row, asker_scope)
        except ConversationOwnerError as exc:
            raise SavedChatRefused(session_id, exc.reason, "This conversation belongs to another account.") from exc

        instance_id = _persona_chat_session_owner(db, session_id) or _persona_chat_bound_owner(session_id)
        try:
            instance = PersonaInstanceStore().get(instance_id) if instance_id else None
        except Exception:
            instance = None  # A saved chat keeps its history if its holder is gone.
        persona = normalize_persona_or_template_id(pinned_persona) if pinned_persona else None
        if (not instance_id or (pinned_instance and pinned_instance != instance_id)
                or (persona and instance is not None and not personas_equal(instance.persona_id, persona))):
            raise SavedChatRefused(session_id, ChatErrorKind.FOREIGN_CHAT_SESSION,
                                   "chat root is not owned by the requested persona instance",
                                   persona_instance_id=pinned_instance or None)
        yield SavedChat(db, instance_id, instance)
