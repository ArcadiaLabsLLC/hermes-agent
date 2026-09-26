"""The office lane: the actor wire row (built by the snapshot's own row builder),
and the six emitters — actor / conflict / surface × upsert / remove / refresh.
"""

from __future__ import annotations

from typing import Any

from ..config import AgentRuntimeConfig
from ..events import EventLog
from ..serde import to_jsonable
from .emit import delta_patches_enabled, emit_state_patch
from .models import (
    OFFICE_ACTOR_ENTITY,
    OFFICE_CONFLICT_ENTITY,
    OFFICE_SURFACE_ENTITY,
    PATCH_OP_REFRESH,
    PATCH_OP_REMOVE,
    PATCH_OP_UPSERT,
)
from .payload import office_actor_patch_id

__layer__ = "stores"


def project_office_actor_wire_row(actor: Any) -> dict[str, Any]:
    """The office-actor WIRE row, produced by the SNAPSHOT's own row builder.

    Unlike the persona-instance projection above — which reproduces
    ``persona_instance_summary``'s derived-field logic field-for-field and is
    held to it by a golden — this one CALLS ``snapshot.office_actor_summary_row``
    directly. It can, because that builder is already pure (a field copy off an
    ``OfficeActor`` plus the caller-supplied ``unpublished``): there is no
    ``_profile_visibility_persona`` equivalent to seed a store or emit a stray
    domain event into the mutation's own batch. Byte-parity with a full rebuild
    is therefore STRUCTURAL rather than asserted, which is the stronger of the
    two — a field added to the summary row reaches the patch lane in the same
    commit and cannot drift out of it.

    ``unpublished`` is the one field the builder does not compute, and it MUST be
    recomputed here rather than left to the fold's merge: a drag changes the
    actor's content hash, so a realm-bound actor flips ``unpublished`` False→True
    on the same write. A patch that omitted the key would leave the launcher's
    "unpublished" badge showing the pre-drag answer for the rest of the session —
    the exact stale-derived-field failure S6→S7-A was rewritten to end. The
    derivation mirrors ``snapshot._offices_summary``: no realm behind the
    workspace → no baseline → the key is OMITTED (not False), because "this
    workspace does not publish" and "this actor is published" are different facts.
    """

    from ..snapshot.offices import office_actor_summary_row

    return office_actor_summary_row(actor, unpublished=_office_actor_unpublished(actor))


def _office_actor_unpublished(actor: Any) -> bool | None:
    """``True``/``False`` for a realm-bound actor, ``None`` (→ key omitted) when
    the workspace has no realm or the lookup fails.

    Mirrors ``snapshot._offices_summary``'s ``_actor_unpublished`` closure,
    including its archived-workspace behaviour: that function builds its
    workspace→realm map from ``WorkspaceStore.list_all()``, which excludes
    archived workspaces, so an actor under an archived workspace resolves to
    ``None`` there and must resolve to ``None`` here.

    Best-effort by design: a publication-honesty flag must never be able to take
    an office write down, and ``None`` degrades to the same key-omitted shape a
    non-realm workspace produces.
    """

    try:
        from ..office_models import office_content_hash
        from ..office_sync import read_office_baseline
        from ..store import WorkspaceStore

        workspace = WorkspaceStore().get(str(getattr(actor, "workspace_id", "") or ""))
        if getattr(workspace, "archived", False):
            return None
        realm_id = getattr(workspace, "realm_id", None)
        if not realm_id:
            return None
        baseline = read_office_baseline(str(realm_id))
        key = f"{actor.workspace_id}:actor:{actor.actor_key}"
        return baseline.get(key) != office_content_hash(actor)
    except Exception:
        return None


