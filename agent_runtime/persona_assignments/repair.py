"""Roster repairs: steering edges that name a non-instance token or a missing
instance, and chat bindings whose session no longer exists in the session DB.

Functions over a ``PersonaInstanceStore`` (composition — the class binds each
one as a method).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_runtime.models import looks_like_persona_instance_id
from agent_runtime.persona_assignments.scan import (
    _session_presence_probe,
    PersonaScanRefusal,
)
from agent_runtime.persona_assignments.vocabulary import _BINDING_REPAIR_REASON
from agent_runtime.serde import safe_assignment_text, safe_optional_token

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "repair_missing_chat_session_bindings",
    "repair_missing_steering_references",
    "repair_non_instance_steering",
]


def repair_non_instance_steering(
    store: PersonaInstanceStore,
    persona_instance_id: str | None = None,
    *,
    apply: bool = True,
) -> dict[str, Any]:
    """Strip non-instance principals out of steering fields (evented, dry-run aware).

    A steering-parent SET (``steered_by``) and its mirror (``spawned_by``)
    may hold ONLY persona-instance ids. A legacy mint seeded the operator
    principal into them (``steered_by=["operator"]`` / ``spawned_by=
    "operator"``), which the HUD then rendered as a phantom "steered by
    operator" edge. This removes the non-instance entries surgically:

    - ``steered_by`` keeps only its instance-shaped parents;
    - a NON-instance ``spawned_by`` is re-pointed at the surviving primary
      parent (``steered_by[0]``) when one remains, else cleared — restoring
      the mirror invariant. An already instance-shaped ``spawned_by`` is left
      untouched (the ``__post_init__`` backfill self-heals it into a bare
      ``steered_by``), so a valid parent is never destroyed.

    Everything else on the row (mode, goal, session) is untouched — this is a
    steering repair, not a detach. Honors dry-run: with ``apply=False``
    nothing is written and no event is emitted (the on-disk row stays
    byte-identical); with ``apply=True`` each repaired row goes through the
    single steer write path (``_commit_steer`` → one
    ``persona_instance.steered`` event + state patch).
    ``persona_instance_id`` targets one row; ``None`` scans every row.
    """
    targets = (
        [store.get(persona_instance_id)]
        if persona_instance_id
        else store.list_all()
    )
    repairs: list[dict[str, Any]] = []
    for instance in targets:
        steered_before = list(instance.steered_by)
        kept = [p for p in steered_before if looks_like_persona_instance_id(p)]
        bogus_steered = [p for p in steered_before if not looks_like_persona_instance_id(p)]
        spawned = instance.spawned_by
        bogus_spawn = (
            spawned
            if (spawned and not looks_like_persona_instance_id(spawned))
            else None
        )
        if not bogus_steered and bogus_spawn is None:
            continue
        updates: dict[str, Any] = {"steered_by": kept}
        # Only rewrite the mirror when it is itself bogus; re-point it at the
        # surviving primary, or clear it when no instance parent remains.
        desired_spawn = spawned
        if bogus_spawn is not None:
            desired_spawn = kept[0] if kept else None
            updates["spawned_by"] = desired_spawn
        record = {
            "persona_instance_id": instance.id,
            "steered_by_before": steered_before,
            "steered_by_after": kept,
            "spawned_by_before": spawned,
            "spawned_by_after": desired_spawn,
            "removed_steered_by": bogus_steered,
            "removed_spawned_by": bogus_spawn,
        }
        repairs.append(record)
        if not apply:
            continue
        store._commit_steer(
            instance,
            updates,
            added=[],
            removed=bogus_steered,
            detached=not kept,
        )
    return {
        "applied": bool(apply),
        "dry_run": not apply,
        "repaired": repairs,
        "repaired_count": len(repairs),
    }


def repair_missing_steering_references(
    store: PersonaInstanceStore,
    *,
    apply: bool = True,
) -> dict[str, Any]:
    """Remove steering parents that no longer resolve to a live instance.

    JSON shape validation cannot catch a syntactically valid id whose row
    has been retired or reaped. This is the referential-integrity repair:
    it preserves every live parent and all child context, rewrites the
    ``spawned_by`` mirror, and emits the ordinary steering event when
    applied. Dry-run is side-effect free.

    REFUSES, whole, when any instance row will not decode. ``live_ids`` is
    this repair's entire notion of what exists, and it is derived by
    SUBTRACTION: a parent id absent from it is stripped from its child as
    dangling. An unreadable row is absent from it for a reason that has
    nothing to do with the parent being gone — so under the short list every
    child edge naming that row is destroyed, and the strip is a delete-shaped
    write minted out of a parse error. There is no partial answer available
    here the way there is for a per-workspace office publish: one unreadable
    row poisons the membership question for EVERY child at once, because the
    set is what the predicate tests against. So the refusal is the whole
    sweep, it writes nothing, and it says how many rows it could not read.
    """
    scan = store.scan_all()
    refusal = PersonaScanRefusal.for_scan("persona_instances", scan.unreadable)
    if refusal is not None:
        return {
            "applied": False,
            "dry_run": not apply,
            "refused": refusal.as_dict(),
            "repaired": [],
            "repaired_count": 0,
        }
    instances = scan.instances
    live_ids = {instance.id for instance in instances}
    repairs: list[dict[str, Any]] = []
    for instance in instances:
        before = list(instance.steered_by)
        kept = [parent for parent in before if parent in live_ids]
        missing = [parent for parent in before if parent not in live_ids]
        spawned_before = instance.spawned_by
        spawned_missing = bool(
            spawned_before
            and looks_like_persona_instance_id(spawned_before)
            and spawned_before not in live_ids
        )
        if not missing and not spawned_missing:
            continue
        spawned_after = kept[0] if kept else None
        repairs.append(
            {
                "persona_instance_id": instance.id,
                "steered_by_before": before,
                "steered_by_after": kept,
                "spawned_by_before": spawned_before,
                "spawned_by_after": spawned_after,
                "missing_parent_ids": sorted(set(missing + ([spawned_before] if spawned_missing else []))),
            }
        )
        if not apply:
            continue
        store._commit_steer(
            instance,
            {"steered_by": kept, "spawned_by": spawned_after},
            added=[],
            removed=missing,
            detached=not kept,
        )
    return {
        "applied": bool(apply),
        "dry_run": not apply,
        # Additive and uniform across both arms, so a consumer reads one
        # shape: ``None`` is the positive statement "the whole store was
        # readable", never the absence of an answer.
        "refused": None,
        "repaired": repairs,
        "repaired_count": len(repairs),
    }


def repair_missing_chat_session_bindings(
    store: PersonaInstanceStore,
    *,
    apply: bool = True,
    session_db: Any | None = None,
) -> dict[str, Any]:
    """Clear chat-session bindings whose session SessionDB no longer has.

    A persona instance can outlive its chat: the operator deletes the
    conversation through a path that does not own the instance store (the
    generic ``hermes sessions delete``, a gateway/web delete, a scrub), and
    the pointer is left dangling. The snapshot's persona-chat projection is
    READ-ONLY, so it can only hide the row and account a ``session_not_in_db``
    drop — one permanent parity anomaly per orphan, forever. This is the
    write-path repair that retires them.

    Fail-safe by construction:

    * a binding is cleared ONLY on a positive "absent" answer from a
      positively-enumerating SessionDB; an unavailable, unreadable or empty
      database repairs nothing at all (see :func:`_session_presence_probe`),
      because a blind read must never reap a live pointer;
    * ``task_bound`` instances are skipped entirely — a mission turn runs in
      a session that lives in the run/event stream and is legitimately absent
      from the operator SessionDB;
    * an instance with a live worker/run binding is held;
    * ``apply=False`` is a pure report: no writes, no events.
    """

    probe, skip_reason = _session_presence_probe(session_db)
    if probe is None:
        return {
            "applied": False,
            "dry_run": not apply,
            "skipped": skip_reason,
            "repaired": [],
            "repaired_count": 0,
            "held": [],
            "held_count": 0,
        }

    repairs: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for instance in store.list_all():
        pointers = {
            safe_assignment_text(instance.default_chat_session_id, limit=200),
            safe_assignment_text(instance.session_id, limit=200),
        }
        # Legacy rows may persist either pointer as an empty string. That is
        # already the absence of a binding, not a session id to probe. Keep
        # dry-run and apply on the same candidate set: before this filter a
        # dry-run reported a repair for ``""`` while apply delegated to
        # ``clear_chat_session_binding``, which correctly rejected the empty
        # target and wrote nothing.
        pointers = {pointer for pointer in pointers if pointer}
        if not pointers:
            continue
        if (instance.mode or "").lower() == "task_bound" or safe_optional_token(
            instance.current_task_id
        ):
            # Mission sessions live in the run/event stream, not SessionDB.
            continue
        missing = sorted(session_id for session_id in pointers if probe(session_id) == "absent")
        if not missing:
            continue
        if store._has_live_binding(instance):
            held.extend(
                {
                    "persona_instance_id": instance.id,
                    "persona_id": instance.persona_id,
                    "session_id": session_id,
                    "reason": "active-binding",
                }
                for session_id in missing
            )
            continue
        for session_id in missing:
            if not apply:
                repairs.append(
                    {
                        "persona_instance_id": instance.id,
                        "persona_id": instance.persona_id,
                        "session_id": session_id,
                        "cleared_fields": [
                            field_name
                            for field_name, value in (
                                ("default_chat_session_id", instance.default_chat_session_id),
                                ("session_id", instance.session_id),
                            )
                            if safe_assignment_text(value, limit=200) == session_id
                        ],
                        "reason": _BINDING_REPAIR_REASON,
                    }
                )
                continue
            record = store.clear_chat_session_binding(
                instance,
                session_id=session_id,
                reason=_BINDING_REPAIR_REASON,
            )
            if record is not None:
                repairs.append(record)
    return {
        "applied": bool(apply),
        "dry_run": not apply,
        "repaired": repairs,
        "repaired_count": len(repairs),
        "held": held,
        "held_count": len(held),
    }
