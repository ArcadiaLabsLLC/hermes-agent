"""The persona-instance lane: the read-only wire projections (subset and full row)
and the three chokepoint emitters — patch, create, remove.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ..config import AgentRuntimeConfig, ensure_persisted_personas
from ..events import EventLog
from ..models import EVENT_PAYLOAD_LIMIT_BYTES
from .emit import delta_patches_enabled, emit_state_patch
from .models import (
    _PERSONA_INSTANCE_STORE_TO_WIRE,
    PATCH_OP_REFRESH,
    PATCH_OP_REMOVE,
    PATCH_OP_UPSERT,
    PERSONA_INSTANCE_ENTITY,
)
from .payload import _is_oversize_marker, build_state_patch

__layer__ = "stores"

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Per-entity wire projection (mirrors snapshot.py's projection, side-effect-free)
# --------------------------------------------------------------------------- #
def project_persona_instance_wire_fields(instance: Any, changed_store_fields: Iterable[str]) -> dict[str, Any]:
    """Project the wire fields a persona-instance store mutation affected.

    Computes exactly the wire fields ``persona_instance_summary`` produces for
    the changed store fields (its derived-field logic reproduced field-for-field
    — a golden in ``test_state_patches.py`` asserts byte-parity against
    ``persona_instance_summary`` for the live rows, so it can never drift). This
    is a **read-only** derivation on purpose: routing through
    ``persona_instance_summary`` for a profile instance would fall into
    ``_profile_visibility_persona`` → ``ensure_persisted_personas``, which SEEDS
    the agent store and emits a stray ``persona.updated`` into the mutation's own
    event batch (demoting a coverable batch to a full core). The persona is
    resolved read-only from ``AgentStore().list_all()``,
    neither of which writes); a profile instance whose persona is absent yields
    the same ``model=None / provider=None / skills=overrides`` fallback the
    visibility-persona standin does.
    """

    persona = _resolve_persona_for(instance)
    row = _persona_instance_wire_row(instance, persona)
    wire_fields: dict[str, Any] = {}
    for store_field in changed_store_fields:
        for wire_field in _PERSONA_INSTANCE_STORE_TO_WIRE.get(store_field, (store_field,)):
            if wire_field in row:
                wire_fields[wire_field] = row[wire_field]
    return wire_fields


def _persona_instance_wire_row(instance: Any, persona: Any) -> dict[str, Any]:
    """The subset of ``persona_instance_summary`` fields a steer/profile mutation
    can touch, derived read-only. ``persona`` is the backing agent (or None for a
    profile instance → ``model``/``provider`` default None, ``skills`` fall back
    to the instance overrides), mirroring the summary's
    ``getattr(visibility_persona, ...)`` exactly."""

    from ..persona_assignments import _model_supports_reasoning_effort

    overrides = instance.skill_overrides
    persona_model = getattr(persona, "model", None)
    persona_provider = getattr(persona, "provider", None)
    persona_skills = list(getattr(persona, "skills", []) or [])
    effective_model = instance.model or persona_model
    # ``persona_instance_summary`` derives all three profile names from this one
    # value (``instance.profile_id or visibility_persona.hermes_profile``); the
    # standin's fallback is None, mirrored here by ``getattr(persona, ...)``.
    profile_id = instance.profile_id or getattr(persona, "hermes_profile", None)
    return {
        "steered_by": list(instance.steered_by),
        "spawned_by": instance.spawned_by,
        "goal_id": instance.goal_id,
        "mode": instance.mode,
        "lifecycle_mode": instance.mode,
        "current_task_id": instance.current_task_id,
        "display_name": instance.display_name,
        "agent_profile_display_name": instance.display_name,
        "current_chat_goal": instance.current_chat_goal,
        "skill_overrides": list(overrides) if overrides is not None else None,
        "skills": list(overrides) if overrides is not None else persona_skills,
        "model": instance.model,
        "effective_model": effective_model,
        "provider": instance.provider,
        "effective_provider": instance.provider or persona_provider,
        "api_mode": instance.api_mode,
        "reasoning_effort": instance.reasoning_effort,
        "model_is_override": bool(instance.model or instance.provider or instance.reasoning_effort),
        "reasoning_supported": _model_supports_reasoning_effort(effective_model),
        # The ``open_chat`` fields. Same rule as everything above: these are the
        # WIRE names and the WIRE derivations, not the store attributes.
        "workspace_id": instance.workspace_id,
        "realm_id": instance.realm_id,
        "profile_id": profile_id,
        "backing_profile": profile_id,
        "source_profile_id": profile_id,
        "default_chat_session_id": instance.default_chat_session_id,
        "chat_session_id": instance.default_chat_session_id,
        "session_id": instance.default_chat_session_id,
        "updated_at": instance.updated_at,
    }


def _resolve_persona_for(instance: Any) -> Any:
    """The backing persona for ``instance``, resolved READ-ONLY (never seeds) and
    exactly as ``snapshot.py`` resolves it — so the projected derived fields match
    a full rebuild. A profile instance whose persona isn't a stored agent resolves
    to None (the wire-row derivation then uses the visibility-persona fallback
    values). Best-effort: any resolution failure falls back to None."""

    try:
        from ..store import AgentStore

        persona_id = str(getattr(instance, "persona_id", "") or "")
        personas = AgentStore().list_all()
        return {p.id: p for p in personas}.get(persona_id)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Chokepoint emitters (op-based; each dark unless the flag is on)
# --------------------------------------------------------------------------- #
def emit_persona_instance_patch(
    event_log: EventLog,
    instance: Any,
    changed_store_fields: Iterable[str],
    *,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit a persona-instance ``upsert`` for the wire fields a steer/profile
    write affected. Dark (and projection-free) unless the flag is on."""

    fields = list(changed_store_fields)
    if not fields:
        return False
    if not delta_patches_enabled(config):
        return False
    changed = project_persona_instance_wire_fields(instance, fields)
    if not changed:
        return False
    return emit_state_patch(
        event_log,
        entity=PERSONA_INSTANCE_ENTITY,
        entity_id=instance.id,
        op=PATCH_OP_UPSERT,
        changed=changed,
        task_id=getattr(instance, "current_task_id", None),
        run_id=getattr(instance, "active_run_id", None),
        persona_id=getattr(instance, "persona_id", None),
        config=config,
    )


