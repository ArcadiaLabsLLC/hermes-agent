"""Sync conflicts on office actors: scan the sidecars (typed outcomes, never a
guessed key passed off as a read one), resolve one, and the write-path guard.

Functions over an ``OfficeStore`` (composition — the class binds each one as a
method, so ``store.<name>(...)`` reads exactly as before).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_time import now

from agent_runtime import office_models, paths
from agent_runtime.errors import SyncConflict
from agent_runtime.locks import office_lock
from agent_runtime.models import OfficeActor
from agent_runtime.office_store.files import _write_actor
from agent_runtime.office_store.models import ConflictScan, OfficeActorOutcome
from agent_runtime.office_store.normalize import _safe_actor_ref
from agent_runtime.serde import from_jsonable, read_json, safe_id
from agent_runtime.store_conflicts import archive_conflict_sidecar, guard_no_conflict

if TYPE_CHECKING:
    from agent_runtime.office_store.store import OfficeStore

__layer__ = "stores"

__all__ = [
    "_guard_no_conflict",
    "resolve_conflict",
    "scan_conflicts",
]


def scan_conflicts(store: OfficeStore, workspace_id: str) -> ConflictScan:
    """Every unresolved conflict sidecar, and how each key was ARRIVED at.

    Replaces ``conflict_actor_keys``, which returned the bare list and
    answered a decode failure by substituting ``path.stem`` — silently. The
    filename is a TOKEN (``office_models.actor_file_token``: sanitised,
    truncated at 64 with a hash suffix), so for a long key the substitute is
    not the actor key at all, and ``office resolve-conflict --actor <it>``
    finds nothing. A caller handed a bare list could not tell that entry
    from a real one, and both readers of this — the snapshot's parity
    warning and the CLI's surface row — present these as keys an operator
    can act on.

    The substitution STAYS: a conflict the operator can half-name beats a
    conflict they cannot see. What is gone is the silence. Callers that only
    want the keys spell ``.keys``, which makes dropping the provenance a
    visible choice rather than the default.

    ``*.resolved.json`` sidecars are skipped before any read: they are the
    record of a conflict that was already dealt with, not a conflict.
    """

    conflicts_dir = paths.office_conflicts_dir(workspace_id)
    if not conflicts_dir.exists():
        return ConflictScan([], [])
    keys: list[str] = []
    outcomes: list[OfficeActorOutcome] = []
    for path in sorted(conflicts_dir.glob("*.json")):
        if path.name.endswith(".resolved.json"):
            continue
        try:
            payload = read_json(path)
            key = str(payload.get("actor_key") or "").strip()
        except Exception as exc:  # noqa: BLE001 — the scan survives one bad file
            outcomes.append(
                OfficeActorOutcome.conflict_key_from_filename(
                    workspace_id, path.stem, exc
                )
            )
            keys.append(path.stem)
            continue
        # An EMPTY ``actor_key`` in a sidecar that decoded fine is the same
        # guess by a different route — the payload was readable and simply
        # did not say — so it is recorded the same way rather than passing
        # for a read key.
        if not key:
            outcomes.append(
                OfficeActorOutcome.conflict_key_from_filename(
                    workspace_id, path.stem, ValueError("actor_key missing")
                )
            )
            keys.append(path.stem)
            continue
        outcomes.append(OfficeActorOutcome.conflict_read(workspace_id, key))
        keys.append(key)
    return ConflictScan(keys, outcomes)


def resolve_conflict(
    store: OfficeStore,
    workspace_id: str,
    actor_key: str,
    *,
    take: str,
    updated_by: str = "operator",
    allow_class_key: bool = False,
    correlation_id: str | None = None,
    dry_run: bool = False,
) -> OfficeActor | None:
    """Resolve a realm-sync conflict sidecar for an actor. ``take=local``
    keeps the local actor; ``take=remote`` adopts the sidecar's remote copy
    (or archives the local actor for an edit-vs-remove tombstone). Always
    archives the sidecar and emits ``office.actor.conflict_resolved``.

    BOTH ``take="remote"`` arms also emit their ``office_actor`` patch — the
    adopt arm an ``upsert``, the edit-vs-remove arm the ``remove``
    ``_archive_actor_locked`` has always emitted. ``take="local"`` writes no
    row and emits none.

    Those actor rows were never the missing half. The resolution also
    ARCHIVES the conflict sidecar, which takes the key out of the office
    row's ``conflict_actor_keys``, and no ``office_actor`` patch carries that
    field (the launcher's ``_applyOfficeActorPatch`` never writes it) — so a
    covered batch would clear the desk and leave the sync strip's conflict
    pill lit for the rest of the session. **That is what
    :meth:`_emit_conflict_resolved_patch` now carries**, on all three arms,
    which is why the archive is the thing it pairs with rather than the
    write: ``take="local"`` moves the ledger and nothing else. The domain
    event is coverable from 2026-09-04 (w12/l3), gated on the client
    declaring ``office_conflict``. See ``patch_coverage`` for the ruling in
    full.

    ``allow_class_key`` is the operator's on-the-record override for the
    class-key fence below (``harness office resolve-conflict
    --allow-class-key``); see ``_guard_class_keyed_adoption``.

    Why this arm IS fenced when :meth:`adopt_remote_actor` is not, given
    that both write a peer's row into the live directory of the same
    workspace: the discriminator every fence in this store keys on is LOCAL
    AUTHORING INTENT, not the row's provenance. A pull is automatic — no
    operator, no consent to offer, and nobody to take an override — so
    fencing it would only mean refusing to hold what a peer published (the
    D3 ruling at :meth:`adopt_remote_actor`). ``resolve-conflict --take
    remote`` is the opposite case in every respect: it is an operator
    gesture whose whole content is the decision to adopt the peer's copy as
    local truth, it has an override to hand them (``allow_class_key``), and
    the refusal it can raise points at a real next move. Same input class,
    opposite dispositions, one rule."""

    take = str(take or "").strip().lower()
    if take not in {"local", "remote"}:
        raise ValueError("invalid_request")
    wsid = safe_id(workspace_id)
    if not wsid:
        raise ValueError("invalid_request")
    with office_lock(wsid):
        sidecar_path = paths.office_conflict_path(wsid, actor_key)
        if not sidecar_path.exists():
            raise SyncConflict(f"no_conflict:{actor_key}")
        sidecar = read_json(sidecar_path)
        result_actor: OfficeActor | None = None
        if take == "local":
            if store.actor_exists(wsid, actor_key):
                result_actor = store.get_actor(wsid, actor_key)
        else:  # take == remote
            remote = sidecar.get("remote_actor")
            if isinstance(remote, dict):
                actor = from_jsonable(OfficeActor, remote)
                actor.workspace_id = wsid
                actor.state = "active"
                store._guard_class_keyed_adoption(wsid, actor, allow_class_key=allow_class_key)
                actor.revision = max(int(actor.revision or 1), 1) + 1
                actor.updated_at = now()
                actor.updated_by = _safe_actor_ref(updated_by)
                result_actor = actor
                if not dry_run:
                    # ABSENCE asked under the lock that is already held for
                    # the write — the same question ``upsert_actor`` asks,
                    # and the only one the fold's insert-on-absent cares
                    # about. A resolve CAN land on an absent row: the
                    # conflict sidecar outlives an archive of its own key.
                    created = not store.actor_exists(wsid, actor.actor_key)
                    _write_actor(actor)
                    # The half this arm was missing. Its sibling one branch
                    # down archives through ``_archive_actor_locked``, which
                    # emits its remove patch even with the domain event
                    # suppressed — so a resolve that TOOK a desk away
                    # reached every live consumer and a resolve that GAVE
                    # you one reached none. Exactly the H1 asymmetry
                    # ``adopt_remote_actor`` closed for the pull lane, on
                    # the same lane, one method up. Inside the lock and
                    # before the domain event, like every other emitter in
                    # this class — see ``_emit_actor_patch``.
                    store._emit_actor_patch(
                        actor, created=created, correlation_id=correlation_id
                    )
            elif store.actor_exists(wsid, actor_key):
                # Remote removed the actor (edit-vs-remove) → archive local.
                actor = store.get_actor(wsid, actor_key)
                if not dry_run:
                    # Locked variant — see remove_actor: office_lock is not
                    # reentrant.
                    surface = store._ensure_surface_locked(
                        wsid, created_by=updated_by
                    )
                    store._archive_actor_locked(
                        surface,
                        actor,
                        reason="remote_removed",
                        updated_by=updated_by,
                        emit=False,
                        correlation_id=correlation_id,
                    )
        if dry_run:
            # take value + sidecar existence validated; return the would-be
            # resolved actor in memory. Leave the sidecar in place and emit
            # nothing (matches the real return, incl. None for edit-vs-remove).
            return result_actor
        _archive_actor_conflict_sidecar(wsid, actor_key)
        # The row the archive above moves, on ALL THREE arms — the fact that
        # kept this method's domain event uncoverable. Before the domain
        # event and inside the lock, like every emitter in this class.
        store._emit_conflict_resolved_patch(
            wsid, actor_key, correlation_id=correlation_id
        )
        store._emit(
            "office.actor.conflict_resolved",
            correlation_id,
            workspace_id=wsid,
            actor_key=actor_key,
            take=take,
            revision=getattr(result_actor, "revision", None),
        )
    return result_actor


def _guard_no_conflict(store: OfficeStore, workspace_id: str, actor_key: str) -> None:
    guard_no_conflict(paths.office_conflict_path(workspace_id, actor_key), f"actor_conflict:{actor_key}")


def _archive_actor_conflict_sidecar(workspace_id: str, actor_key: str) -> None:
    """Move an actor's resolved sidecar to ``<actor token>.resolved.json``."""
    archive_conflict_sidecar(
        paths.office_conflict_path(workspace_id, actor_key),
        paths.office_conflicts_dir(workspace_id) / f"{office_models.actor_file_token(actor_key)}.resolved.json",
        {"actor_key": actor_key},
    )
