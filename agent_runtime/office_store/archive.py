"""Archival: orphaned surfaces, the actors of a retired instance, the replay
read of which keys a retire archived, and the one lock-held actor archive.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_time import now

from agent_runtime import paths
from agent_runtime.errors import ActorsUnreadable, NotFound
from agent_runtime.locks import office_lock
from agent_runtime.models import OfficeActor, OfficeSurface
from agent_runtime.office_store.files import (
    _free_surface_archive_dir,
    _write_archived_actor,
    _write_surface,
)
from agent_runtime.office_store.models import ARCHIVED_LEDGER_CAP, OfficeActorOutcome
from agent_runtime.office_store.normalize import _safe_actor_ref
from agent_runtime.serde import safe_id

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "_archive_actor_locked",
    "_guard_surface_is_orphaned",
    "_instance_bound_actor",
    "archive_actors_for_instance",
    "archive_orphaned_surface",
    "archived_actor_keys_for_instance",
    "workspace_resolves",
]


def workspace_resolves(store: OfficeStore, workspace_id: str) -> bool:
    """Does a workspace record exist for ``workspace_id``?

    Derived the way :func:`snapshot._offices_summary` derives ``orphaned`` —
    membership in ``WorkspaceStore().list_all(include_archived=True)``
    (``snapshot.py:450``) — so this predicate and the ``orphaned_office``
    parity warning cannot answer differently. In particular an ARCHIVED
    workspace still resolves: its office is not an orphan and archiving it
    would be data loss, not cleanup.
    """

    wsid = safe_id(workspace_id)
    if not wsid:
        return False
    from ..store import WorkspaceStore

    return wsid in {
        getattr(w, "id", None)
        for w in WorkspaceStore().list_all(include_archived=True)
    }


def archive_orphaned_surface(
    store: OfficeStore,
    workspace_id: str,
    *,
    updated_by: str = "operator",
    dry_run: bool = False,
) -> dict:
    """Move a whole ORPHANED office surface out of the projection.

    The operator's exit from the ``orphaned_office`` parity warning. Before
    this existed, a surface whose workspace record had gone raised a HUD
    parity-warning chip forever and the only way to clear it was deleting
    files by hand in the live runtime root — so the honest instrument was a
    first-class verb (the same reasoning ``office resolve-conflict`` rides,
    and the board warning's "archive to repair" hint has had an equivalent
    since inception; the office side had none).

    REFUSES a surface whose workspace still resolves. That is the whole
    safety property: this moves an entire surface — folders, every active
    and archived placement, the conflict sidecars — so pointed at a LIVE
    workspace it is a mass delete wearing a cleanup verb's name. The check
    runs twice, once before the lock for a clean refusal and once inside it,
    because a workspace can be re-created between the two.

    Archive-never-delete, like every other removal in this store: the
    directory is MOVED under ``paths.office_surface_archive_root()``, never
    unlinked, so a mistaken archive is recoverable by moving it back.

    ``updated_by`` is on the domain event, not just the signature. It was
    accepted and discarded until 2026-08-19 — the ONE verb in this store
    that moves a whole surface was also the only one whose event could not
    say who moved it, which is exactly backwards: the 2026-08-15 mass
    archive is the precedent for wanting attribution most on the highest
    blast radius.
    """

    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    if not store.surface_exists(wsid):
        raise NotFound(f"office:{wsid}")
    store._guard_surface_is_orphaned(wsid)

    surface = store.get_surface(wsid)
    # ``.actors`` on both, and the shortfall deliberately dropped: this
    # verb MOVES the directory, so every file leaves whether or not it
    # decoded, and these two numbers are a report of what could be counted
    # rather than of what moved. A count that refused on an undecodable file
    # would block the one verb an operator has for clearing an orphaned
    # surface — which is usually orphaned BECAUSE something about it is
    # broken. Written out rather than inherited from a thin view (AX5).
    active = store.scan_actors(wsid).actors
    archived = store.scan_actors(wsid, include_archived=True).actors
    destination = _free_surface_archive_dir(wsid)
    result = {
        "workspace_id": surface.workspace_id,
        "revision": surface.revision,
        "folders": list(surface.folders),
        "actor_count": len(active),
        "archived_placement_count": max(0, len(archived) - len(active)),
        "archived_as": destination.name,
    }
    if dry_run:
        # Full validation + the refusal check ran; nothing moved, no event.
        return result

    with office_lock(wsid):
        # Re-checked under the lock: a workspace re-created (or a surface
        # already archived by a concurrent operator) between the checks
        # above and here must not be archived anyway.
        if not store.surface_exists(wsid):
            raise NotFound(f"office:{wsid}")
        store._guard_surface_is_orphaned(wsid)
        destination = _free_surface_archive_dir(wsid)
        destination.parent.mkdir(parents=True, exist_ok=True)
        paths.office_dir(wsid).rename(destination)
        result["archived_as"] = destination.name
        # The accounted degrade, emitted BEFORE the domain event and inside
        # the lock, exactly like the two emitters above. ``office_surface``
        # ``refresh`` says "this row is not expressible as a fold, re-fetch
        # it", which is the truth: the offices row and every office_actor row
        # under it left in one move and there is no remove-a-surface op on
        # this wire. It is what demotes the batch to a full core — WITHOUT it
        # the covered ``office.surface.updated`` below would be the only
        # entry in an otherwise-coverable batch, shipping a patch frame with
        # an EMPTY patches list: the client advances its watermark having
        # folded nothing and keeps the archived surface, and its
        # ``orphaned_office`` chip, forever. See
        # ``state_patches.emit_office_surface_refresh``.
        store._emit_surface_refresh_patch(surface.workspace_id)
        store._emit(
            "office.surface.updated",
            workspace_id=surface.workspace_id,
            change="archived",
            revision=surface.revision,
            updated_by=_safe_actor_ref(updated_by),
        )
    return result


def _guard_surface_is_orphaned(store: OfficeStore, workspace_id: str) -> None:
    if store.workspace_resolves(workspace_id):
        raise ValueError(
            f"office surface '{workspace_id}' is NOT orphaned — its workspace "
            "still resolves, so archiving it would move a live surface (every "
            "actor placement included) out of the projection. Archive the "
            "workspace itself if that is what you meant."
        )


def _instance_bound_actor(store: OfficeStore, actor, canonical: str) -> bool:
    """Is *actor* the placement of the instance whose canonical id is given?

    The ONE spelling of "bound to this instance", asked by both the prune
    below and the archived-side read beside it. Persona-id-keyed actors
    answer ``False`` by construction (they carry no ``persona_instance_id``)
    and survive instance churn by design.
    """

    from ..persona_assignments import canonical_persona_instance_id

    bound = actor.persona_instance_id
    if not bound:
        return False
    return (
        canonical_persona_instance_id(bound, persona_id=actor.persona_id) or bound
    ) == canonical


def archive_actors_for_instance(
    store: OfficeStore,
    persona_instance_id: str,
    *,
    reason: str = "instance_reaped",
    correlation_id: str | None = None,
) -> dict:
    """Hermes prune-lane hook: archive every active placement bound to a
    reaped persona instance so no phantom desk file re-materializes the
    agent (NEVER a launcher-side filter — the orphan-tombstone precedent).
    Persona-id-keyed placements survive instance churn by design.

    Returns ``{"archived": N, "failed": M, "archived_actor_keys": [...],
    "failures": [{actor_key, workspace_id, error}]}`` — byte-identical to
    what it has always returned, and now DERIVED from one typed
    :class:`OfficeActorOutcome` per key this loop reached (H-H3). The four
    keys were three tallies and two lists kept in parallel; three of them
    could disagree with the fourth and nothing would have said so. They are
    one list's projections now, and the counts are its lengths by
    construction.

    The per-actor swallow KEEPS the loop — a prune must not die on one bad
    file, and the retirement it serves is authoritative with or without the
    office projection — but for a long time it swallowed the IDENTITIES too:
    a bare ``0`` meant two opposite things (nothing matched, and three
    matches all failed), and the counts that replaced it still could not
    answer *which* desk is still on the canvas after a retire said it was
    gone. Placement plan D7 makes that half VISIBLE at this ONE chokepoint,
    because a caller that re-derived the list would be a second,
    disagreeing answer to a question this loop already knows: the keys it
    archived, and the failures it survived, leave WITH the counts.

    The counts stay, and are the lists' lengths by construction; every
    existing caller keeps reading exactly the two keys it read before.

    ``correlation_id`` is the RETIRE GESTURE's token, and it rides down to
    each :meth:`remove_actor` so the ``office.actor.removed`` event and the
    ``state.patched`` remove row this loop produces carry the same id the
    operator's create half carried. It defaults to ``None``, which is what
    keeps the janitor/prune callers — who have no gesture behind them —
    byte-identical to before this parameter existed. A default of "mint one"
    would be worse than nothing: it would join a prune to a gesture that
    never happened.
    """

    target = str(persona_instance_id or "").strip()
    if not target:
        return {"archived": 0, "failed": 0, "archived_actor_keys": [], "failures": []}
    from ..persona_assignments import canonical_persona_instance_id

    canonical = canonical_persona_instance_id(target) or target
    outcomes: list[OfficeActorOutcome] = []
    for wsid in store.list_workspaces():
        # The scan's ``unreadable`` is SPENT here, not dropped: the rows
        # alone answer "these are the actors" for a directory this read may
        # only have partly decoded, and this loop turns that answer into a
        # COMPLETENESS claim — an empty ``failures``
        # is the retire ack's positive statement that every bound actor is
        # off the level (``agent_retire`` says so at its own docstring). A
        # bound desk whose file would not decode is not archived and is not
        # visible either way, so the shortfall becomes a failure row of its
        # own rather than a shorter loop nobody can see.
        scan = store.scan_actors(wsid)
        if scan.unreadable:
            outcomes.append(OfficeActorOutcome.scan_unreadable(wsid, scan))
        for actor in scan.actors:
            if not store._instance_bound_actor(actor, canonical):
                continue
            try:
                store.remove_actor(
                    wsid,
                    actor.actor_key,
                    reason=reason,
                    updated_by="harness",
                    correlation_id=correlation_id,
                )
            except Exception as exc:  # noqa: BLE001 — the loop survives one bad file
                outcomes.append(
                    OfficeActorOutcome.archive_failed(wsid, actor.actor_key, exc)
                )
                continue
            outcomes.append(OfficeActorOutcome.archived(wsid, actor.actor_key))
    archived_keys = [o.actor_key for o in outcomes if o.succeeded]
    failures = [o.as_failure_row() for o in outcomes if not o.succeeded]
    return {
        "archived": len(archived_keys),
        "failed": len(failures),
        "archived_actor_keys": archived_keys,
        "failures": failures,
    }


def archived_actor_keys_for_instance(store: OfficeStore, persona_instance_id: str) -> list[str]:
    """Which ARCHIVED actors are bound to this instance — the replay's evidence.

    Read-only, and the reason it exists is idempotence: ``agent retire``
    answers a second call for an already-archived instance with the same ack
    rather than ``not_found`` (plan D11), and "the same ack" has to include
    every ARCHIVED actor bound to this instance — a SUPERSET of what the
    first call archived whenever another lane (``runtime.office.remove``)
    archived one earlier; a replay names the union, never the first call's list. The prune above cannot supply
    them a second time — it archived them, so they are no longer live for it
    to find — and a caller that reconstructed the list from a scene snapshot
    would be re-deriving a store fact from a render. This asks the archive.

    RAISES :class:`ActorsUnreadable` when either directory it walks would not
    fully decode, and that is the C4 correction rather than a new fragility.
    This list is EVIDENCE — the replay's answer to "which desks are off the
    level" — and it was built from the rows alone, which drop what could not
    be read and report the remainder as complete. A short list here is not
    a smaller truth, it is a DIFFERENT claim: a bound desk whose archive copy
    will not decode reads as "not archived by this instance", which is the
    one thing an empty list is supposed to rule out. The caller
    (``agent_retire``) turns the refusal into an ``office_archive_failures``
    row, so the shortfall reaches the operator instead of a silently short
    list of keys.
    """

    target = str(persona_instance_id or "").strip()
    if not target:
        return []
    from ..persona_assignments import canonical_persona_instance_id

    canonical = canonical_persona_instance_id(target) or target
    keys: list[str] = []
    for wsid in store.list_workspaces():
        # Both reads gated, and gated on the WIDER one: the archive-inclusive
        # scan covers the live directory and the archive together, so its
        # count is the shortfall of everything this answer depends on. The
        # live scan still supplies the re-added keys to skip, exactly as
        # before — the discrimination stays "which DIRECTORY holds it".
        live_scan = store.scan_actors(wsid)
        scan = store.scan_actors(wsid, include_archived=True)
        if scan.unreadable:
            raise ActorsUnreadable(
                f"office actors unreadable in {wsid}: {scan.unreadable}"
            )
        live = {actor.actor_key for actor in live_scan.actors}
        for actor in scan.actors:
            if actor.actor_key in live:
                continue
            if not store._instance_bound_actor(actor, canonical):
                continue
            keys.append(actor.actor_key)
    return keys


def _archive_actor_locked(
    store: OfficeStore,
    surface: OfficeSurface,
    actor: OfficeActor,
    *,
    reason: str,
    updated_by: str,
    emit: bool = True,
    correlation_id: str | None = None,
    record_tombstone: bool = True,
) -> None:
    actor.state = "archived"
    actor.revision += 1
    actor.updated_at = now()
    actor.updated_by = _safe_actor_ref(updated_by)
    _write_archived_actor(actor)
    paths.office_actor_path(actor.workspace_id, actor.actor_key).unlink(missing_ok=True)
    # The ONE line the diagnostic mode skips. The archive copy above is
    # written unconditionally — archive-never-delete is not the thing being
    # traded — and only the realm-visible ledger entry is withheld, because
    # only that entry crosses machines (``adopt_remote_surface`` merges it)
    # and therefore only that entry is an assertion about the realm rather
    # than about this projection. See ``remove_actor``'s ``record_tombstone``.
    if record_tombstone and actor.actor_key not in surface.archived_actor_keys:
        surface.archived_actor_keys = [*surface.archived_actor_keys, actor.actor_key][-ARCHIVED_LEDGER_CAP:]
        surface.updated_at = now()
        _write_surface(surface)
    # The archive half of the lifecycle pair, INSIDE the lock and BEFORE the
    # domain event — the same ordering ``upsert_actor`` uses, for the same
    # monotonicity reason (see ``_emit_actor_patch``).
    #
    # It fires for ``emit=False`` too, and that is correct rather than an
    # oversight: ``resolve_conflict``'s edit-vs-remove branch suppresses the
    # DOMAIN event, but the row really did leave the office and a client that
    # never heard so would render a desk the store no longer has. Until
    # 2026-09-04 that batch demoted anyway on its own uncovered
    # ``office.actor.conflict_resolved``, so the patch cost nothing there and
    # was merely honest; since w12/l3 gave the conflict ledger a row and the
    # event became coverable, this remove is the ONLY thing telling a folding
    # client the desk went — which is what the paragraph above was insuring
    # against, arriving.
    store._emit_actor_remove_patch(actor, correlation_id=correlation_id)
    if emit:
        store._emit(
            "office.actor.removed",
            correlation_id,
            workspace_id=actor.workspace_id,
            actor_key=actor.actor_key,
            reason=reason,
        )
