"""OfficeStore — the single write chokepoint for the Mission Office domain.

Mirrors ``BoardStore`` 1:1 (the plan's lean directive —
``docs/mission_control/OFFICE_LAYOUT_REALM_SYNC_PLAN_2026-07-17.md``, launcher
repo): file-per-actor JSON under the runtime root, the shared store-lock
discipline, atomic writes, and a typed ``EventLog`` event on EVERY mutation
(standing store rule — an event-less write is invisible to the watermark-gated
snapshot/serve pipeline).

Hard invariants this store upholds:

- **Actor keys are canonicalized at THIS boundary** (plan §4.3):
  ``canonical_persona_instance_id`` for instance-bound actors, else the
  normalized persona id. The launcher sends the identity triple and never
  computes a sync filename; ``office_models.actor_file_token`` is the only
  filename derivation.
- **Archive-never-delete.** Removed actors move to ``archive/`` and their keys
  are recorded in the surface's ``archived_actor_keys`` resurrection-guard
  ledger. The LEDGER half — and only that half — is skipped by a diagnostic
  local eviction (``remove_actor(record_tombstone=False)``), because the ledger
  is the part a realm pull replicates: a repair aimed at this install's
  projection must not mint intent for every machine in the realm. The archive
  copy is always written, so ``actor-restore`` works in both modes.
- **Display names are validated at WRITE time** against the realm-sync
  secret-assignment scanner, so one member's name can never hard-fail another
  member's realm publish (plan §4.2). The publish-time scan stays as
  defense-in-depth.
- **Upserts are naturally idempotent** (keyed by ``actor_key``; identical
  content re-writes converge on the same file), so no idempotency ledger is
  needed — the board's ledger exists because ``add_card`` mints a new id per
  call; office writes don't.
"""

from __future__ import annotations

from typing import Any


from agent_runtime import paths
from agent_runtime.errors import NotFound
from agent_runtime.events import EventLog
from agent_runtime.models import OfficeActor, OfficeSurface
from agent_runtime.office_store import (
    actor_writes as actor_writes_lane,
    adoption as adoption_lane,
    archive as archive_lane,
    conflicts as conflicts_lane,
    guards as guards_lane,
    patches as patches_lane,
    surface_writes as surface_writes_lane,
)
from agent_runtime.office_store.files import read_actor_dir
from agent_runtime.office_store.models import ActorScan
from agent_runtime.serde import from_jsonable, read_json
from agent_runtime.store_events import emit_store_event

__layer__ = "stores"

__all__ = [
    "OfficeStore",
]


