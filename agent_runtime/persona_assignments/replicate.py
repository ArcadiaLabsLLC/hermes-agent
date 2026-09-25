"""The realm-sync replication door onto the roster: mint or refresh a replicated
instance from a peer's row (only the travel allowlist crosses), retire a
replica, and apply a peer's steering edges (cycle-validated like a local edit).

Functions over a ``PersonaInstanceStore`` (composition — the class binds each
one as a method, so ``store.replicate_instance(...)`` reads as before).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from hermes_time import now

from agent_runtime import paths
from agent_runtime.config.roster import ensure_persisted_personas
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments.errors import PersonaInstanceRetireError
from agent_runtime.persona_assignments.identity import (
    _coerce_travel_value,
    _durable_chat_root,
    _MISSING_TRAVEL_FIELD,
    _profile_id_for_persona_or_template,
    _role_for_persona_or_template,
    is_canonical_persona_channel,
    persona_chat_session_id_for,
)
from agent_runtime.serde import dedupe_tokens, safe_assignment_text, safe_optional_token
from agent_runtime.state_patches.persona_instance import (
    emit_persona_instance_create,
    emit_persona_instance_patch,
    emit_persona_instance_remove,
)
from agent_runtime.states import WorkerSessionState

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "_replica_row",
    "apply_replicated_steering",
    "replicate_instance",
    "retire_replica",
]


def replicate_instance(
    store: PersonaInstanceStore,
    body: dict[str, Any],
    *,
    realm_id: str,
    adopt_existing: PersonaInstance | None = None,
) -> PersonaInstance:
    """THE door a realm pull writes a replicated agent through.

    A replication mint is a **THIRD intent class** (plan §3.5). It is not
    AUTHORED — no operator clicked on this machine, so it must not produce
    the receipts an authored create produces — and it is not DIAGNOSTIC — it
    is not a repair of a local projection against a local truth, but the
    arrival of a peer's authored fact. So it gets its own verb here and its
    own event type (``persona_instance.replicated``), rather than reusing
    ``_mint_instance``: ``persona_instance.created`` means "this machine
    authored an agent" to every consumer that reads it, and one pull would
    otherwise look like N creates in the log an operator greps.

    Why a STORE DOOR and not a raw ``persona_instances/`` write in the
    applier. Three facts are store-level and all three would be lost:

    * the DELTA PATCH. This is the one place not to repeat a mistake made
      one lane over three days ago — ``apply_board_pull`` writes cards with
      raw atomic writes, so a pull that GIVES you a card reaches no live
      consumer while one that ARCHIVES a card emits (open queue row). A
      replicated instance that needs an app restart to appear has not been
      replicated as far as the operator is concerned.
    * the §1.3 DERIVATIONS. ``role`` / ``profile_id`` / ``runtime_root`` /
      ``state`` / the durable chat root are this machine's answers, and an
      applier deriving them would be a second authority over what a
      persona-instance row means.
    * the EVENT-then-patch ordering the rest of this store keeps.

    ``adopt_existing`` is the ADOPT arm: the row is already here and only
    the travelling surface moves. Every §1.2 field on it is preserved
    BY CONSTRUCTION — the arm copies the existing record and writes only
    allowlisted keys onto it — so this door cannot express "adopt a live
    binding" even by mistake.

    No tombstone is minted here, ever: nothing is being deleted. No office
    write happens here either — the desk arrived through its own lane, and
    writing it again would be a second authority over one row.
    """

    from ..persona_instance_sync import (
        PERSONA_INSTANCE_ALLOWED_KEYS,
        cleared_travel_value,
    )

    instance_id = str(body["id"])
    persona_id = str(body["persona_id"])
    if adopt_existing is not None:
        instance = replace(adopt_existing)
        created = False
    else:
        instance = store._replica_row(instance_id, persona_id, body)
        created = True

    # The travelling SURFACE, wholesale. A key the publisher cleared clears
    # here too — a locally stale override that outlived the upstream write
    # removing it is the same clobber class the record split exists to end.
    # ``steered_by`` is deliberately NOT applied here: the edges are phase
    # two (plan §3.4), because an edge may name a parent this pass has not
    # minted yet.
    for name in sorted(PERSONA_INSTANCE_ALLOWED_KEYS - {"id", "persona_id", "steered_by"}):
        value = body.get(name, _MISSING_TRAVEL_FIELD)
        if value is _MISSING_TRAVEL_FIELD:
            value = cleared_travel_value(name)
        setattr(instance, name, _coerce_travel_value(name, value))
    instance.updated_at = now()

    store._write(instance)
    if created:
        emit_persona_instance_create(store.event_log, instance)
    else:
        emit_persona_instance_patch(
            store.event_log,
            instance,
            [*sorted(PERSONA_INSTANCE_ALLOWED_KEYS - {"id", "persona_id"}), "updated_at"],
        )
    # ``source``/``realm_id`` on the payload: the ``updated_by="realm_sync"``
    # precedent, so an operator reading the log can tell a peer's arrival
    # from their own click without joining against anything.
    store._event(
        "persona_instance.replicated",
        instance,
        {
            "source": "realm_sync",
            "realm_id": str(realm_id),
            "action": "replicated" if created else "adopted",
        },
    )
    return instance


def _replica_row(store: PersonaInstanceStore, instance_id: str, persona_id: str, body: dict[str, Any]) -> PersonaInstance:
    """A brand-new replica's LOCAL half — plan §1.3, derived, never carried.

    ``role`` and ``profile_id`` come from the persona definition that
    arrived in the SAME pull (the applier runs after
    ``apply_persona_config_pull`` for exactly this reason); travelling them
    would let a stale copy shadow the definition beside it. The chat root is
    minted fresh AND MADE DURABLE before the bind — a pointer that travelled
    would resolve to a SessionDB row the receiver does not have, which is
    precisely the ``unknown_chat_session`` defect ``_durable_chat_root`` was
    written to retire. A failure there RAISES, so the applier refuses this
    row and keeps pulling rather than binding a root it did not persist.
    """

    display_name = safe_assignment_text(body.get("display_name"), limit=120)
    return PersonaInstance(
        id=instance_id,
        persona_id=persona_id,
        role=str(_role_for_persona_or_template(persona_id, ensure_persisted_personas) or ""),
        display_name=display_name,
        profile_id=_profile_id_for_persona_or_template(persona_id, ensure_persisted_personas),
        runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE,
        default_chat_session_id=_durable_chat_root(
            persona_chat_session_id_for(instance_id),
            persona_id=persona_id,
            display_name=display_name,
        ),
        updated_at=now(),
    )


def retire_replica(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    *,
    reason: str = "remote_removed",
    realm_id: str | None = None,
) -> dict[str, Any]:
    """Archive a replicated row when its DESK left — plan §5.2, nothing else.

    Two things this deliberately does NOT do, and both are the point:

    * **It runs no office half.** :meth:`retire` calls
      ``_archive_office_placements``, which archives through
      ``remove_actor``'s DEFAULT ``record_tombstone=True`` — a realm-visible
      ledger entry. Here the authored tombstone already exists upstream, and
      the pull's own office lane has already archived the local desk that
      triggered this, so minting a second one is the duplicate-authority
      defect §5.2 forbids. That is what "``record_tombstone=False``
      semantics" MEANS for this family: a persona-instance row has no
      realm-visible ledger of its own, so withholding the office write is
      the whole of it.
    * **It mints no tombstone of any kind.** Nothing in the replication lane
      ever does. The row MOVES to the archive (archive-never-delete) and the
      projection stops listing it, exactly as :meth:`retire` does.

    Refuses typed — never silently — on the two guards :meth:`retire`
    carries: a canonical channel (which never replicates at all, so reaching
    this door with one is a caller bug worth naming) and a LIVE run binding.
    A working agent is never archived; the pull accounts it as held and
    re-decides next pass, the "keep the baseline, retry" repair
    ``_reconcile_actors`` already uses one lane over.
    """

    instance = store.get(persona_instance_id)
    if is_canonical_persona_channel(instance):
        raise PersonaInstanceRetireError(
            "canonical_persona_channel",
            f"{instance.id} is a canonical persona channel and never replicates",
            persona_instance_id=instance.id,
            detail={"persona_id": instance.persona_id},
        )
    if store._has_live_binding(instance):
        raise PersonaInstanceRetireError(
            "instance_active",
            f"{instance.id} has a live run binding; never archive a working agent",
            persona_instance_id=instance.id,
            detail={"active_run_id": safe_optional_token(instance.active_run_id)},
        )

    archive_dir = (
        paths.persona_instances_archive_dir()
        / f"{now().strftime('%Y%m%dT%H%M%SZ')}_replica_retire"
    )
    archived_path = store._archive_instance_row(instance, archive_dir)
    if archived_path is None:
        raise PersonaInstanceRetireError(
            "not_found",
            f"persona instance row is not on disk: {instance.id}",
            persona_instance_id=instance.id,
        )
    payload: dict[str, Any] = {
        "reason": safe_assignment_text(reason, limit=240) or "remote_removed",
        "persona_id": instance.persona_id,
        "mode": instance.mode,
        "archive_dir": str(archive_dir),
        "source": "realm_sync",
    }
    if realm_id:
        payload["realm_id"] = str(realm_id)
    store._event("persona_instance.retired", instance, payload)
    emit_persona_instance_remove(store.event_log, instance)
    return {
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "archive_path": str(archived_path),
        "archive_dir": str(archive_dir),
    }


def apply_replicated_steering(
    store: PersonaInstanceStore, persona_instance_id: str, parents: list[str], *, realm_id: str
) -> tuple[list[str], list[dict[str, str]]]:
    """Phase TWO of the mint (plan §3.4): the authored steering edges.

    Returns ``(applied, dropped)``. An edge whose target is still absent
    after phase one is DROPPED with a typed row, never silently — the target
    may be a row this realm never published, or one whose own admission was
    refused. ``_validate_no_steering_cycle`` runs per edge, so a hostile or
    corrupt remote graph cannot install a cycle even though every edge in it
    passed the content door.
    """

    applied: list[str] = []
    dropped: list[dict[str, str]] = []
    for parent in dedupe_tokens(parents):
        if parent == persona_instance_id:
            dropped.append({"parent": parent, "reason": "self_edge"})
            continue
        if not paths.persona_instance_path(parent).exists():
            dropped.append({"parent": parent, "reason": "parent_absent"})
            continue
        try:
            store._validate_no_steering_cycle(persona_instance_id, parent)
        except Exception as exc:  # noqa: BLE001 — accounted, never silent
            dropped.append({"parent": parent, "reason": type(exc).__name__})
            continue
        applied.append(parent)
    try:
        instance = store.get(persona_instance_id)
    except Exception as exc:  # noqa: BLE001 — the row went away under us
        dropped.append({"parent": "", "reason": type(exc).__name__})
        return [], dropped
    if list(instance.steered_by) == applied:
        return applied, dropped
    instance.steered_by = applied
    instance.updated_at = now()
    store._write(instance)
    emit_persona_instance_patch(store.event_log, instance, ["steered_by", "updated_at"])
    store._event(
        "persona_instance.replicated",
        instance,
        {
            "source": "realm_sync",
            "realm_id": str(realm_id),
            "action": "steered",
            "steered_by": list(applied),
        },
    )
    return applied, dropped