def project_persona_instance_full_wire_row(instance: Any) -> dict[str, Any]:
    """The COMPLETE persona-instance wire row — the exact row a full core holds.

    This is the create half of the projection pair, and it is deliberately a
    different mechanism from :func:`project_persona_instance_wire_fields` above.
    That one reproduces ``persona_instance_summary``'s derived-field logic
    field-for-field (held to it by a golden) because it only ever needs the
    SUBSET a steer/profile write moved, and reproducing a subset read-only is
    cheaper than building the whole row. A create has no subset: the client holds
    no row at all, so the patch must carry every key the rebuild would, and the
    only thing that can promise that is the rebuild's own builder. So this one
    CALLS ``persona_instance_summary`` — the same structural-parity argument
    :func:`project_office_actor_wire_row` makes, and the stronger of the two: a
    field added to the summary reaches the create patch in the same commit and
    cannot drift out of it.

    The persona is resolved READ-ONLY through :func:`_resolve_persona_for`, and
    handed to the summary rather than left for it to look up — the same resolution
    ``snapshot.py`` performs (``personas_by_id.get(persona_id)``), so a profile
    instance whose persona is not a stored agent resolves to ``None`` HERE too and
    falls into the summary's own ``_profile_visibility_persona`` standin exactly
    as the full rebuild does. Byte-parity with the core needs that fallback to
    stay in play, not to be routed around.

    ``profile_readiness`` is not threaded: ``snapshot.py`` passes it, but it feeds
    only ``tool_resolution``'s ``profile_readiness``/``..._summary`` keys, and the
    summary row copies none of those out — it reads ``permission_mode``,
    ``mutation_boundary``, ``final_tool_count``, ``blocked_tools`` and
    ``effective_toolsets``. Omitting it costs one recomputation inside
    ``resolve_tool_visibility`` and moves no wire byte; the parity golden in
    ``test_state_patches.py`` is what holds that claim.
    """

    from ..agent_create_phases import timed_create_subphase
    from ..persona_assignments import persona_instance_summary

    # W3-H1: the projection alone, so the create receipt can separate it from
    # the ``state.patched`` append that ``emit_persona_instance_create`` performs
    # around it. Free for every other caller — see ``timed_create_subphase``.
    with timed_create_subphase("wire_row_ms"):
        return persona_instance_summary(
            instance, _resolve_persona_for(instance), roster=ensure_persisted_personas
        )


