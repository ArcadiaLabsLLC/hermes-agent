"""Per-conversation and per-profile chat heads, over :mod:`agent_runtime.chat_session_scope`.

The scope module resolves WHERE one chat lives (the ladder, the process and
instance doors); this one answers the questions a ``per_profile`` record adds
(chat-head plan, ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``):
which scope a per-conversation writer acquires (:func:`resolve_conversation_chat_scope`),
which head a new record names (:func:`chat_head_for`, :func:`first_bind_chat_head`),
and the cross-agent read fan-out (:func:`per_profile_read_heads`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime import chat_session_scope as _scope
from agent_runtime.chat_session_scope import (
    SESSION_DB_ABSENT,
    ChatHeadSource,
    ChatSessionScope,
    InstanceChatHead,
    InstanceChatHeadStatus,
    SessionDbAccess,
)

__layer__ = "stores"

__all__ = [
    "HeadRead",
    "chat_head_for",
    "first_bind_chat_head",
    "per_profile_read_heads",
    "resolve_conversation_chat_scope",
]

logger = logging.getLogger(__name__)


def resolve_conversation_chat_scope(
    *,
    session_id: str | None = None,
    persona_instance_id: str | None = None,
    instance: Any = None,
    instance_store: Any = None,
    persona_id: str | None = None,
) -> ChatSessionScope:
    """The chat scope a per-conversation WRITER acquires (plan §7.2 decision 5). Never raises.

    The owning instance answers when it can be named — ``instance`` itself, else
    the owner the session id encodes (``persona_chat_<instance>_<hex>``), else
    the caller's pin — through :func:`resolve_instance_chat_scope`. A session
    whose owner cannot be derived (a legacy opaque id) asks the ladder, and keeps
    its answer only when a ``per_profile`` record gave it. A named owner with no
    row (an instance being created) has no record to ask: given its
    ``persona_id``, it answers the head its first bind will record
    (:func:`first_bind_chat_head`), so the root a create mints lands where the
    bind then stamps it; without one, the process scope. Everything else is the
    process scope, so a writer that moves here changes nothing for a process
    record.
    """

    owner = _derived_owner(session_id)
    named = owner or str(persona_instance_id or "").strip()
    if instance is None:
        instance = _load_instance(named, instance_store)
    if instance is not None:
        return _scope.resolve_instance_chat_scope(instance)
    if named and persona_id and (
        head := first_bind_chat_head(instance_id=named, persona_id=persona_id, session_id=session_id)
    ):
        return ChatSessionScope(
            head,
            ChatHeadSource.INSTANCE_RECORDED,
            instance_head=InstanceChatHead(
                InstanceChatHeadStatus.RECORDED, head_home=head, instance_id=named,
                head_kind=_per_profile_kind(),
            ),
        )
    if session_id and str(session_id).strip() and not owner:
        scope = _scope.resolve_chat_session_scope(session_id=str(session_id))
        if scope.per_profile:
            return scope
    return _scope.resolve_process_chat_scope()


def _derived_owner(session_id: str | None) -> str:
    if not session_id:
        return ""
    from .persona_assignments.identity import chat_session_owner_instance_id

    return chat_session_owner_instance_id(session_id) or ""


def _load_instance(instance_id: str, instance_store: Any) -> Any:
    if not instance_id:
        return None
    try:
        if instance_store is None:
            from .persona_assignments import PersonaInstanceStore

            instance_store = PersonaInstanceStore()
        return instance_store.get(instance_id)
    except Exception:
        return None


def chat_head_for(persona: Any) -> Path:
    """The chat head a NEW per-profile record names (plan §7.2 decision 2).

    The home the persona RUNS in — ``profile_context.resolve_persona_profile``,
    the one derivation the worker store and recall already use — so the chat,
    the run and recall agree. A persona that inherits the active profile (or
    names a profile that does not exist) gets the process head. Derivation
    only: the stamp that records it is the first-bind slice's.
    """

    from agent_runtime.profile_context import resolve_persona_profile

    home = resolve_persona_profile(persona).profile_home
    return Path(home) if home is not None else _scope.resolve_process_chat_scope().head_home


def first_bind_chat_head(
    *, instance_id: str, persona_id: str, session_id: str | None = None
) -> Path | None:
    """The ``per_profile`` head a never-bound instance's FIRST bind records, or ``None``.

    Plan §7.2 decision 8 (a): the persona's run home (:func:`chat_head_for`)
    when it is not the process head and the process head holds no session that
    names *instance_id* nor *session_id* (the conversation being bound) — the
    legacy rows that predate the stamp keep their instance on the process head,
    for the migrate verb to move. ``None`` — stay
    ``process`` — whenever that cannot be shown: a degraded process scope, a
    persona not on the roster, a home equal to the process head, a process store
    that exists but will not open. Both the create's root mint and the bind's
    stamp ask this one function, so the root lands where the record points.
    """

    process = _scope.resolve_process_chat_scope()
    persona = _roster_persona(persona_id)
    if not process.authoritative or persona is None:
        return None
    head = chat_head_for(persona)
    if _scope._same_path(head, process.head_home) or not head.is_dir():
        return None
    if not _scope.chat_session_store_exists(process):
        return head
    db = _scope.open_chat_session_db(process, access=SessionDbAccess.READ)
    if db is None:
        return None
    try:
        from agent_runtime.instance_sessions import instance_session_ids

        if session_id and db.get_session(session_id) is not None:
            return None
        return None if instance_session_ids(db, instance_id, limit=1) else head
    except Exception:
        logger.debug("first-bind legacy-row query failed", exc_info=True)
        return None
    finally:
        close = getattr(db, "close", None)
        if callable(close):
            close()


def _roster_persona(persona_id: str) -> Any:
    from agent_runtime.config.roster import ensure_persisted_personas
    from agent_runtime.serde import safe_assignment_token

    wanted = safe_assignment_token(persona_id)
    try:
        return next(
            (p for p in ensure_persisted_personas() if safe_assignment_token(getattr(p, "id", None)) == wanted),
            None,
        )
    except Exception:
        return None


def _per_profile_kind() -> str:
    from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE

    return CHAT_HEAD_KIND_PER_PROFILE


@dataclass(frozen=True, slots=True)
class HeadRead:
    """One ``per_profile`` head opened for a cross-agent read: its scope and READ handle.

    ``db`` is ``None`` when the head refused (its home is gone) or holds no
    store yet; :attr:`unavailable` names which, for the reader's accounting.
    """

    scope: ChatSessionScope
    db: Any | None

    @property
    def unavailable(self) -> str:
        return self.scope.refusal or SESSION_DB_ABSENT


@contextmanager
def per_profile_read_heads(
    instances: Iterable[Any], *, process_db: Any = None
) -> Iterator[dict[str, HeadRead]]:
    """Instance id -> its ``per_profile`` head, each distinct head opened ONCE, read-only.

    The fan-out a cross-agent read (the roster, the history list) runs beside
    its process handle (plan §2.4): instances whose head is the process one —
    every record that is not ``per_profile``, and a ``per_profile`` record whose
    home IS ``process_db``'s — are absent, so the caller's process handle serves
    them exactly as before. Handles close on exit. N is the number of agent
    profiles, so nothing is indexed.
    """

    from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE

    process_path = getattr(process_db, "db_path", None)
    process_key = _scope._normalized(Path(process_path)) if process_path else None
    by_path: dict[str, HeadRead] = {}
    reads: dict[str, HeadRead] = {}
    try:
        for instance in instances:
            if getattr(instance, "chat_head_kind", None) != CHAT_HEAD_KIND_PER_PROFILE:
                continue
            instance_id = str(getattr(instance, "id", "") or "")
            scope = _scope.resolve_instance_chat_scope(instance)
            key = _scope._normalized(scope.db_path)
            if not instance_id or not scope.per_profile or key == process_key:
                continue
            read = by_path.get(key)
            if read is None:
                read = by_path[key] = HeadRead(
                    scope, _scope.open_chat_session_db(scope, access=SessionDbAccess.READ)
                )
            reads[instance_id] = read
        yield reads
    finally:
        for read in by_path.values():
            close = getattr(read.db, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # a read must not fail on release
                    logger.debug("closing a per-profile chat head failed", exc_info=True)
