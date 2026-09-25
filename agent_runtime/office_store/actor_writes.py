"""The actor write lane: upsert (``ActorUpsert``: refuse, fence, decide, write,
emit), remove (archive-never-delete), and restore.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes_time import now

from agent_runtime import paths
from agent_runtime.errors import ArchiveUnreadable, NotFound
from agent_runtime.locks import office_lock
from agent_runtime.models import OfficeActor, OfficeItem, OfficeSurface
from agent_runtime.office_store.files import _write_actor, _write_surface
from agent_runtime.office_store.models import MAX_ITEMS_PER_ACTOR, OfficePositionPolicy
from agent_runtime.office_store.normalize import (
    _canonical_actor_key,
    _normalize_actor_persona_ref,
    _normalize_item,
    _safe_actor_ref,
    _stamp_minted_kinds,
)
from agent_runtime.serde import from_jsonable, read_json, safe_id
from agent_runtime.store_conflicts import check_revision

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "ActorUpsert",
    "remove_actor",
    "restore_actor",
    "upsert_actor",
]


def upsert_actor(
    store: OfficeStore,
    workspace_id: str,
    payload: dict[str, Any],
    *,
    updated_by: str = "operator",
    expect_revision: int | None = None,
    allow_class_key: bool = False,
    resurrect: bool = False,
    correlation_id: str | None = None,
    dry_run: bool = False,
    position_policy: OfficePositionPolicy | None = None,
) -> OfficeActor:
    """Write ONE actor placement, creating the surface if it does not exist.

    THE ORDER: refuse an unresolvable workspace BEFORE the lock, run every
    fence INSIDE it, and author the surface only once the write is going to
    happen. It used to be one ``ensure_surface`` call ABOVE the lock, which
    made "this workspace has an office" a side effect of ATTEMPTING a
    placement rather than of making one — a refused write left a default
    ``office.json`` behind on a workspace that had none, for every guard
    (class-key, tombstone, conflict, revision) and by construction.
    The creation could not simply move down into the existing lock as an
    ``ensure_surface`` call, because ``office_lock`` is not reentrant
    (``locks._file_lock``) and this frame already holds it; the creation half
    is therefore reachable on its own as :meth:`_ensure_surface_locked`,
    while the refusal — the only part that must keep its precedence over the
    fences — stays where it was.

    ``allow_class_key`` is the sanctioned override for the class→instance
    re-key fence below (``_guard_class_keyed_write``). It is a STORE
    parameter and not a caller-side fence omission on purpose (EG-6.6): an
    override has to be a value someone passed on the record, because the
    alternative — a caller that simply does not call the guard — is
    indistinguishable from a caller that forgot, which is how this fence
    came to exist at four call sites around one store. Only ``harness office
    actor-upsert --allow-class-key`` passes it; the wire lane deliberately
    has no equivalent (a parameter is not consent — see
    ``serve_rpc._runtime_office_upsert``).

    ``resurrect`` is the same kind of parameter for the tombstone fence
    (D1): without it, an upsert of a key that has an archive copy or a live
    resurrection-guard ledger entry raises :class:`ActorArchived` instead of
    re-adding it. It is ORTHOGONAL to ``allow_class_key`` and deliberately
    not implied by it — one answers "may this write use a class key", the
    other "may this write raise the dead", and an operator who consented to
    the first was never asked the second. Only ``harness office
    actor-upsert --resurrect`` passes it; the wire lane again has no
    equivalent, for the reason spelled out there.

    ``position_policy`` is the UNAIMED lane (M10, plan D2), and it is what
    closes the placement race. It applies to a single-item payload that
    carries no point of its own: the caller had no aim, so the store asks the
    policy for one INSIDE ``office_lock``, against the actor set this very
    write is about to land beside. Before this parameter existed the only
    way to place unaimed was to resolve the slot OUTSIDE the lock and send
    the answer as an ordinary position, which left a window — two creates
    that both omit a position and race between their reads and their writes
    computed the same free slot, and the second landed on top of the first.
    The read could not simply be wrapped in ``office_lock`` because the lock
    is not reentrant (``locks._file_lock``), so the resolution had to move
    INTO the write. That is this hook.

    The store supplies the SET and the lock and nothing else: the arithmetic
    stays in ``office_layout_policy``, which is pure and knows no store, and
    the exclusion rule ("skip the actor I am about to write") stays with the
    caller that knows which actor that is. Refused rather than guessed for a
    multi-item payload — one point cannot answer for several items, and a
    store that picked one of them would be inventing a rule its caller never
    stated.
    """

    request = ActorUpsert.parse(workspace_id, payload, unaimed=position_policy is not None)
    wsid, actor_key = request.workspace_id, request.actor_key
    items = request.items
    if not dry_run:
        # The REFUSAL here, the CREATION under the lock (see the write half
        # below). This used to be one ``ensure_surface`` call, and it
        # authored a default ``office.json`` BEFORE any fence had run — so a
        # write the class-key, tombstone, conflict or revision guard
        # was about to refuse still left a live office behind on a
        # surface-less workspace, for every guard and by construction. The
        # refusal keeps its old position on purpose: it is the first thing
        # ``upsert_actor`` can answer about an id, and moving it under the
        # fences would make an unresolved workspace hear a class-key
        # sentence about a placement it can never make.
        store._refuse_unresolvable_workspace(wsid)
    with office_lock(wsid):
        # THE class-key fence, first and inside the lock (EG-6.6). First
        # because that is the precedence the four caller-side copies had —
        # they all ran before any store call — and inside the lock because
        # the predicate reads the ledger and the live actor set, which a
        # concurrent writer can move between a caller's read and this write.
        store._guard_class_keyed_write(wsid, payload, allow_class_key=allow_class_key)
        store._guard_no_conflict(wsid, actor_key)
        if position_policy is not None:
            items = _place_unaimed(store, wsid, request, position_policy)
        # The DESK fence stood here, between the conflict guard and the
        # archive read, until 2026-09-18. It is gone with the invariant it
        # enforced (see the note at the top of this module): a desk is
        # furniture addressed by its own synthetic id, so a workspace holds
        # as many as an operator places. Nothing replaced it — no reader was
        # moved down into the write path, and the two fences either side of
        # this line are unchanged.
        existing = store.get_actor(wsid, actor_key) if store.actor_exists(wsid, actor_key) else None
        archived_path = paths.office_archived_actor_path(wsid, actor_key)
        # THE tombstone fence (D1), before the archive is read rather than
        # after. Without consent this write is refused whatever the archive
        # decodes to, so decoding it first would only mean answering
        # ``archive_unreadable`` — "ask again once the file is readable" —
        # to a caller whose write can never be accepted no matter how
        # readable the file becomes. ``ArchiveUnreadable`` stays reachable on
        # the CONSENTED path below, which is the path that actually needs the
        # revision token the archive carries.
        #
        # ``existing is None`` is load-bearing: a LIVE row whose key also
        # sits in the ledger is a ledger the write should clean up, not a
        # resurrection, and that half of the arm still runs untouched.
        if existing is None:
            store._guard_archived_actor(
                wsid,
                actor_key=actor_key,
                persona_instance_id=request.persona_instance_id,
                archived_path=archived_path,
                resurrect=resurrect,
            )
        archived = _read_archived(actor_key, archived_path) if existing is None else None
        check_revision(existing.revision if existing else None, expect_revision)
        ts = now()
        actor = _next_actor(request, items, existing, archived, ts=ts, updated_by=updated_by)
        if dry_run:
            # Full validation (payload/items/secret-name), conflict guard, and
            # revision check ran above; return the would-be actor in memory.
            # Write nothing, touch no ledger, emit no event.
            return actor
        # THE surface creation, here rather than before the lock: every
        # fence above has passed, so this is the first line of an upsert
        # that is actually going to happen. ``_ensure_surface_locked``
        # rather than ``ensure_surface`` because ``office_lock`` is not
        # reentrant and this frame already holds it.
        surface = store._ensure_surface_locked(wsid, created_by=updated_by)
        _write_actor(actor)
        _forget_resurrected_key(surface, actor_key, archived_path, ts=ts)
        _emit_upserted(
            store, actor, created=existing is None, item_count=len(items), correlation_id=correlation_id
        )
    return store.get_actor(wsid, actor_key)


@dataclass(frozen=True, slots=True)
class ActorUpsert:
    """One validated upsert request: the refusals that need no lock, answered.

    ``items`` is empty for the UNAIMED lane — its one item is normalized inside
    the lock by :func:`_place_unaimed`, never here, so no placeholder point is
    ever constructed.
    """

    workspace_id: str
    persona_id: str
    raw_instance: str | None
    actor_key: str
    raw_items: tuple[Any, ...]
    items: list[OfficeItem]
    backing_profile: str | None

    @property
    def persona_instance_id(self) -> str | None:
        return _canonical_actor_key(self.persona_id, self.raw_instance) if self.raw_instance else None

    @classmethod
    def parse(cls, workspace_id: str, payload: dict[str, Any], *, unaimed: bool) -> ActorUpsert:
        wsid = safe_id(workspace_id)
        if not wsid:
            raise ValueError("invalid_request")
        if not isinstance(payload, dict):
            raise ValueError("invalid_request: actor payload must be an object")
        persona_id = _normalize_actor_persona_ref(payload.get("persona_id"))
        if not persona_id:
            raise ValueError("invalid_request: persona_id required")
        raw_instance = str(payload.get("persona_instance_id") or "").strip() or None
        actor_key = _canonical_actor_key(persona_id, raw_instance)
        raw_items = payload.get("items")
        if not isinstance(raw_items, (list, tuple)) or not raw_items:
            raise ValueError("invalid_request: items required")
        if len(raw_items) > MAX_ITEMS_PER_ACTOR:
            raise ValueError("invalid_request: too many items")
        if not unaimed:
            items = [_normalize_item(item, persona_id=persona_id) for item in raw_items]
        else:
            # The unaimed lane defers ONE field and refuses up front on the one
            # shape it cannot serve. Everything else about the item — id,
            # persona, kind, folder, display name, scale — is validated below,
            # inside the lock, by the same ``_normalize_item`` call the aimed
            # lane makes; nothing here is normalized twice and no placeholder
            # point is ever constructed, which is the property that keeps a
            # made-up origin from escaping if this arm is later edited.
            if len(raw_items) != 1:
                raise ValueError(
                    "invalid_request: position_policy resolves ONE item's slot; "
                    f"payload carries {len(raw_items)}"
                )
            items = []
        backing_profile = _normalize_actor_persona_ref(payload.get("backing_profile"))
        return cls(wsid, persona_id, raw_instance, actor_key, tuple(raw_items), items, backing_profile)


def _place_unaimed(
    store: OfficeStore, wsid: str, request: ActorUpsert, position_policy: OfficePositionPolicy
) -> list[OfficeItem]:
    """The unaimed item, normalized at the point the policy chooses — called
    with ``office_lock`` held."""
    # M10, closed. The scan and the write are now under ONE
    # acquisition of ``office_lock``, so no concurrent create can
    # land between them and take the slot this one is about to
    # choose. The policy is handed the scan rather than its rows so
    # the completeness question stays visible at the seam that can
    # answer it.
    return [
        _normalize_item(
            request.raw_items[0],
            persona_id=request.persona_id,
            position=position_policy(store.scan_actors(wsid)),
        )
    ]


def _read_archived(actor_key: str, archived_path: Path) -> OfficeActor | None:
    """The archived copy whose revision a re-add carries forward, or ``None``."""
    if not archived_path.exists():
        return None
    # REFUSED, not swallowed. This read is where the revision guard's
    # token lives between a remove and the re-add that follows it:
    # ``base_revision`` below takes the archived revision precisely so
    # a re-added key carries its history forward. ``archived = None``
    # made the base 0 and the new revision 1 — a token BELOW the one
    # every peer and every launcher read model already holds, so the
    # next guarded write on this key reads as a stale prediction
    # against a server that silently rewound. A fresh start is a
    # decision an operator makes (``actor-restore``, a deliberate
    # re-key), never one an unreadable file makes for them.
    try:
        return from_jsonable(OfficeActor, read_json(archived_path))
    except Exception as exc:
        raise ArchiveUnreadable(
            f"archive_unreadable:{actor_key} ({type(exc).__name__})"
        ) from exc


def _next_actor(
    request: ActorUpsert,
    items: list[OfficeItem],
    existing: OfficeActor | None,
    archived: OfficeActor | None,
    *,
    ts: Any,
    updated_by: str,
) -> OfficeActor:
    """The row this upsert writes: the next revision after the live row, else
    after the archived copy, else the first."""
    base_revision = existing.revision if existing else (archived.revision if archived else 0)
    return OfficeActor(
        actor_key=request.actor_key,
        workspace_id=request.workspace_id,
        persona_id=request.persona_id,
        persona_instance_id=request.persona_instance_id,
        backing_profile=request.backing_profile,
        items=_stamp_minted_kinds(items, existing or archived),
        state="active",
        revision=base_revision + 1,
        created_at=existing.created_at if existing else ts,
        updated_at=ts,
        updated_by=_safe_actor_ref(updated_by),
    )


def _forget_resurrected_key(surface: OfficeSurface, actor_key: str, archived_path: Path, *, ts: Any) -> None:
    """An explicit local upsert of an archived key is operator intent to re-add."""
    # Clear the resurrection-guard ledger entry + archive copy
    # so a later pull doesn't re-archive it. The client mirrors exactly
    # this delta during the fold (§V1's derivation table), which is why
    # it no longer forces the write onto the full-core lane.
    if actor_key in surface.archived_actor_keys:
        surface.archived_actor_keys = [k for k in surface.archived_actor_keys if k != actor_key]
        surface.updated_at = ts
        _write_surface(surface)
    archived_path.unlink(missing_ok=True)


def _emit_upserted(
    store: OfficeStore,
    actor: OfficeActor,
    *,
    created: bool,
    item_count: int,
    correlation_id: str | None,
) -> None:
    """The patch and the domain event of one upsert, with ``office_lock`` held."""
    # INSIDE the lock, and from the actor object just written — see
    # _emit_actor_patch for why both halves of that are load-bearing.
    #
    # ``created`` is ABSENCE of the live row, not absence of the key: a
    # resurrection re-add is created=True because the row is missing from
    # the client's list, which is the only question the fold's
    # insert-on-absent asks.
    store._emit_actor_patch(actor, created=created, correlation_id=correlation_id)
    store._emit(
        "office.actor.upserted",
        correlation_id,
        workspace_id=actor.workspace_id,
        actor_key=actor.actor_key,
        persona_id=actor.persona_id,
        items=item_count,
        revision=actor.revision,
    )


def remove_actor(
    store: OfficeStore,
    workspace_id: str,
    actor_key: str,
    *,
    reason: str = "operator",
    updated_by: str = "operator",
    expect_revision: int | None = None,
    correlation_id: str | None = None,
    record_tombstone: bool = True,
    dry_run: bool = False,
) -> OfficeActor:
    """Archive one actor placement — the office's delete.

    ``record_tombstone`` is the AUTHORED-vs-DIAGNOSTIC split (operator
    ruling, 2026-08-30). Defaulted true, which is every caller that carries
    an operator's intent to delete: the launcher's delete button, the CLI
    without ``--local-only``, the RPC verb. The tombstone is the point there
    — the ledger entry is what a realm pull replicates, and what stops the
    peer's still-live copy from resurrecting the row on the next sync.

    ``False`` is for a repair aimed only at THIS install's projection — a
    doctor remediation, a dispatch step, a census cleanup. Those have no
    operator intent to propagate, and minting a realm-visible tombstone from
    one would delete the row on every machine in the realm to fix a local
    display. The archive copy is still written either way: archive-never-
    delete is not what is being traded, and ``actor-restore`` still works.
    """

    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    with office_lock(wsid):
        if not store.actor_exists(wsid, actor_key):
            # Idempotent: already archived → return the archived copy.
            archived_path = paths.office_archived_actor_path(wsid, actor_key)
            if archived_path.exists():
                # Typed for the same reason the upsert's twin is: the ack
                # this branch returns CARRIES the revision, so a decode
                # failure here is the guard token going missing, not a
                # generic handler crash. Raising the same class means one
                # reason string covers the condition on both write verbs.
                try:
                    return from_jsonable(OfficeActor, read_json(archived_path))
                except Exception as exc:
                    raise ArchiveUnreadable(
                        f"archive_unreadable:{actor_key} ({type(exc).__name__})"
                    ) from exc
            raise NotFound(f"office_actor:{actor_key}")
        actor = store.get_actor(wsid, actor_key)
        check_revision(actor.revision, expect_revision)
        if dry_run:
            # Existence + revision check ran; return the would-be archived
            # actor in memory (mirrors _archive_actor_locked's mutation) and
            # persist nothing / emit nothing.
            actor.state = "archived"
            actor.revision += 1
            actor.updated_at = now()
            actor.updated_by = _safe_actor_ref(updated_by)
            return actor
        # ``_ensure_surface_locked``, not ``ensure_surface``: this call sits
        # INSIDE ``office_lock(wsid)`` and ``office_lock`` is not reentrant,
        # so the public door would contend with the lock this verb is
        # already holding and refuse ``HarnessLockUnavailable`` at the
        # deadline. It only ever worked because ``ensure_surface`` returns
        # before acquiring when the surface already exists — i.e. the bug
        # was invisible for exactly as long as no surface-less workspace
        # reached this line.
        surface = store._ensure_surface_locked(wsid, created_by=updated_by)
        store._archive_actor_locked(
            surface,
            actor,
            reason=reason,
            updated_by=updated_by,
            correlation_id=correlation_id,
            record_tombstone=record_tombstone,
        )
    return from_jsonable(OfficeActor, read_json(paths.office_archived_actor_path(wsid, actor_key)))


def restore_actor(
    store: OfficeStore,
    workspace_id: str,
    actor_key: str,
    *,
    updated_by: str = "operator",
    correlation_id: str | None = None,
    dry_run: bool = False,
) -> OfficeActor:
    """Un-archive one actor placement — ``harness office actor-restore``.

    The third and last production writer of a live actor file, and the one
    with NO class-key fence — which is a disposition, not an omission
    (EG-6.6's enumeration witness names it as such). Restoring an archived
    class key IS the deliberate resurrection the fence refuses on every other
    path: it takes no payload to be wrong about, writes back exactly the
    bytes the archive holds, and is the very exit
    ``office_class_key_guard.refusal_message`` tells the operator to take.
    Fencing the sanctioned override against itself would leave the refusal
    pointing at a dead end.
    """

    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    with office_lock(wsid):
        archive_path = paths.office_archived_actor_path(wsid, actor_key)
        if not archive_path.exists():
            raise NotFound(f"office_actor:{actor_key}")
        actor = from_jsonable(OfficeActor, read_json(archive_path))
        actor.state = "active"
        actor.revision += 1
        actor.updated_at = now()
        actor.updated_by = _safe_actor_ref(updated_by)
        if dry_run:
            # Archived-copy existence checked; return the would-be restored
            # actor in memory without writing / unlinking / emitting.
            return actor
        _write_actor(actor)
        archive_path.unlink(missing_ok=True)
        # Locked variant — see remove_actor: office_lock is not reentrant.
        surface = store._ensure_surface_locked(wsid, created_by=updated_by)
        if actor_key in surface.archived_actor_keys:
            surface.archived_actor_keys = [k for k in surface.archived_actor_keys if k != actor_key]
            surface.updated_at = now()
            _write_surface(surface)
        store._emit(
            "office.actor.restored",
            correlation_id,
            workspace_id=wsid,
            actor_key=actor_key,
        )
    return store.get_actor(wsid, actor_key)