class OfficeStore:
    def __init__(self, event_log: EventLog | None = None) -> None:
        self.event_log = event_log or EventLog()

    # --- event emission (single chokepoint) ------------------------------

    def _emit(self, event_type: str, correlation_id: str | None = None, **payload: Any) -> None:
        """Append one office DOMAIN event (through ``store_events``; never raises).

        ``correlation_id`` (EG-2.3 / Plan D §V2) is the gesture token, threaded
        from the write boundary. It is a plain payload key, so the delta lane
        lifts it to ``entity.correlation_id`` for free and the office
        notification forwards it verbatim — no wire change on either lane.
        Positional-or-keyword rather than keyword-only because ``**payload``
        would otherwise swallow it; ``None`` is filtered out by
        :func:`emit_store_event` exactly as every other absent field is, which is
        what keeps a gestureless event byte-identical to before this key existed.
        """

        # Function-local like every other ``state_patches`` reach in this
        # package, so the patch module's import weight stays off the store's
        # own import path.
        from ..state_patches import CORRELATION_ID_KEY, normalize_correlation_id

        token = normalize_correlation_id(correlation_id)
        if token is not None:
            payload[CORRELATION_ID_KEY] = token
        emit_store_event(self.event_log, event_type, payload, domain="office")

    # --- surface reads ----------------------------------------------------

    def get_surface(self, workspace_id: str) -> OfficeSurface:
        path = paths.office_surface_path(workspace_id)
        if not path.exists():
            raise NotFound(f"office:{workspace_id}")
        return from_jsonable(OfficeSurface, read_json(path))

    def surface_exists(self, workspace_id: str) -> bool:
        return paths.office_surface_path(workspace_id).exists()

    def list_workspaces(self) -> list[str]:
        root = paths.office_root()
        if not root.exists():
            return []
        return sorted(child.name for child in root.iterdir() if (child / "office.json").exists())

    # --- surface writes ---------------------------------------------------

    # --- actor reads ------------------------------------------------------

    def get_actor(self, workspace_id: str, actor_key: str) -> OfficeActor:
        path = paths.office_actor_path(workspace_id, actor_key)
        if not path.exists():
            raise NotFound(f"office_actor:{actor_key}")
        return from_jsonable(OfficeActor, read_json(path))

    def actor_exists(self, workspace_id: str, actor_key: str) -> bool:
        return paths.office_actor_path(workspace_id, actor_key).exists()

    def scan_actors(self, workspace_id: str, *, include_archived: bool = False) -> ActorScan:
        """Every actor this workspace HAS, plus how many files did not decode.

        THE chokepoint, and since AX5 the ONLY one. There was a thin
        ``list_actors`` view over it that returned ``.actors`` and dropped
        ``.unreadable``, so a caller who only wanted rows kept a short
        signature — and the arms that most needed the count were the ones that
        never had to ask for it. The discipline then lived in PROSE: five
        separate comments across ``realm_sync``, ``office_sync``,
        ``office_class_key_guard``, ``snapshot`` and this file, each explaining
        to the next reader why THIS site spends ``scan_actors`` and not the
        cheap one. A rule that has to be re-argued at every call site is a rule
        the API is not carrying.

        So the thin view is gone and every caller spells ``.actors``. Dropping
        the unreadable count is still allowed and still usually right — it is
        now a thing someone WROTE rather than a default they inherited, which
        is the whole of the change.

        Forking readers is the failure this shape forbids: a count that reached
        ``runtime.office.get`` and not the ``subscribe`` baseline would put the
        two back in the silent-disagreement state ``_office_projection`` was
        extracted to end.
        """

        scan = read_actor_dir(paths.office_actors_dir(workspace_id))
        actors = scan.actors
        unreadable = scan.unreadable_files
        if include_archived:
            archived = read_actor_dir(paths.office_archive_dir(workspace_id))
            actors = [*actors, *archived.actors]
            unreadable = unreadable.merge(archived.unreadable_files)
        return ActorScan(sorted(actors, key=lambda a: a.actor_key), unreadable)

    # ── lanes (composition): each binding makes a lane function a method, so
    # ``store.<name>(...)`` — and a test patching the class attribute — resolves
    # exactly as it did when the body lived here.

    # patches
    _emit_actor_patch = patches_lane._emit_actor_patch
    _emit_surface_patch = patches_lane._emit_surface_patch
    _emit_actor_remove_patch = patches_lane._emit_actor_remove_patch
    _emit_conflict_resolved_patch = patches_lane._emit_conflict_resolved_patch
    _emit_surface_refresh_patch = patches_lane._emit_surface_refresh_patch

    # surface_writes
    ensure_surface = surface_writes_lane.ensure_surface
    _refuse_unresolvable_workspace = surface_writes_lane._refuse_unresolvable_workspace
    _ensure_surface_locked = surface_writes_lane._ensure_surface_locked
    update_surface = surface_writes_lane.update_surface

    # conflicts
    scan_conflicts = conflicts_lane.scan_conflicts
    resolve_conflict = conflicts_lane.resolve_conflict
    _guard_no_conflict = conflicts_lane._guard_no_conflict

    # actor_writes
    upsert_actor = actor_writes_lane.upsert_actor
    remove_actor = actor_writes_lane.remove_actor
    restore_actor = actor_writes_lane.restore_actor

    # adoption
    adopt_remote_surface = adoption_lane.adopt_remote_surface
    adopt_remote_actor = adoption_lane.adopt_remote_actor

    # archive
    workspace_resolves = archive_lane.workspace_resolves
    archive_orphaned_surface = archive_lane.archive_orphaned_surface
    _guard_surface_is_orphaned = archive_lane._guard_surface_is_orphaned
    _instance_bound_actor = archive_lane._instance_bound_actor
    archive_actors_for_instance = archive_lane.archive_actors_for_instance
    archived_actor_keys_for_instance = archive_lane.archived_actor_keys_for_instance
    _archive_actor_locked = archive_lane._archive_actor_locked

    # guards
    _guard_archived_actor = guards_lane._guard_archived_actor
    _guard_class_keyed_write = guards_lane._guard_class_keyed_write
    _guard_class_keyed_adoption = guards_lane._guard_class_keyed_adoption


    # --- actor writes -----------------------------------------------------


    # --- realm-sync adoption (the pull's write arms) -----------------------


    # --- orphaned-surface exit (EG-0.1 / HC §3) ----------------------------


    # --- prune lane (plan §4.3) --------------------------------------------


    # --- internal helpers ---------------------------------------------------


