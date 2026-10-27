"""Move each agent's chats out of the process head into its own profile (plan §2.3, §7.2 decision 8 (b)).

``hermes harness persona chat-head migrate [--instance <id>] [--apply] --json``.
For each live persona instance whose persona runs in its own profile, every
session in the process head that names it (``instance_sessions``), plus its
compression lineage (children by ``parent_session_id``), is copied into that
profile's ``state.db`` with upstream's move primitives
(``hermes_state_profile_repair``: export → import → delete). The instance's
record flips to ``per_profile`` only after its WHOLE set copied and verified
(the target holds every session with at least the source's messages); only
then are the process-head rows deleted. Until it flips, its chats read from the
process head exactly as before.

Dry-run unless ``apply``. Idempotent: a flipped instance with nothing left in
the process head reports ``present``; one flipped but with rows left behind (a
crash between flip and delete) has them deleted on the next ``apply``
(``settled``). A busy chat — a root whose lease is held, or a turn, receipt or
clarify ticket still open — refuses that instance and moves none of it.
"""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack, closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_runtime import chat_session_scope as scopes
from agent_runtime.instance_sessions import instance_session_ids
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE

__layer__ = "lanes"

__all__ = ["InstanceMove", "MigrateRefused", "migrate_chat_heads"]

logger = logging.getLogger(__name__)


class MigrateRefused(RuntimeError):
    """The whole run cannot start (no authoritative process head, unknown instance)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class InstanceMove:
    """One instance's answer. ``status``: planned | moved | present | settled | skipped | refused."""

    instance_id: str
    status: str
    target_home: str | None = None
    session_ids: list[str] = field(default_factory=list)
    messages: int = 0
    reason: str | None = None

    def payload(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value not in (None, [])}


def migrate_chat_heads(*, instance_id: str | None = None, apply: bool = False) -> dict[str, Any]:
    """Plan (or with ``apply``, perform) the move for one instance or every live one."""

    from agent_runtime.persona_assignments import PersonaInstanceStore

    process = scopes.resolve_process_chat_scope()
    if not process.authoritative:
        raise MigrateRefused("process_head_unresolved")
    store = PersonaInstanceStore()
    if instance_id:
        try:
            instances = [store.get(instance_id)]
        except Exception as exc:
            raise MigrateRefused("unknown_instance") from exc
    else:
        instances = store.list_all()
    source = scopes.open_chat_session_db(
        process, access=scopes.SessionDbAccess.WRITE if apply else scopes.SessionDbAccess.READ
    )
    with closing(source) if source is not None else ExitStack():
        moves = [_one(store, instance, source, process, apply=apply) for instance in instances]
    return {
        "ok": not any(move.status == "refused" for move in moves),
        "applied": apply,
        "source_head": str(process.head_home),
        "instances": [move.payload() for move in moves],
    }


def _one(store: Any, instance: Any, source: Any, process: Any, *, apply: bool) -> InstanceMove:
    instance_id = str(instance.id)
    per_profile = getattr(instance, "chat_head_kind", None) == CHAT_HEAD_KIND_PER_PROFILE
    if per_profile:
        target = Path(str(instance.chat_head_home))
    else:
        persona = scopes._roster_persona(instance.persona_id)
        target = scopes.chat_head_for(persona) if persona is not None else process.head_home
    move = InstanceMove(instance_id, "planned", target_home=str(target))
    if scopes._same_path(target, process.head_home):
        return _skip(move, "runs_in_process_head")
    if not target.is_dir():
        return _skip(move, "profile_home_missing")
    move.session_ids, roots = _lineage(source, instance) if source is not None else ([], [])
    if per_profile and not move.session_ids:
        move.status = "present"
        return move
    if not move.session_ids:
        return _skip(move, "no_sessions")
    if not apply:
        move.messages = sum(source.count_messages_all(sid) for sid in move.session_ids)
        return move
    try:
        with _quiesced(instance_id, roots):
            return _apply(store, instance_id, source, target, move, per_profile=per_profile)
    except _Busy as exc:
        move.status, move.reason = "refused", exc.reason
        return move


