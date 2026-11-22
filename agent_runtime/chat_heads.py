"""Per-conversation and per-profile chat heads, over :mod:`agent_runtime.chat_session_scope`.

The scope module resolves WHERE one chat lives (the ladder, the process and
instance doors); this one answers the questions a ``per_profile`` record adds
(chat-head plan, ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``):
which scope a per-conversation writer acquires (:func:`resolve_conversation_chat_scope`),
which head a new record names (:func:`chat_head_for`, :func:`first_bind_chat_head`),
and the cross-agent read fan-out (:func:`per_profile_read_heads`, and
:func:`holder_read_heads` over the live instances AND the retired holders, the one
answer to "which heads hold this account's chats" both chat-list readers ask).
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
    "RetiredHolders",
    "chat_head_for",
    "first_bind_chat_head",
    "holder_read_heads",
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
    row (an instance being created), or with a row never bound (no chat pointer, no
    head), has no record to ask: given its
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
    if instance is not None and not _never_bound(instance):
        return _scope.resolve_instance_chat_scope(instance)
    if instance is not None:
        # A row that exists but was never bound (the canonical row every snapshot mints, a placed
        # agent before its first chat) is the no-row case: its first turn's bind stamps the head
        # ``first_bind_chat_head`` answers, so the turn writes there too
        # (RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN: the first chat
        # went to ``profiles/base`` while the bind recorded the agent's own profile).
        named = str(getattr(instance, "id", "") or named)
        persona_id = str(getattr(instance, "persona_id", "") or persona_id or "")
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
    if instance is not None:
        return _scope.resolve_instance_chat_scope(instance)
    if session_id and str(session_id).strip() and not owner:
        scope = _scope.resolve_chat_session_scope(session_id=str(session_id))
        if scope.per_profile:
            return scope
    return _scope.resolve_process_chat_scope()


def _never_bound(instance: Any) -> bool:
    """Whether ``instance`` has no chat pointer and no recorded head: the one bind that may stamp
    ``per_profile`` is its next (``persona_assignments.chat_binding.open_chat``'s ``first_bind``)."""

    return not getattr(instance, "default_chat_session_id", None) and not getattr(instance, "chat_head_home", None)


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


class RetiredHolders:
    """The retired holders one chat-list read meets: the archive listing read at most once, each
    tombstone decoded at most once, and every decoded row handed to whoever asks next.

    The one memo behind :func:`holder_read_heads` (which heads to open) and the readers' own
    projection (``instance_history._project_instance_history``,
    ``persona_chat_history.summary.HistorySummary._retired_holder``), so a page that opens a
    retired holder's head and then flags its row reads that tombstone once
    (RT-FU-A-RETIRED-HOLDERS-CHAT-IN-ITS-OWN-PROFILE-STAYS-IN-THE-CHAT-LISTS). The live half of the
    retirement predicate is the caller's: it asks only for an id its live roster missed.
    """

    def __init__(self) -> None:
        self._ids: frozenset[str] | None = None
        self._rows: dict[str, Any] = {}

    def ids(self) -> frozenset[str]:
        """Every instance id the retirement archive names (``retired_persona_instance_ids``)."""

        if self._ids is None:
            from agent_runtime.persona_assignments import retire

            self._ids = retire.retired_persona_instance_ids()
        return self._ids

    def row(self, instance_id: str | None) -> Any:
        """The archived row of the retired ``instance_id``, or ``None`` (never retired, or unreadable)."""

        if not instance_id or instance_id not in self.ids():
            return None
        if instance_id not in self._rows:
            from agent_runtime.persona_assignments import PersonaInstanceStore, retire

            try:
                self._rows[instance_id] = retire.retired_instance_row(PersonaInstanceStore(), instance_id)
            except Exception:
                self._rows[instance_id] = None
        return self._rows[instance_id]

    def rows(self, *, live_ids: Iterable[str] = ()) -> list[Any]:
        """Every retired holder's archived row, ids the live roster still holds left out (a live row wins)."""

        live = set(live_ids)
        return [row for instance_id in sorted(self.ids() - live)
                if (row := self.row(instance_id)) is not None]


@contextmanager
def holder_read_heads(
    instances: Iterable[Any], *, retired: RetiredHolders, process_db: Any = None
) -> Iterator[dict[str, HeadRead]]:
    """Instance id -> its ``per_profile`` head for every LIVE instance AND every RETIRED holder.

    :func:`per_profile_read_heads` over the live roster plus the rows the retirement archive
    names (``retired``, read once, each tombstone decoded once), so a chat saved in a retired
    holder's own profile is still read after no live instance of its agent shares that head
    (RT-FU-A-RETIRED-HOLDERS-CHAT-IN-ITS-OWN-PROFILE-STAYS-IN-THE-CHAT-LISTS). Each distinct
    head is still opened once, read-only; a head whose home is gone answers
    :attr:`HeadRead.unavailable` as a live one does.
    """

    live = list(instances)
    live_ids = {str(getattr(instance, "id", "") or "") for instance in live}
    # MUTATION: drop ``retired.rows(...)`` here and both readers' retired-profile tests redden.
    with per_profile_read_heads([*live, *retired.rows(live_ids=live_ids)], process_db=process_db) as reads:
        yield reads
