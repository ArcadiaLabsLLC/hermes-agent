"""``WorkspaceStore`` — create / save / set_active / add-remove agent / rename /
archive, and the delete cascade (office subtree, owned boards, realm membership
and the resurrection-guard ledger).
"""

from __future__ import annotations

import shutil
import uuid

from hermes_time import now

from .. import paths
from ..errors import AlreadyExists, NotFound, WorkspaceDeleteBlocked
from ..events import EventLog
from ..models import Realm, Workspace, WorkspaceLift
from ..serde import safe_id
from ..store_events import emit_store_event
from .base import (
    _dedupe_ids,
    _list_models,
    _read_model,
    _safe_display_name,
    _slugify,
    _write_model,
    apply_activation,
    read_model_json,
    read_pointer,
)
from .ledgers import DELETED_WORKSPACE_LEDGER_CAP, _prune_workspace_lifts
from .realms import RealmStore

__layer__ = "stores"


class WorkspaceStore:
    def __init__(self, event_log: EventLog | None = None):
        self.event_log = event_log or EventLog()

    def create(
        self,
        *,
        name: str,
        agent_ids: list[str] | None = None,
        default_blueprint_id: str | None = None,
        isolation: str = "soft",
        max_concurrent_lanes: int | None = None,
        realm_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Workspace:
        clean_name = _safe_display_name(name)
        if not clean_name:
            raise ValueError("workspace name is required")
        clean_isolation = str(isolation or "soft").strip().lower()
        if clean_isolation not in {"soft", "hard"}:
            raise ValueError("invalid_isolation")
        ts = now()
        slug = _slugify(clean_name)
        item = Workspace(
            id=safe_id(workspace_id) or f"ws_{slug}_{uuid.uuid4().hex[:6]}",
            slug=slug,
            name=clean_name,
            agent_ids=_dedupe_ids(agent_ids or []),
            default_blueprint_id=safe_id(default_blueprint_id),
            isolation=clean_isolation,
            max_concurrent_lanes=max_concurrent_lanes if max_concurrent_lanes is None else max(1, int(max_concurrent_lanes)),
            realm_id=safe_id(realm_id),
            created_at=ts,
            updated_at=ts,
        )
        path = paths.workspace_path(item.id)
        if path.exists():
            raise AlreadyExists(item.id)
        _write_model(path, item)
        emit_store_event(
            self.event_log,
            "workspace.created",
            {"workspace_id": item.id, "name": item.name, "realm_id": item.realm_id},
            domain="store",
        )
        return self.get(item.id)

    def get(self, workspace_id: str) -> Workspace:
        return _read_model(Workspace, paths.workspace_path(workspace_id))

    def list_all(self, *, include_archived: bool = False) -> list[Workspace]:
        items = _list_models(Workspace, paths.workspaces_dir())
        if not include_archived:
            items = [item for item in items if not item.archived]
        return sorted(items, key=lambda item: (item.name.lower(), item.id))

    def save(self, item: Workspace, *, emit_event: bool = True) -> Workspace:
        """``emit_event=False`` is for named mutators (rename/archive/…) that
        append their own, more specific event — never for skipping emission."""
        item.updated_at = now()
        _write_model(paths.workspace_path(item.id), item)
        if emit_event:
            emit_store_event(
                self.event_log,
                "workspace.updated",
                {"workspace_id": item.id, "change": "saved", "name": item.name},
                domain="store",
            )
        return self.get(item.id)

    def set_active(self, workspace_id: str | None, *, issued_at: str | None = None) -> dict:
        value = safe_id(workspace_id)
        name = self.get(value).name if value else None
        return apply_activation(
            paths.active_workspace_path(),
            "workspace_id",
            value,
            issued_at,
            name=name,
            event_type="workspace.activated",
            event_log=self.event_log,
        )

    def active_id(self) -> str | None:
        return read_pointer(paths.active_workspace_path(), "workspace_id")

    def active_intent_issued_at(self) -> str | None:
        """The supersede basis stored ALONGSIDE the active workspace pointer.

        ``set_active`` writes it on every applied write; this reads it back.
        The one caller is ``scope_activation``'s straddle heal: when a realm
        switch's reconcile is refused ``superseded``, the workspace pointer is
        owned by a strictly newer explicit gesture, and re-parking the realm
        pointer under the REALM intent's (older) basis would be refused in turn
        — leaving the two pointers in different realms with nothing to heal
        them. The winning gesture's own basis is the only one that carries, and
        this is where it is recorded.

        ``None`` when the pointer file is missing, unreadable, or predates the
        field. The caller then lets ``set_active`` stamp ``now()``, which is the
        fail-open direction ``_resolve_activation_write`` already takes when
        either side has no parseable basis.
        """

        try:
            raw = read_model_json(paths.active_workspace_path())
        except Exception:
            return None
        value = raw.get("intent_issued_at")
        return value if isinstance(value, str) and value.strip() else None

    def add_agent(self, workspace_id: str, persona_id: str) -> Workspace:
        item = self.get(workspace_id)
        persona = safe_id(persona_id)
        if persona and persona not in item.agent_ids:
            item.agent_ids.append(persona)
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "workspace.updated",
            {"workspace_id": item.id, "change": "agent_added", "persona_id": persona},
            domain="store",
        )
        return item

    def remove_agent(self, workspace_id: str, persona_id: str) -> Workspace:
        item = self.get(workspace_id)
        persona = safe_id(persona_id)
        item.agent_ids = [value for value in item.agent_ids if value != persona]
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "workspace.updated",
            {"workspace_id": item.id, "change": "agent_removed", "persona_id": persona},
            domain="store",
        )
        return item

    def rename(self, workspace_id: str, name: str) -> Workspace:
        item = self.get(workspace_id)
        item.name = _safe_display_name(name)
        item.slug = _slugify(item.name)
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "workspace.updated",
            {"workspace_id": item.id, "change": "renamed", "name": item.name},
            domain="store",
        )
        return item

    def archive(self, workspace_id: str) -> Workspace:
        item = self.get(workspace_id)
        item.archived = True
        item = self.save(item, emit_event=False)
        emit_store_event(
            self.event_log,
            "workspace.archived",
            {"workspace_id": item.id, "name": item.name},
            domain="store",
        )
        return item

    def delete(self, workspace_id: str, *, reason: str = "operator_delete") -> dict:
        """Hard-delete a workspace and cascade its scoped content stores.

        The single write chokepoint for workspace deletion (archive stays the
        reversible path). Guards, in order:

        - ``realm_default_workspace`` — a SERVER-bound realm's default pointer
          is backend-adoption authority; promote another default first. A
          local realm's default pointer is local truth and is cleared here.

        Cascade: the workspace JSON, its Mission Office subtree, and every
        board owned by the workspace. A realm-bound delete also rewrites realm
        membership and records the id in the realm's ``deleted_workspace_ids``
        resurrection-guard ledger, so realm sync propagates the removal
        instead of letting another member's surviving copy republish it.
        Emits ``workspace.deleted`` (Stage 12: the mutation must ride its own
        event or stay invisible to the watermark-gated consumers).
        """
        item = self.get(workspace_id)
        realm: Realm | None = None
        if item.realm_id:
            try:
                realm = RealmStore(event_log=self.event_log).get(item.realm_id)
            except NotFound:
                realm = None
        if realm is not None and realm.server_id and realm.default_workspace_id == item.id:
            raise WorkspaceDeleteBlocked(
                "realm_default_workspace",
                "This workspace is the realm's default; promote another default workspace first.",
                safe_details={"realm_id": realm.id},
            )

        # Cascade content stores under their own write locks so a concurrent
        # office/board write cannot interleave with the removal.
        from ..board_store import BoardStore
        from ..locks import board_lock, office_lock

        # THE CASCADE'S ENUMERATION IS ITS DELETE LIST, so it is refused whole
        # rather than run short. ``list_all`` drops a board whose ``board.json``
        # will not decode, and the loop below deletes by MATCHING
        # ``board.workspace_id`` — a board it cannot decode is a board it cannot
        # attribute, so it silently survives a workspace that no longer exists.
        # That is worse than either outcome the operator chose between: an orphan
        # directory owned by a deleted workspace, which no workspace-scoped verb
        # will list again and no later delete can re-reach, because the row that
        # named it is gone.
        #
        # Refused BEFORE the office subtree is removed — before the cascade takes
        # its first irreversible step — so the store is left exactly as found. A
        # half-done cascade is worse than a refused one: the refusal is repairable
        # by fixing one file; the half-done state is not repairable at all once
        # the workspace row is unlinked.
        board_scan = BoardStore(event_log=self.event_log).scan_all()
        if board_scan.unreadable:
            raise WorkspaceDeleteBlocked(
                "workspace_boards_unreadable",
                (
                    f"{board_scan.unreadable} board definition(s) will not decode, so the "
                    "cascade cannot tell which boards this workspace owns; repair or "
                    "remove them before deleting the workspace."
                ),
                safe_details={"unreadable": board_scan.unreadable, "workspace_id": item.id},
            )

        with office_lock(item.id):
            shutil.rmtree(paths.office_dir(item.id), ignore_errors=True)
        for board in board_scan.boards:
            if board.workspace_id != item.id:
                continue
            with board_lock(board.board_id):
                shutil.rmtree(paths.board_dir(board.board_id), ignore_errors=True)

        if realm is not None:
            realm.workspace_ids = [wid for wid in (realm.workspace_ids or []) if wid != item.id]
            ledger = [wid for wid in (realm.deleted_workspace_ids or []) if wid != item.id]
            ledger.append(item.id)
            realm.deleted_workspace_ids = ledger[-DELETED_WORKSPACE_LEDGER_CAP:]
            # SUPERSEDE any lift marker for this id rather than dropping it.
            # Dropping it would be an absence again, and a peer's surviving lift
            # would then out-rank this fresh delete on the next pull. Stamping
            # ``deleted_at`` makes "a fresh re-delete beats a stale lift" the
            # same comparison as "a fresh lift beats a stale delete".
            realm.workspace_lifts = _prune_workspace_lifts(
                [
                    (
                        WorkspaceLift(
                            workspace_id=lift.workspace_id,
                            restored_at=lift.restored_at,
                            deleted_at=now(),
                        )
                        if lift.workspace_id == item.id
                        else lift
                    )
                    for lift in (getattr(realm, "workspace_lifts", None) or [])
                ]
            )
            if realm.default_workspace_id == item.id:
                # Only reachable for local realms — the server-bound case is
                # guarded above.
                realm.default_workspace_id = None
            RealmStore(event_log=self.event_log).save(realm, emit_event=False)
            emit_store_event(
                self.event_log,
                "realm.updated",
                {"realm_id": realm.id, "change": "workspace_deleted"},
                domain="store",
            )

        paths.workspace_path(item.id).unlink(missing_ok=True)
        if self.active_id() == item.id:
            # Clear the dangling pointer; verb-layer callers may re-reconcile
            # to the realm's default afterwards.
            self.set_active(None)
        emit_store_event(
            self.event_log,
            "workspace.deleted",
            {
                "workspace_id": item.id,
                "name": item.name,
                "realm_id": item.realm_id,
                "reason": reason,
            },
            domain="store",
        )
        return {
            "id": item.id,
            "name": item.name,
            "realm_id": item.realm_id,
            "deleted": True,
        }
