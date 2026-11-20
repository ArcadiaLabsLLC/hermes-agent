"""A seat's office placement and chats name the agent its instance record names.

Seen 2026-11-20 on the owner's install (launcher rows
``MC-OFFICE-SEATS-STILL-NAME-THE-SHIPPED-NEKO-AFTER-THE-SORT`` and
``MC-SHIPPED-NEKO-CHAT-HISTORY-LISTS-THE-BETA-COPYS-CHATS``): re-pointing a seat at
another agent (``agent_duplicate._repoint``, which ``persona sort-shipped``'s
``copy`` runs) patched only the instance record. The seat's office actor kept the
old agent's ``persona_id`` and name, and its chats kept the old agent's
``model_config.persona_id`` stamp — the stamp the history list filters an agent's
chats by (``instance_history._history_page``) — so the Beta seats' desks named the
shipped Neko and their chats listed under her.

The instance record is the authority. :func:`follow_seat` brings the seat's office
actors (the actor's and its items' ``persona_id``, the agent item's name) and its
chats' stamps to it; :func:`stray_seats` is the read-only scan for seats already
out of step (an install sorted before this landed), which ``persona sort-shipped``
plans and applies. A chat with no stamp already follows the roster and is left
alone; nothing is deleted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from typing import Any

__layer__ = "stores"

__all__ = ["SeatDrift", "follow_seat", "seat_drift", "stray_seats"]


@dataclass(frozen=True)
class SeatDrift:
    """What of one seat still names another agent than its record does."""

    instance_id: str
    persona_id: str
    #: ``"<workspace>/<actor key>"`` of each office actor that names another agent.
    office_actors: tuple[str, ...] = ()
    #: Ids of the seat's chats stamped with another agent.
    chats: tuple[str, ...] = ()
    #: ``{"actor": "<workspace>/<actor key>", "error": <reason>}`` per office actor whose write
    #: was refused (a realm-sync conflict hold, an unresolved workspace); the rest still move.
    office_failed: tuple[dict[str, str], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.office_actors or self.chats or self.office_failed)

    def receipt(self) -> dict[str, Any]:
        receipt = {"instance_id": self.instance_id, "persona_id": self.persona_id,
                   "office_actors": list(self.office_actors), "chats": len(self.chats)}
        if self.office_failed:
            receipt["office_failed"] = list(self.office_failed)
        return receipt


def _stale_actor(actor: Any, instance: Any) -> bool:
    if actor.persona_instance_id != instance.id:
        return False
    return actor.persona_id != instance.persona_id or any(
        item.persona_id != instance.persona_id for item in actor.items)


def _stale_actors(office: Any, instance: Any) -> list[Any]:
    return [actor for workspace_id in office.list_workspaces()
            for actor in office.scan_actors(workspace_id).actors if _stale_actor(actor, instance)]


def _chat_scopes(instance: Any) -> list[Any]:
    """The instance's own chat head and the process head, each once (the history list reads both)."""

    from .chat_session_scope import resolve_instance_chat_scope, resolve_process_chat_scope

    scopes: dict[str, Any] = {}
    for scope in (resolve_instance_chat_scope(instance), resolve_process_chat_scope()):
        scopes.setdefault(str(scope.db_path), scope)
    return list(scopes.values())


@contextmanager
def _session_db(scope: Any, *, write: bool) -> Iterator[Any]:
    from .chat_session_scope import SessionDbAccess, open_chat_session_db

    db = open_chat_session_db(scope, access=SessionDbAccess.WRITE if write else SessionDbAccess.READ)
    if db is None:
        yield None
        return
    with closing(db):
        yield db


def _stale_chat_ids(db: Any, instance: Any) -> list[str]:
    from .instance_sessions import instance_session_clause

    clause, args = instance_session_clause(instance.id)
    rows = db._read_all(
        "SELECT id FROM sessions WHERE (model_config IS NULL OR json_valid(model_config)) AND " + clause
        + " AND COALESCE(json_extract(model_config,'$.persona_id'),'') NOT IN ('',?) ORDER BY id",
        [*args, instance.persona_id])
    return [row["id"] for row in rows]


def _stale_chats(instance: Any) -> list[tuple[Any, list[str]]]:
    found = []
    for scope in _chat_scopes(instance):
        with _session_db(scope, write=False) as db:
            ids = _stale_chat_ids(db, instance) if db is not None else []
        if ids:
            found.append((scope, ids))
    return found


def seat_drift(instance: Any, *, office: Any = None) -> SeatDrift:
    """Read only: what of ``instance`` names another agent than its record."""

    from .office_store.store import OfficeStore

    actors = _stale_actors(office or OfficeStore(), instance)
    chats = [chat for _, ids in _stale_chats(instance) for chat in ids]
    return SeatDrift(instance.id, instance.persona_id,
                     tuple(f"{actor.workspace_id}/{actor.actor_key}" for actor in actors), tuple(sorted(chats)))


def stray_seats() -> list[SeatDrift]:
    """Read only: every seat whose office actor or chats name another agent than its record."""

    from .office_store.store import OfficeStore
    from .persona_assignments import PersonaInstanceStore

    office = OfficeStore()
    drifts = (seat_drift(instance, office=office) for instance in PersonaInstanceStore().scan_all().instances)
    return sorted((drift for drift in drifts if drift), key=lambda drift: drift.instance_id)


def _follow_actor(office: Any, actor: Any, instance: Any) -> None:
    items = [{
        "item_id": item.item_id, "kind": item.kind, "persona_id": instance.persona_id,
        "position": list(item.position), "folder": item.folder, "scale": item.scale,
        "pet_slug": item.pet_slug,
        "display_name": instance.display_name if item.kind == "agent" else item.display_name,
    } for item in actor.items]
    office.upsert_actor(actor.workspace_id, {
        "persona_id": instance.persona_id, "persona_instance_id": instance.id,
        "backing_profile": actor.backing_profile, "items": items,
    }, updated_by="harness", expect_revision=actor.revision)


def _restamp(db: Any, ids: list[str], persona_id: str) -> None:
    marks = ",".join("?" * len(ids))
    db._execute_write(lambda conn: conn.execute(
        f"UPDATE sessions SET model_config=json_set(model_config,'$.persona_id',?) WHERE id IN ({marks})",
        [persona_id, *ids]))


def follow_seat(instance_id: str) -> SeatDrift:
    """Bring the seat's office actors and chat stamps to the agent its record names.

    Returns what it moved (falsy when the seat was already in step); an office actor
    whose write is refused is named under ``office_failed`` and the rest still move.
    """

    from .office_store.store import OfficeStore
    from .persona_assignments import PersonaInstanceStore

    instance = PersonaInstanceStore().get(instance_id)
    office = OfficeStore()
    followed: list[str] = []
    failed: list[dict[str, str]] = []
    for actor in _stale_actors(office, instance):
        key = f"{actor.workspace_id}/{actor.actor_key}"
        try:
            _follow_actor(office, actor, instance)
        except Exception as exc:  # one refused desk must not strand the seat's chats; it is named
            failed.append({"actor": key, "error": type(exc).__name__})
        else:
            followed.append(key)
    moved: list[str] = []
    for scope, ids in _stale_chats(instance):
        with _session_db(scope, write=True) as db:
            if db is not None:
                _restamp(db, ids, instance.persona_id)
                moved.extend(ids)
    return SeatDrift(instance.id, instance.persona_id, tuple(followed), tuple(sorted(moved)), tuple(failed))