def emit_persona_instance_create(
    event_log: EventLog,
    instance: Any,
    *,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit the CREATE patch for a brand-new persona instance: a complete-row
    ``upsert`` stamped ``created: true`` — or an honest ``refresh`` if that row
    cannot be carried losslessly (D3, 2026-08-16).

    Why this exists. ``open_chat``'s create arm emitted ``op: refresh``, and one
    unfoldable row demotes its whole batch, so every Mission Office "add an
    agent" gesture took the perfectly foldable ``office_actor created:true``
    upsert down with it and paid a full ``build_snapshot()`` — measured at 6.3–6.6
    s of a 6.94 s gesture (plan §10.1). The refresh was not a measurement, it was
    a deferral: the ~18 KB figure in this module's header predates the R2
    residue slimming that evicted the tool-detail payloads (~97% of the row)
    behind ``visibility_ref``. Measured on the operator's live roster, 2026-08-16:
    17 instances, worst assembled payload 3,133 bytes against the 4,096-byte cap,
    worst single value 504 bytes against the 3,584-byte per-value budget.

    Why the degrade is checked HERE rather than left to
    :func:`build_state_patch`'s shrink loop. That loop is right for a SUBSET
    upsert: marking one oversize value still ships a merge the launcher can apply,
    with the marked field accounted and refetched. For a CREATE it would be a
    lie — the launcher INSERTS this row wholesale, so a marker would become the
    inserted row's value for that field, i.e. a fabricated roster row rather than
    an accounted degrade. So a create is all-or-nothing: any marker, or any
    degrade the loop already made, and the whole patch becomes the ``refresh``
    that was the pre-D3 behaviour. That keeps the worst case exactly today's
    wire — a full core — for a roster row that outgrows the cap, instead of a
    silently corrupt insert.

    Dark (and projection-free) unless the flag is on.
    """

    if not delta_patches_enabled(config):
        return False
    row = project_persona_instance_full_wire_row(instance)
    payload = build_state_patch(
        PERSONA_INSTANCE_ENTITY, instance.id, PATCH_OP_UPSERT, row, True
    )
    lossless = payload.get("op") == PATCH_OP_UPSERT and not any(
        _is_oversize_marker(value)
        for value in (payload.get("changed") or {}).values()
    )
    if not lossless:
        logger.warning(
            "persona-instance create patch degraded to refresh: the projected "
            "row for %s does not fit the %d-byte payload cap losslessly — the "
            "batch takes a full core (D3, plan §10.3)",
            instance.id,
            EVENT_PAYLOAD_LIMIT_BYTES,
        )
        return emit_state_patch(
            event_log,
            entity=PERSONA_INSTANCE_ENTITY,
            entity_id=instance.id,
            op=PATCH_OP_REFRESH,
            persona_id=getattr(instance, "persona_id", None),
            config=config,
        )
    return emit_state_patch(
        event_log,
        entity=PERSONA_INSTANCE_ENTITY,
        entity_id=instance.id,
        op=PATCH_OP_UPSERT,
        changed=row,
        created=True,
        task_id=getattr(instance, "current_task_id", None),
        run_id=getattr(instance, "active_run_id", None),
        persona_id=getattr(instance, "persona_id", None),
        config=config,
    )


def emit_persona_instance_remove(
    event_log: EventLog,
    instance: Any,
    *,
    config: AgentRuntimeConfig | None = None,
) -> bool:
    """Emit a persona-instance ``remove`` (the instance left the active frame —
    a close / task-terminal fan-out). Dark unless the flag is on.

    Takes no ``reason``: ``emit_state_patch`` has no field to carry one, so the
    kwarg this used to accept was computed by its caller and discarded. The
    WHY travels on the paired domain event, which does have a place for it."""

    if not delta_patches_enabled(config):
        return False
    return emit_state_patch(
        event_log,
        entity=PERSONA_INSTANCE_ENTITY,
        entity_id=instance.id,
        op=PATCH_OP_REMOVE,
        task_id=getattr(instance, "current_task_id", None),
        persona_id=getattr(instance, "persona_id", None),
        config=config,
    )
