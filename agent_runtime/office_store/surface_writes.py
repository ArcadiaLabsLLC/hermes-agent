"""Surface writes: ensure (create-if-missing, refusing an unresolvable
workspace), the lock-held creation half, and the surface update.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_time import now

from agent_runtime import office_models
from agent_runtime.errors import WorkspaceUnresolved
from agent_runtime.locks import office_lock
from agent_runtime.models import OfficeSurface
from agent_runtime.office_store.files import _write_surface
from agent_runtime.office_store.normalize import _normalize_folders, _safe_actor_ref
from agent_runtime.serde import safe_id
from agent_runtime.store_conflicts import check_revision

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "_ensure_surface_locked",
    "_refuse_unresolvable_workspace",
    "ensure_surface",
    "update_surface",
]


def ensure_surface(store: OfficeStore, workspace_id: str, *, created_by: str = "operator") -> OfficeSurface:
    """Lazily create the deterministic default surface for a workspace.

    Idempotent: if the surface already exists it is returned unchanged (no
    event). Two machines calling this converge on identical semantic
    content (fixed folders + timestamp-excluded content hash).

    REFUSES typed (:class:`~.errors.WorkspaceUnresolved`) when no workspace
    record resolves the id. Until MC-8 this authored a surface for ANY id
    that passed ``safe_id``, which is how a leaked test context minted a
    LIVE office — 135 events and a ``revision 67`` actor file — for a
    workspace that never existed. The parity warning could describe that
    afterwards; this is the door.

    THE ORDER IS THE CONTRACT, and each step is placed against a specific
    failure:

    1. ``safe_id`` FIRST — an unusable id is a caller error, not a question
       about store state, and asking the store about it would be asking a
       question with no meaning.
    2. the ``surface_exists`` short-circuit SECOND, i.e. **the refusal guards
       CREATION and never reading**. An office whose workspace record has
       since disappeared must still be returned: the projection, the parity
       warning and the archive verb all read through here, so refusing an
       existing orphan would break every path the operator has for cleaning
       one up — including ``archive_orphaned_surface``, whose entire
       precondition is ``workspace_resolves() is False``. Putting the refusal
       above this line would make the live orphan unarchivable by the verb
       that exists to archive it.
    3. the refusal THIRD — before ``office_lock`` and before any write. The
       same discipline ``store.WorkspaceStore.delete``'s cascade follows:
       refused before the first irreversible step, so a refused call leaves
       the store exactly as it found it. Nothing is created, no lock is
       taken, no event is emitted — which is what makes "it refused" and "it
       refused before doing anything" one statement here instead of two.
    """

    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    if store.surface_exists(wsid):
        return store.get_surface(wsid)
    store._refuse_unresolvable_workspace(wsid)
    with office_lock(wsid):
        store._ensure_surface_locked(wsid, created_by=created_by)
    return store.get_surface(wsid)


def _refuse_unresolvable_workspace(store: OfficeStore, wsid: str) -> None:
    """THE door, spelled once, so every caller refuses in the same words.

    ``workspace_resolves`` is the SHARED predicate — the one
    ``archive_orphaned_surface`` refuses on, derived from the same
    membership the ``orphaned_office`` parity warning uses — so the door and
    the diagnostic cannot answer differently about one id. Archived
    workspaces resolve, deliberately: an archived workspace is a real record
    and its office is not an orphan.

    Extracted because :meth:`upsert_actor` has to spend this refusal at a
    different MOMENT than the creation it used to be welded to (see
    :meth:`_ensure_surface_locked`), and two spellings of one door are two
    doors free to disagree.
    """

    if store.workspace_resolves(wsid):
        return
    raise WorkspaceUnresolved(
        f"no workspace record resolves '{wsid}', so an office surface "
        "will not be authored for it; create the workspace first, or if "
        "the id is expected to arrive by realm sync, pull the realm "
        "before placing into it",
        safe_details={"workspace_id": wsid},
    )


def _ensure_surface_locked(store: OfficeStore, wsid: str, *, created_by: str) -> OfficeSurface:
    """The CREATION half of :meth:`ensure_surface`, for a caller that ALREADY
    holds ``office_lock(wsid)``.

    ``office_lock`` is NOT reentrant (``locks._file_lock``): a second
    acquisition from this same process contends with the first and refuses
    at the deadline rather than deadlocking. So a write verb that must
    author the surface INSIDE its own lock — after its fences have passed,
    not before — cannot call :meth:`ensure_surface`; it calls this. Same
    split, same reason, as ``upsert_actor``'s ``position_policy`` hook: work
    that must see or extend the locked state runs inside the lock that
    already holds it, never by taking it again.

    The unresolved-workspace refusal runs here TOO, not only at the pre-lock
    site: a helper that authors a surface without asking whether the
    workspace resolves would be a second door past ``ensure_surface``'s, and
    MC-8's whole finding was that an unresolved id could author a LIVE
    office.
    """

    if store.surface_exists(wsid):
        return store.get_surface(wsid)
    store._refuse_unresolvable_workspace(wsid)
    surface = office_models.default_surface(wsid, created_at=now(), updated_by=_safe_actor_ref(created_by))
    _write_surface(surface)
    store._emit("office.surface.created", workspace_id=surface.workspace_id)
    return surface


def update_surface(
    store: OfficeStore,
    workspace_id: str,
    *,
    folders: list[str] | None = None,
    updated_by: str = "operator",
    expect_revision: int | None = None,
    correlation_id: str | None = None,
    dry_run: bool = False,
) -> OfficeSurface:
    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    # Read BEFORE the ensure below, because the ensure is what makes the
    # answer stop being true. It decides whether this write gets an
    # ``office_surface`` patch at all: a folder write that AUTHORED the
    # office is a create as far as any reader is concerned, and the patch is
    # a three-field SUBSET — a client that has never held this workspace
    # would answer it ``patch_without_target`` and re-hydrate, paying the
    # patch AND the core. That is not hypothetical: ``workspace_template``
    # clones an office by calling ``ensure_surface`` and then this, and a
    # template clone is exactly the case where no client holds the row.
    # Creates stay full-core, which is the same ruling
    # ``office.surface.created`` already rides.
    surface_existed = store.surface_exists(wsid)
    if not dry_run:
        store.ensure_surface(wsid, created_by=updated_by)
    with office_lock(wsid):
        # A dry-run against an unauthored office validates + previews against
        # the WOULD-BE default surface without persisting it (no ensure_surface
        # write above), so the preview is honest and the store stays untouched.
        if store.surface_exists(wsid):
            surface = store.get_surface(wsid)
        else:
            surface = office_models.default_surface(
                wsid, created_at=now(), updated_by=_safe_actor_ref(updated_by)
            )
        check_revision(surface.revision, expect_revision)
        change = []
        if folders is not None:
            surface.folders = _normalize_folders(folders)
            change.append("folders")
        surface.revision += 1
        surface.updated_at = now()
        surface.updated_by = _safe_actor_ref(updated_by)
        if dry_run:
            # Full validation + revision check ran; return the would-be
            # surface in memory. Write nothing, emit no event.
            return surface
        _write_surface(surface)
        if surface_existed:
            store._emit_surface_patch(surface, correlation_id=correlation_id)
        store._emit(
            "office.surface.updated",
            correlation_id,
            workspace_id=surface.workspace_id,
            change=",".join(change) or "saved",
            revision=surface.revision,
        )
    return store.get_surface(wsid)
