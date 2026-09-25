"""The office store's ``state.patched`` producers: the actor upsert/remove, the
surface, the conflict-resolved and the surface-refresh patches, each emitted from
the object just written, inside the lock that wrote it.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_runtime.models import OfficeActor, OfficeSurface

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "_emit_actor_patch",
    "_emit_actor_remove_patch",
    "_emit_conflict_resolved_patch",
    "_emit_surface_patch",
    "_emit_surface_refresh_patch",
]


def _emit_actor_patch(
    store: OfficeStore, actor: OfficeActor, *, created: bool, correlation_id: str | None = None
) -> None:
    """Emit the S7-A ``office_actor`` patch for one actor write.

    Called from INSIDE ``office_lock`` and handed the in-memory actor that
    was just written. Both are load-bearing, and together they are the
    monotonicity guarantee the whole patch lane rests on:

    * **Inside the lock.** ``office_lock`` is a cross-process file lock, so
      holding it across (write file → append event) makes EventLog order
      agree with revision order for a given actor. Appending after release
      admits the inversion: writer A takes rev 2 and writer B takes rev 3,
      B's append wins the race, and the fold applies rev 3 at the lower
      offset then rev 2 at the higher — leaving the launcher's core at rev 2
      while disk says 3, with no gap for the ``base_offset`` check to catch.
      The stream watermark stays monotonic (it is the log offset); the
      ENTITY watermark would not be, and nothing downstream would notice.
    * **From the written object rather than a re-read.** Stated honestly
      after mutation testing showed it is NOT independently load-bearing:
      swapping in a ``get_actor`` re-read stayed green, because the re-read
      happens under the same lock and therefore cannot see another writer.
      It is defense-in-depth for the day someone moves this call out of the
      lock — the placement above is the actual guarantee, and the re-read
      would only turn a lock bug into a subtler one. Do not read the two
      bullets as two independent guards; there is one, and it is the lock.

    ``created`` says the row was ABSENT before this write — a first
    placement, or a re-add resurrecting an archived key. It rides the patch
    as an additive marker so ``patch_coverage`` can gate the widened op
    behind the ``office_actor_lifecycle`` capability token; the fold itself
    inserts-on-absent either way. It replaces the old
    ``replaced_existing``/``surface_rewritten`` pair, which existed to route
    creates and ledger-clearing re-adds onto ``refresh`` because a patch
    could not express the parent office row. The 2026-08-16 fold-promotion
    plan (§V1) retired that: ``actor_count``, ``actors_truncated`` and the
    ``archived_actor_keys`` delta under the two lifecycle ops are exactly
    derivable by a client from the rows it folds, so they no longer need a
    wire row and these writes no longer need to demote.

    The ONE case a patch still cannot express is TRUNCATION. Past
    ``MAX_OFFICE_ACTORS_PROJECTED`` the snapshot projects a CUT of the actor
    list, and which actors survive the cut is not client-decidable — neither
    the row's presence nor the derived counts can be folded — so the count is
    taken post-write, under the lock that is already held, and a workspace
    over the bound keeps the honest ``refresh``.

    UNREADABILITY DEMOTES TOO, and that is AX5's correction here. This
    guard's job, in its own words, is to know when the projection is no
    longer complete — and truncation is only ONE of the two ways it can be
    short. ``serve_rpc._office_projection`` says the other out loud beside
    its own cut: ``actors_unreadable`` counts "rows the platform took",
    against ``actors_truncated``'s "a cut WE chose". That number rides the
    office ROW, and no ``office_actor`` patch can express it, so a client
    folding one keeps whatever it last heard. This guard read
    ``list_actors``, which had already dropped the count before the
    comparison — the worst site in the set, because it is the one whose
    whole purpose was to notice incompleteness.

    A short scan therefore takes the same ``refresh`` a truncation takes.
    The cost, stated: an office holding one permanently-undecodable file
    demotes every write in that workspace to a full core. That is the
    degrade this lane's own contract already names as its floor — "a missing
    patch is a missing PROMOTION" — paid on a store that is in an abnormal
    state and should be loud about it, rather than a fold that quietly
    serves a number nobody can correct.

    Cost of the count itself, named rather than discovered: the scan is a
    directory glob plus a JSON parse per actor, on a mutation path. It is
    bounded by the same 200-actor projection cap it is checking, and it runs
    under a lock that already serializes office writes — the alternative (a
    filename glob) would count unparseable files as members, which is the
    wrong direction for this guard in the other direction.

    Best-effort like ``_emit`` beside it: a patch-lane fault must never take
    an office write down, and a missing patch is a missing PROMOTION — the
    batch then ships the full core it would have shipped before this lane
    existed.
    """

    try:
        from ..office_models import MAX_OFFICE_ACTORS_PROJECTED
        from ..state_patches import emit_office_actor_patch, emit_office_actor_refresh

        scan = store.scan_actors(actor.workspace_id)
        if scan.unreadable or len(scan.actors) > MAX_OFFICE_ACTORS_PROJECTED:
            emit_office_actor_refresh(
                store.event_log,
                actor.workspace_id,
                actor.actor_key,
                correlation_id=correlation_id,
            )
        else:
            emit_office_actor_patch(
                store.event_log, actor, created=created, correlation_id=correlation_id
            )
    except Exception as exc:
        import logging

        # The CLASS in the message, not only in the traceback. This swallow is
        # one of the five paths that leave a covered domain event without its
        # paired patch, and the stream now DEMOTES that batch to a full core
        # (`snapshot_build reason=demote`) rather than shipping an empty patch
        # frame. A grep-joinable class name is what makes that demote
        # attributable instead of mysterious.
        logging.getLogger(__name__).warning(
            "office actor patch emit failed: %s error=%s",
            actor.actor_key,
            type(exc).__name__,
            exc_info=True,
        )


def _emit_surface_patch(
    store: OfficeStore, surface: OfficeSurface, *, correlation_id: str | None = None
) -> None:
    """Emit the ``office_surface`` patch for one folder-taxonomy write.

    Called from INSIDE ``office_lock`` and BEFORE the paired
    ``office.surface.updated``, for the two reasons ``_emit_actor_patch``
    gives at length: the cross-process lock is what makes EventLog order
    agree with revision order for this surface, and the pairing is what lets
    the coverage classifier treat the domain event as carrying no fold state
    of its own. A patch appended after the lock admits the inversion where a
    lower revision lands at a higher offset and the client holds the older
    folder list with nothing downstream to notice.

    No truncation guard, unlike ``_emit_actor_patch``. That guard exists
    because past ``MAX_OFFICE_ACTORS_PROJECTED`` the snapshot ships a CUT of
    the actor list and the derived counts stop being client-computable.
    This row touches neither the list nor the counts — ``folders`` and the
    surface ``revision`` are projected whole at any office size — so there
    is no size at which it stops being expressible.

    Best-effort like ``_emit`` beside it: a patch-lane fault must never take
    a folder write down, and a missing patch is a missing PROMOTION — the
    batch ships the full core it would have shipped before this lane
    existed.
    """

    try:
        from ..state_patches import emit_office_surface_patch

        emit_office_surface_patch(
            store.event_log, surface, correlation_id=correlation_id
        )
    except Exception as exc:
        import logging

        # See ``_emit_actor_patch``: the exception class rides the message so
        # the demote this suppression now forces is attributable.
        logging.getLogger(__name__).warning(
            "office surface patch emit failed: %s error=%s",
            surface.workspace_id,
            type(exc).__name__,
            exc_info=True,
        )


def _emit_actor_remove_patch(
    store: OfficeStore, actor: OfficeActor, *, correlation_id: str | None = None
) -> None:
    """Emit the ``office_actor`` ``remove`` for one archive.

    No truncation guard, deliberately: a remove carries no ``changed`` and
    makes no claim about the projected list's membership — it says one key
    left, which is true under a cut as well as under a complete list. The
    client's own truncated-base guard is what refuses the fold when its held
    projection was already a cut.

    Best-effort, like every emitter in this class.
    """

    try:
        from ..state_patches import emit_office_actor_remove

        emit_office_actor_remove(
            store.event_log,
            actor.workspace_id,
            actor.actor_key,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        import logging

        # See ``_emit_actor_patch``: the exception class rides the message so
        # the demote this suppression now forces is attributable.
        logging.getLogger(__name__).warning(
            "office actor remove patch emit failed: %s error=%s",
            actor.actor_key,
            type(exc).__name__,
            exc_info=True,
        )


def _emit_conflict_resolved_patch(
    store: OfficeStore, workspace_id: str, actor_key: str, *, correlation_id: str | None = None
) -> None:
    """Emit the ``office_conflict`` ``remove`` for one resolved sidecar.

    The row ``office.actor.conflict_resolved`` never had, and the reason it
    sat on ``patch_coverage``'s must-stay-absent list through three
    successive arguments. The event's fold state is not on the ACTOR row at
    all: it is the office row's ``conflict_actor_keys``, read off the sidecar
    files by :meth:`scan_conflicts`, and EVERY arm of
    :meth:`resolve_conflict` archives a sidecar — ``take="local"`` included,
    which writes no actor row of any kind. Without this row a covered batch
    would fold the resolved desk and leave the sync strip's conflict pill lit
    for the rest of the session.

    Called from inside ``office_lock`` and before the domain event, exactly
    like its two siblings above — see ``_emit_actor_patch`` for why the
    placement rather than the argument is the monotonicity guarantee.

    Best-effort, like every emitter in this class: a patch-lane fault is a
    missing PROMOTION, never a failed resolve.
    """

    try:
        from ..state_patches import emit_office_conflict_resolved_patch

        emit_office_conflict_resolved_patch(
            store.event_log,
            workspace_id,
            actor_key,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        import logging

        # See ``_emit_actor_patch``: the exception class rides the message so
        # the demote this suppression now forces is attributable.
        logging.getLogger(__name__).warning(
            "office conflict resolved patch emit failed: %s error=%s",
            actor_key,
            type(exc).__name__,
            exc_info=True,
        )


def _emit_surface_refresh_patch(store: OfficeStore, workspace_id: str) -> None:
    """Best-effort like every emitter in this class — a patch-lane fault must
    never take the archive down, and a missing refresh is a missing DEMOTE
    that the batch's own uncovered content still forces on any client that
    did not declare ``office_surface``."""

    try:
        from ..state_patches import emit_office_surface_refresh

        emit_office_surface_refresh(store.event_log, workspace_id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "office surface refresh patch emit failed: %s", workspace_id, exc_info=True
        )