def emit_office_actor_patch(
    event_log: EventLog,
    actor: Any,
    *,
    created: bool = False,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit an office-actor ``upsert`` carrying the actor's COMPLETE wire row.

    Complete, not a changed-field subset, and that is deliberate: the store has
    no per-field office write — ``upsert_actor`` rewrites the whole actor file
    from a whole payload — so a subset would be an invention of the patch lane,
    and the whole row measures 663–764 bytes against the live canvas (four
    actors, 2026-08-14), an order of magnitude inside the 3584-byte per-value
    budget. It is also what makes the fold a plain row replace — and, since the
    2026-08-16 fold-promotion plan, what makes INSERT-on-absent safe: a client
    that does not hold this actor can materialize it from the patch alone,
    because there is nothing about the row the patch omits.

    ``created=True`` marks a write whose row was ABSENT before it (a first
    placement, or a re-add resurrecting an archived key — absent from the
    client's list either way). It changes nothing about the fold; it is the
    coverage gate's input, so the widened op is promoted only at a client that
    declared ``office_actor_lifecycle``.

    **What still is NOT expressible here.** The office core section is
    workspace-keyed with a nested actor list whose parent row carries derived
    state — ``actor_count``, ``actors_truncated``, ``archived_actor_keys``,
    ``folders``, the SURFACE's own ``revision``/``updated_at``. The
    2026-08-16 validation (§V1) established that under the two LIFECYCLE ops the
    first three are exactly derivable by a client from the rows it folds, so they
    no longer need a wire row of their own. ``folders`` and the surface
    ``revision`` are moved only by ``update_surface``, which has carried its own
    :func:`emit_office_surface_patch` row since 2026-08-16 (WV-H3) — so those
    two are no longer un-expressible either, they are simply somebody else's
    row; ``updated_at`` drift under an ACTOR write is still accepted and
    documented, because no actor write moves the surface's copy of it.
    The one case that remains genuinely inexpressible is TRUNCATION — past
    ``MAX_OFFICE_ACTORS_PROJECTED`` the projected list is a cut the client cannot
    reproduce — and that is what :func:`emit_office_actor_refresh` is now for,
    and all it is for.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_ACTOR_ENTITY,
        entity_id=office_actor_patch_id(actor.workspace_id, actor.actor_key),
        op=PATCH_OP_UPSERT,
        changed=project_office_actor_wire_row(actor),
        created=True if created else None,
        correlation_id=correlation_id,
        persona_id=getattr(actor, "persona_id", None),
        config=config,
    )


def emit_office_actor_remove(
    event_log: EventLog,
    workspace_id: Any,
    actor_key: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit an office-actor ``remove`` — the archive half of the lifecycle pair.

    Carries no ``changed`` by contract, so it is always tiny and can never hit
    the oversize ladder. The fold splices the actor out by key, recomputes the
    derived container counts and appends the key to its mirrored
    ``archived_actor_keys`` ledger — the client-side derivation §V1 established,
    which is why archiving finally has a foldable op at all.

    Idempotent by construction on the client side (remove-if-present), which is
    what lets the same row replay across the stream lane and the office push lane
    without the two colliding.

    Best-effort at its call site like every sibling emitter: a patch-lane fault
    is a missing PROMOTION, never a failed archive.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_ACTOR_ENTITY,
        entity_id=office_actor_patch_id(workspace_id, actor_key),
        op=PATCH_OP_REMOVE,
        correlation_id=correlation_id,
        config=config,
    )


def emit_office_conflict_resolved_patch(
    event_log: EventLog,
    workspace_id: Any,
    actor_key: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit an ``office_conflict`` ``remove`` — one key leaving the conflict ledger.

    A ``remove`` and not an ``upsert`` because the fact moved is a DEPARTURE from
    a list. The fold is the one the launcher already performs for
    ``office_actor``'s remove — splice this id out, idempotently — and it carries
    no payload that could go stale between the emit and the fold, so it can never
    reach the oversize ladder.

    There is deliberately no ARRIVAL op. A conflict sidecar is WRITTEN by realm
    sync, not by a chokepointed office write, so a create has no row to ride and
    the batch that first raises a conflict keeps demoting to a full core exactly
    as it does today. This entity covers the RESOLVE and nothing else, which is
    the whole of what ``office.actor.conflict_resolved`` needed.

    The id is :func:`office_actor_patch_id`'s, reused rather than re-derived: the
    two halves are the same two halves (a workspace id and an actor key), the
    separator argument is the same one, and the launcher splits on the first
    ``/`` for both. A second builder for one id scheme is the drift operator
    task #57 already paid for once.

    Best-effort at its call site like every sibling emitter: a patch-lane fault
    is a missing PROMOTION, never a failed resolve.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_CONFLICT_ENTITY,
        entity_id=office_actor_patch_id(workspace_id, actor_key),
        op=PATCH_OP_REMOVE,
        correlation_id=correlation_id,
        config=config,
    )


def emit_office_surface_patch(
    event_log: EventLog,
    surface: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit an ``office_surface`` ``upsert`` — the folder-taxonomy write's row.

    A SUBSET merge, like ``persona_instance``'s and unlike its ``office_actor``
    sibling's complete-row replace. The reason is the shape of what it patches:
    ``office_actor`` addresses a row the store rewrites whole, so a replace is
    faithful; this addresses the office row itself, which also carries the
    actor list, the derived ``actor_count``/``actors_truncated``, and the
    ``conflict_actor_keys``/``archived_actor_keys`` ledgers. Those belong to the
    ACTOR lifecycle folds and to the client-side derivation §V1 established, and
    a complete-row patch from here would clobber every one of them on a folder
    rename.

    So this carries :data:`OFFICE_SURFACE_PATCH_FIELDS` and nothing else, and
    the launcher merges exactly those three keys.

    Why this write can be covered at all
    ------------------------------------
    The §V1 derivability standard: an event is coverable only when nothing is
    left that ONLY the demoted full core could say. ``update_surface`` moves
    three things — ``folders``, the surface's own ``revision``, and
    ``updated_at`` — and this row carries all three verbatim. It moves no actor
    row, no count, and neither key ledger (``_normalize_folders`` and the
    revision bump are the entire mutation; ``office_store.update_surface``
    touches nothing else). Nothing is dropped because nothing is left over.

    Tiny by construction, so the oversize ladder is unreachable in practice:
    ``folders`` is at most ``MAX_FOLDERS`` (64) names of at most 80 characters
    (``office_store._safe_folder``), an order of magnitude inside the 3584-byte
    per-value budget. If it ever were not, :func:`build_state_patch`'s existing
    accounting degrades the whole patch to ``refresh`` and the batch demotes as
    it does today — an honest re-fetch, never a partial merge onto an office row
    whose folder list the client would then hold half of.

    NOT emitted from ``ensure_surface``. A create authors a surface the client
    has never held, and this subset is not a whole office row — a fold would
    answer it ``patch_without_target`` and re-hydrate, which is strictly worse
    than the full core a create already takes. ``office.surface.created``
    therefore stays uncovered, deliberately.

    Best-effort at its call site like every sibling emitter: a patch-lane fault
    is a missing PROMOTION, never a failed folder write.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_SURFACE_ENTITY,
        entity_id=str(getattr(surface, "workspace_id", "") or ""),
        op=PATCH_OP_UPSERT,
        changed={
            "folders": list(getattr(surface, "folders", []) or []),
            "revision": getattr(surface, "revision", None),
            "updated_at": to_jsonable(getattr(surface, "updated_at", None)),
        },
        correlation_id=correlation_id,
        config=config,
    )


def emit_office_surface_refresh(
    event_log: EventLog,
    workspace_id: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """The accounted degrade for an office SURFACE write no fold can express:
    the whole surface left (``OfficeStore.archive_orphaned_surface``, EG-0.1).

    Same instrument, same reason as :func:`emit_office_actor_refresh` one entity
    up. Archiving an orphaned surface removes the ``offices`` row AND every
    ``office_actor`` row under it in one move; ``OFFICE_SURFACE_PATCH_FIELDS`` is
    a three-key folder subset and there is no remove-a-surface op on this wire,
    so nothing here is expressible as a fold. ``refresh``'s documented meaning
    applies unchanged: *this row is not expressible, re-fetch it*.

    WHY THIS AND NOT A NEW DOMAIN EVENT TYPE. The archive rides the existing
    ``office.surface.updated`` (``change="archived"``), which is a COVERED domain
    event — it promises a folding client that an equivalent ``office_surface``
    patch rides the same batch. Left alone that promise is a silent data loss:
    ``batch_is_patch_coverable`` is an ``all(...)`` with no "at least one patch"
    requirement, so a batch whose only entry is that covered event ships a patch
    frame with an EMPTY ``patches`` list — the client advances its watermark
    having folded nothing and keeps the archived surface, and its
    ``orphaned_office`` chip, forever. That is verbatim the failure
    :func:`emit_office_actor_refresh` documents for the actor lane.

    Registering a NEW uncovered event type would also have worked, and was
    rejected: it moves ``decision_contract_hash``, which is baked into the
    committed producer-derived golden fixtures, making a tests-only stage-zero
    landing a cross-stack fixture regeneration. This entity/op pair already
    exists on the wire and needs no client negotiation — a client that declares
    ``office_surface`` demotes on the ``refresh``, and one that does not demotes
    on the domain event. Both land on the full core, which is the refetch.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_SURFACE_ENTITY,
        entity_id=str(workspace_id or ""),
        op=PATCH_OP_REFRESH,
        correlation_id=correlation_id,
        config=config,
    )


def emit_office_actor_refresh(
    event_log: EventLog,
    workspace_id: Any,
    actor_key: Any,
    *,
    correlation_id: str | None = None,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """The accounted degrade for an office write the client cannot place: the
    actor list is TRUNCATED.

    **This is the only remaining meaning.** It used to carry a second, unrelated
    one — "a SECOND row changed and this lane has no vocabulary for it" (a
    create moved ``actor_count``, a re-add rewrote the resurrection ledger) —
    and that conflation is retired by the 2026-08-16 fold-promotion plan (§V3):
    those writes now emit real ``upsert``/``remove`` ops and the container state
    is derived client-side. What survives is ``refresh``'s documented meaning
    everywhere else in this module: *this row is not expressible as a fold,
    re-fetch it*.

    The surviving producer is ``OfficeStore._emit_actor_patch``'s
    ``> MAX_OFFICE_ACTORS_PROJECTED`` guard. Past that bound the snapshot
    projects a CUT of the actor list, and which actors survive the cut is not
    client-decidable — so neither the row's presence nor the derived counts can
    be folded, and a full core is the honest answer.

    ``refresh`` is not in :data:`FOLDABLE_PATCH_OPS`, so the batch carrying it
    demotes to a full core — which IS the refetch. Emitting this rather than
    simply staying silent is what makes the degrade visible in the log: a silent
    skip would leave the paired (covered) ``office.actor.upserted`` as the only
    entry in an otherwise-coverable batch, which would ship a patch frame with an
    EMPTY ``patches`` list — the launcher would advance its watermark having
    folded nothing and keep the pre-write row forever.
    """

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=OFFICE_ACTOR_ENTITY,
        entity_id=office_actor_patch_id(workspace_id, actor_key),
        op=PATCH_OP_REFRESH,
        correlation_id=correlation_id,
        config=config,
    )
