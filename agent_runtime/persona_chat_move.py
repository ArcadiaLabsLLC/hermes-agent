"""Moving a saved chat to another instance of its agent — THE one rebind owner.

Owner 2026-11-19 ("Reuse idle, else new", row
``RT-A-SAVED-CHAT-CAN-MOVE-TO-ANOTHER-INSTANCE-OF-ITS-AGENT``): opening an old
chat whose instance is busy opens it on an idle instance of the same agent
(replacing that instance's loaded chat), or on a newly placed one; an instance
may open old chats from other instances of the same persona. The client picks
the instance (Eternia's ``resolveAgentInstanceUse``); this lane moves the chat.

A chat stays ONE conversation: its transcript row, id and history stay where
they are, and only who holds it changes, in three writes made here and nowhere
else —

1. the move ledger (``persona_assignments.chat_moves``), which the bind and the
   default-chat resolver read;
2. the transcript's own ``persona_instance_id``, which history, recall and the
   owner check read (``persona_chat_session._persona_chat_session_owner``
   accepts it only when the ledger records this move);
3. the bind itself, through ``PersonaInstanceStore.open_chat`` (the one write of
   an instance's chat pointers), after which the instance the chat came from has
   its pointer cleared when it named this chat.

Refused: a chat of a DIFFERENT agent (typed ``foreign_chat_session``, as before),
a chat with a turn running in it (the turn holds the chat's root lease, so the
move answers ``chat_busy`` and never cuts the reply off), a retired target (its
tombstone). A chat whose holder was retired still moves: the holder's agent is
read from its retirement archive (review w1118a.56 D13). A failure after the first write puts the ledger and the transcript
field back, so a half move never strands the chat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hermes_time import now

from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    RetiredPersonaInstanceError,
    personas_equal,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_assignments.chat_moves import record_chat_move, restore_chat_move
from agent_runtime.persona_assignments.vocabulary import CHAT_BINDING_CLEARED_REASON_MOVED
from agent_runtime.persona_chat_session import _persona_chat_session_owner, _session_model_config

__layer__ = "lanes"

__all__ = ["CHAT_MOVED_EVENT", "ChatMoveRefused", "ChatMoved", "move_chat"]

#: The domain event a move appends (``decision_contract_registry``). Deliberately
#: NOT patch-covered: the chat leaves one instance's history and joins another's,
#: which only a full core carries (the ``chat_binding_cleared`` reasoning).
CHAT_MOVED_EVENT = "persona_instance.chat_moved"

#: Transcript ``model_config`` key: the moves this chat has made, oldest first.
_MOVES_CONFIG_KEY = "persona_instance_moves"


class ChatMoveRefused(Exception):
    """A typed refusal: ``error_kind`` is a ``ChatErrorKind`` value."""

    def __init__(self, error_kind: str, error: str, *, next_expected: str) -> None:
        super().__init__(error)
        self.error_kind = error_kind
        self.error = error
        self.next_expected = next_expected


@dataclass(frozen=True)
class ChatMoved:
    """The bound target row, and the instance the chat came from (``None`` when it was already there)."""

    instance: PersonaInstance
    moved_from: str | None


def _write_owner(session_db: Any, session_id: str, config: dict[str, Any]) -> None:
    session_db.update_session_meta(
        session_id, json.dumps(config, sort_keys=True, separators=(",", ":"))
    )


def _holder_agent(store: PersonaInstanceStore, holder_id: str) -> str | None:
    """The agent of the instance holding the chat: its live row, else its retirement archive (D13).

    A retired instance's chats stay its agent's, so they can move onto another
    instance of that agent; the instance store stays the one authority for an
    instance's agent (never the transcript's own ``persona_id``)."""

    try:
        return store.get(holder_id).persona_id
    except Exception:
        retired = store.retired_instance_row(holder_id)
        return retired.persona_id if retired is not None else None


def move_chat(
    *,
    session_db: Any,
    session_id: str,
    to_instance_id: str,
    requested_by: str | None = None,
    correlation_id: str | None = None,
    store: PersonaInstanceStore | None = None,
) -> ChatMoved:
    """Bind the saved chat *session_id* onto *to_instance_id*, moving it off its holder.

    *session_db* is the transcript's own store (the caller resolved its chat
    scope). Raises :class:`ChatMoveRefused`, ``PersonaChatBusyError`` (a turn is
    running in the chat) or ``RetiredPersonaInstanceError`` (the target retired).
    """

    from agent_runtime.mission_chat_outcome import ChatErrorKind
    from agent_runtime.persona_chat_continuity import persona_chat_root_lease

    store = store or PersonaInstanceStore()
    session = safe_assignment_text(session_id, limit=200)
    target_id = safe_assignment_token(to_instance_id)
    holder_id = _persona_chat_session_owner(session_db, session)
    if not session or not target_id or not holder_id:
        raise ChatMoveRefused(
            ChatErrorKind.FOREIGN_CHAT_SESSION,
            f"chat {session!r} has no owning instance to move it from",
            next_expected="open a server-minted chat root",
        )
    try:
        target = store.get(target_id)
    except Exception:
        target = None
    if target is None:
        # The bind would mint a row; a move only ever lands on a live instance.
        archive = store.retired_instance_archive_path(target_id)
        if archive is not None:
            raise RetiredPersonaInstanceError(target_id, archive_path=archive)
        raise ChatMoveRefused(
            ChatErrorKind.PERSONA_INSTANCE_NOT_FOUND,
            f"no instance {target_id!r} to move the chat to",
            next_expected="place an instance of this agent, then open the chat on it",
        )
    holder_persona = _holder_agent(store, holder_id)
    if not personas_equal(holder_persona, target.persona_id):
        raise ChatMoveRefused(
            ChatErrorKind.FOREIGN_CHAT_SESSION,
            f"chat {session!r} belongs to another agent; it cannot move to {target_id!r}",
            next_expected="open this chat on an instance of the agent it belongs to",
        )
    if holder_id == target.id:
        bound = store.open_chat(
            persona_id=target.persona_id, persona_instance_id=target.id,
            session_id=session, correlation_id=correlation_id,
        )
        return ChatMoved(instance=bound, moved_from=None)

    with persona_chat_root_lease(session, owner_id=requested_by, observer_kind="move"):
        config = _session_model_config(session_db, session)
        before = dict(config)
        moves = list(config.get(_MOVES_CONFIG_KEY) or []) if isinstance(config.get(_MOVES_CONFIG_KEY), list) else []
        moves.append({"from": holder_id, "to": target.id, "at": now().isoformat()})
        config.update({"persona_instance_id": target.id, _MOVES_CONFIG_KEY: moves})
        previous_entry = record_chat_move(session, target.id)
        try:
            _write_owner(session_db, session, config)
            bound = store.open_chat(
                persona_id=target.persona_id, persona_instance_id=target.id,
                session_id=session, correlation_id=correlation_id,
            )
        except BaseException:
            try:
                _write_owner(session_db, session, before)
            finally:
                restore_chat_move(session, previous_entry)
            raise
    try:
        holder = store.get(holder_id)
    except Exception:
        holder = None
    if holder is not None:
        store.clear_chat_session_binding(
            holder, session_id=session, reason=CHAT_BINDING_CLEARED_REASON_MOVED
        )
    store._event(
        CHAT_MOVED_EVENT,
        bound,
        {
            "persona_id": bound.persona_id,
            "session_id": session,
            "from_persona_instance_id": holder_id,
            "to_persona_instance_id": bound.id,
            "requested_by": safe_assignment_token(requested_by) or None,
        },
    )
    return ChatMoved(instance=bound, moved_from=holder_id)
