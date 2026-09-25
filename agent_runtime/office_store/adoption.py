"""Realm-sync adoption: take a peer's surface (the archived ledger is a union,
never the peer's wholesale) and a peer's actor, both through the class-key and
tombstone fences.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_runtime.locks import office_lock
from agent_runtime.models import OfficeActor, OfficeSurface
from agent_runtime.office_store.files import _write_actor, _write_surface
from agent_runtime.office_store.models import ARCHIVED_LEDGER_CAP
from agent_runtime.sync_merge import merge_archived_ledgers
from agent_runtime.office_store.normalize import _safe_actor_ref
from agent_runtime.serde import safe_id

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "adopt_remote_actor",
    "adopt_remote_surface",
]


def adopt_remote_surface(
    store: OfficeStore,
    surface: OfficeSurface,
    *,
    updated_by: str = "realm_sync",
    correlation_id: str | None = None,
) -> OfficeSurface:
    """Write a PEER's office surface verbatim — the realm pull's surface arm.

    ``office_sync.apply_office_pull`` wrote this row with a raw
    ``atomic_json_write`` until H1, so the ONE lane that rewrites a live
    office from outside this machine emitted nothing while the archive arm
    beside it (``remove_actor``) emitted a full pair. The asymmetry was the
    defect: a pull that DELETED a desk reached every live consumer and a pull
    that GAVE you one reached none.

    A verb of its own rather than ``update_surface``, because the two write
    different things. ``update_surface`` authors LOCAL intent — it lazily
    creates the surface (refusing an unresolved workspace), normalizes the
    folder list and BUMPS the revision. A pull adopts a record the peer
    already numbered: the revision is the REMOTE's or the next
    ``classify_three_way_pull`` re-classifies a row nobody edited, and the
    surface must be writable for a workspace whose local record has not
    arrived yet (the pull is exactly how such a workspace arrives).

    ``updated_by`` records the SYNC, matching the archive arm's
    ``updated_by="realm_sync"``. It is hash-neutral: ``office_content_hash``
    excludes ``updated_by`` (with ``revision`` and the timestamps), so the
    caller's ``baseline[key] = remote_hash`` stays keyed off the remote
    content.

    Verbatim in every field BUT ONE. ``archived_actor_keys`` is UNIONED with
    the local ledger (:func:`merge_archived_ledgers`), because that field is
    not the peer's opinion about this workspace — it is the resurrection
    guard, and the pull is the one lane that can reach it from outside this
    machine. Adopting it wholesale erased any tombstone the peer had not
    heard of, which is a deletion of the exact evidence
    ``classify_three_way_pull(..., locally_archived=…)`` reads to refuse a
    resurrection. Reachable, not theoretical: publish records the LOCAL hash
    as the baseline, so an install that archives a desk and publishes is
    ``unchanged`` on its next pull — and one peer edit away from
    ``take_remote`` over its own ledger.

    The merge is hash-neutral wherever nothing was actually lost (the peer's
    order leads, so a local subset re-hashes to the remote's exact list); it
    is deliberately hash-CHANGING when a local-only key survives, which
    leaves the surface classified as locally edited until the next publish
    carries the fuller ledger back to the realm. That is the honest state:
    this install now holds a ledger the realm has not seen.

    A CREATE emits only the domain ``office.surface.created`` and no patch —
    the same ruling ``update_surface`` rides for the same reason (a client
    that has never held this workspace answers a three-field subset with
    ``patch_without_target`` and pays for the patch AND the core).
    """

    wsid = safe_id(surface.workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    surface.workspace_id = wsid
    surface.updated_by = _safe_actor_ref(updated_by)
    with office_lock(wsid):
        existed = store.surface_exists(wsid)
        if existed:
            # Read INSIDE the lock that will hold for the write: a local
            # archive racing this pull must land on one side of the union or
            # the other, never between the read and the write.
            surface.archived_actor_keys = merge_archived_ledgers(
                surface.archived_actor_keys,
                store.get_surface(wsid).archived_actor_keys,
                cap=ARCHIVED_LEDGER_CAP,
            )
        _write_surface(surface)
        if existed:
            # INSIDE the lock and BEFORE the domain event, like every other
            # emitter in this class — see ``_emit_surface_patch``.
            store._emit_surface_patch(surface, correlation_id=correlation_id)
            store._emit(
                "office.surface.updated",
                correlation_id,
                workspace_id=wsid,
                change="realm_sync",
                revision=surface.revision,
            )
        else:
            store._emit("office.surface.created", workspace_id=wsid)
    return surface


def adopt_remote_actor(
    store: OfficeStore,
    actor: OfficeActor,
    *,
    updated_by: str = "realm_sync",
    correlation_id: str | None = None,
) -> OfficeActor:
    """Write a PEER's actor row verbatim — the realm pull's adopt/converge arm.

    The twin of :meth:`adopt_remote_surface`, and the half that actually
    puts a desk on somebody's canvas. Before H1 this was
    ``atomic_json_write(paths.office_actor_path(...))`` inside
    ``apply_office_pull``, so an adopted desk was invisible to the office
    subscribe lane, to the patch fold, and to anything tailing ``office.*``.

    Three properties the raw write had and this verb must not lose, each
    pinned by a test rather than by this sentence:

    (a) **the revision is the REMOTE's.** No ``base_revision + 1``. A pull
        that renumbered revisions would hand the next
        ``classify_three_way_pull`` a row that looks locally edited, turning
        every subsequent pull of an untouched desk into a conflict.
    (b) **``updated_by`` records the sync**, matching the archive arm
        (``remove_actor(..., updated_by="realm_sync")``) rather than
        defaulting to ``"operator"``. Hash-neutral, see the surface twin.
    (c) **nothing is re-derived from the write.** The caller keys its
        baseline off the REMOTE content hash; this verb returns the same
        object it wrote so no re-read can drift from it.

    NOT fenced — a RULING (operator, 2026-08-30, plan
    ``realm-actor-lifecycle-refactor`` D3), no longer an open carve-out.
    The class-key fence and the tombstone fence that ``upsert_actor``
    spends both refuse LOCAL authoring intent, and a pull
    has no operator behind it to offer consent, so fencing it would mean
    refusing to hold a fact a peer already published with nobody present to
    take the override. A peer's un-migrated class key is a conflict-lane
    fact about what that peer published, not a placement this store may
    refuse. (The DESK fence was the third of these until 2026-09-18; it is
    gone with its invariant, so the pull has one fewer thing to be outside
    of and nothing about this ruling's two remaining arms moved.) The two
    REAL holes task #33 had bundled with this one were closed instead: the
    surface arm's tombstone-ledger overwrite (C1,
    :func:`merge_archived_ledgers`) and the pull archive arm's discarded
    outcome (C2, ``office_sync.OfficeArchiveOutcome``).
    ``tests/agent_runtime/test_office_class_key_one_fence.py`` carries the
    ruling and pins it at runtime.

    The neighbour one method down differs on purpose:
    :meth:`resolve_conflict` with ``take="remote"`` writes a peer's row too
    and IS class-key fenced, because an operator asked for it — see its
    docstring for the discriminator.

    The resurrection question is answered UPSTREAM and not here:
    ``classify_three_way_pull(..., locally_archived=True)`` never returns
    ``WRITE_REMOTE`` for a key this store archived, so this verb is never
    reached with a tombstoned key and does not need a second opinion about
    one.
    """

    wsid = safe_id(actor.workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    actor.workspace_id = wsid
    actor.updated_by = _safe_actor_ref(updated_by)
    with office_lock(wsid):
        # ABSENCE of the live row, asked under the lock that will hold for
        # the write — the same question ``upsert_actor`` asks, and the only
        # one the fold's insert-on-absent cares about.
        created = not store.actor_exists(wsid, actor.actor_key)
        _write_actor(actor)
        store._emit_actor_patch(actor, created=created, correlation_id=correlation_id)
        store._emit(
            "office.actor.upserted",
            correlation_id,
            workspace_id=wsid,
            actor_key=actor.actor_key,
            persona_id=actor.persona_id,
            items=len(actor.items),
            revision=actor.revision,
        )
    return actor