def _skip(move: InstanceMove, reason: str) -> InstanceMove:
    move.status, move.reason = "skipped", reason
    return move


def _lineage(db: Any, instance: Any) -> tuple[list[str], list[str]]:
    """The instance's sessions plus every descendant, parents first; and the roots among them."""

    seeds = set(instance_session_ids(db, str(instance.id)))
    bound = str(getattr(instance, "default_chat_session_id", "") or "")
    if bound:
        seeds.add(bound)  # an opaque legacy root the predicate cannot name; absent rows drop below
    rows = db._read_all(
        "WITH RECURSIVE tree(id) AS (SELECT value FROM json_each(?) UNION "
        "SELECT s.id FROM sessions s JOIN tree t ON s.parent_session_id = t.id) "
        "SELECT s.id, s.parent_session_id FROM sessions s JOIN tree t ON s.id = t.id "
        "ORDER BY s.started_at, s.id",
        [json.dumps(sorted(seeds))],
    )
    parents = {str(row["id"]): row["parent_session_id"] for row in rows}
    roots = [sid for sid, parent in parents.items() if parent not in parents]
    ordered: list[str] = []
    while parents:
        ready = [sid for sid, parent in parents.items() if parent not in parents]
        for sid in ready:
            ordered.append(sid)
            del parents[sid]
    return ordered, roots


class _Busy(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _quiesced:
    """Hold the instance's bind lock and every root's turn lease; refuse a busy chat."""

    def __init__(self, instance_id: str, roots: list[str]) -> None:
        self._instance_id, self._roots, self._stack = instance_id, roots, ExitStack()

    def __enter__(self) -> None:
        from agent_runtime.locks import persona_chat_instance_lock
        from agent_runtime.operator_conversation import OperatorConversationRefused
        from agent_runtime.operator_session_models import _require_idle
        from agent_runtime.persona_chat_continuity.lease import PersonaChatBusyError, persona_chat_root_lease

        try:
            self._stack.enter_context(persona_chat_instance_lock(self._instance_id))
            for root in self._roots:
                self._stack.enter_context(persona_chat_root_lease(root, observer_kind="chat_head_migrate"))
                _require_idle(root)
        except (PersonaChatBusyError, OperatorConversationRefused) as exc:
            self._stack.close()
            raise _Busy("chat_busy") from exc

    def __exit__(self, *exc: Any) -> None:
        self._stack.close()


def _apply(store: Any, instance_id: str, source: Any, target: Path, move: InstanceMove, *,
           per_profile: bool) -> InstanceMove:
    from hermes_state_profile_repair import SessionLedgeredError

    scope = scopes.ChatSessionScope(target, scopes.ChatHeadSource.INSTANCE_RECORDED)
    sink = scopes.open_chat_session_db(scope, access=scopes.SessionDbAccess.WRITE)
    if sink is None:
        move.status, move.reason = "refused", "target_store_unavailable"
        return move
    with closing(sink):
        try:
            payloads = [source.export_session_for_move(sid) for sid in move.session_ids]
        except SessionLedgeredError:
            move.status, move.reason = "refused", "session_ledgered"
            return move
        profile = target.name
        for payload in filter(None, payloads):
            sink.import_moved_session(payload, profile_name=profile)
            sid = payload["session"]["id"]
            if sink.get_session(sid) is None or sink.count_messages_all(sid) < len(payload["messages"]):
                move.status, move.reason = "refused", "copy_unverified"
                return move
            move.messages += len(payload["messages"])
    if not per_profile:
        _flip(store, instance_id, target)
    for sid in reversed(move.session_ids):
        source.delete_moved_session(sid)
    move.status = "settled" if per_profile else "moved"
    logger.info("chat-head migrate: %s %s %d sessions -> %s", instance_id, move.status, len(move.session_ids), target)
    return move


def _flip(store: Any, instance_id: str, target: Path) -> None:
    """THE flip (plan §7.2 decision 8 (b)): re-read the row, record its own head."""

    instance = store.get(instance_id)
    instance.chat_head_home = str(target)
    instance.chat_head_kind = CHAT_HEAD_KIND_PER_PROFILE
    store.update(instance)
