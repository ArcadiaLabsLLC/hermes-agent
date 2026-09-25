"""The profile lane: the instance model/skills/effort override write
(``update_profile``) and the backing-profile rebind. Validation helpers live in
``profile`` (policy); this module is the write side.

Functions over a ``PersonaInstanceStore`` (composition — the class binds each
one as a method).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from hermes_time import now

from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments.errors import StaleModelOverrideWrite
from agent_runtime.persona_assignments.profile import (
    _as_utc,
    _normalize_reasoning_effort_override,
    _safe_model_override_text,
    _safe_skill_overrides,
)
from agent_runtime.serde import safe_assignment_text, safe_optional_token

if TYPE_CHECKING:
    from agent_runtime.persona_assignments.store import PersonaInstanceStore

__layer__ = "stores"

__all__ = [
    "set_backing_profile",
    "update_profile",
]


def update_profile(
    store: PersonaInstanceStore,
    persona_instance_id: str,
    *,
    display_name: str | None = None,
    current_chat_goal: str | None = None,
    goal_id: str | None = None,
    skills: list[str] | None = None,
    clear_skills: bool = False,
    inherit_skills: bool = False,
    provider: str | None = None,
    model: str | None = None,
    api_mode: str | None = None,
    reasoning_effort: str | None = None,
    clear_model_override: bool = False,
    model_issued_at: datetime | None = None,
    requested_by: str | None = None,
) -> PersonaInstance:
    """Persist operator-editable runtime profile overrides.

    These fields belong to the durable persona instance, not the backing
    Hermes profile template. Editing ``Alice Agent`` therefore updates the
    live ``personainst_*`` record while leaving the lower ``alice`` profile
    untouched for future default instances.

    ``provider``/``model``/``api_mode`` form the instance model-override
    tier (None = inherit the backing persona live; see
    ``models.apply_instance_model_overrides``). ``clear_model_override``
    resets all three. A ``model_issued_at`` older than the last applied
    model write raises :class:`StaleModelOverrideWrite` instead of
    clobbering the newer value.

    **The skills lane is a TRI-state, and all three values are reachable
    from here** (operator ruling 2026-09-03). ``skill_overrides`` has meant
    three different things since the tier shipped, but only two of them had
    a door:

    =====================  ==========================================
    ``skill_overrides``    what the resolver does
    =====================  ==========================================
    a non-empty list       use exactly this set
    ``[]``                 use NO skills — an explicit, pinned empty
    ``None``               FOLLOW THE TEMPLATE, live, forever after
    =====================  ==========================================

    ``skills=`` writes the first, ``clear_skills`` writes the second, and
    until this arm existed nothing wrote the third — so one Save at "this
    agent" scope pinned that agent off its persona permanently, and the
    template tier made that worse in proportion to its use: "fix the persona
    and let the existing agents follow" silently skipped every agent the
    Skills sheet had ever touched. ``inherit_skills`` is the missing arm.

    It is a SEPARATE argument rather than a third value on ``clear_skills``
    or a ``skills=None`` sentinel, and that is the ruling rather than a
    taste call. ``skills=None`` already means "the caller expressed no
    opinion" throughout this method and every one of its callers
    (``hermes_cli.flag_binding.list_flag_or_absent`` exists to keep it that
    way, after an empty-list collapse silently erased skill sets), so
    overloading it would put the tri-state's third value on the one spelling
    that must keep meaning "untouched". The three are therefore mutually
    exclusive and a caller that asks for two gets a ``ValueError`` rather
    than a precedence rule nobody can see in the argv.
    """
    if inherit_skills and (clear_skills or skills is not None):
        raise ValueError("inherit_skills conflicts with skills/clear_skills")
    instance = store.get(persona_instance_id)
    before_patch_fields = store._profile_patch_snapshot(instance)
    if clear_model_override and any(value is not None for value in (provider, model, api_mode, reasoning_effort)):
        raise ValueError("clear_model_override conflicts with provider/model/api_mode/reasoning_effort values")
    changed = _apply_model_lane(
        instance,
        provider=provider,
        model=model,
        api_mode=api_mode,
        reasoning_effort=reasoning_effort,
        clear_model_override=clear_model_override,
        model_issued_at=model_issued_at,
    )
    changed |= _apply_chat_fields(
        instance, display_name=display_name, current_chat_goal=current_chat_goal, goal_id=goal_id
    )
    changed |= _apply_skills_lane(
        instance, skills=skills, clear_skills=clear_skills, inherit_skills=inherit_skills
    )
    if changed:
        _commit_profile_update(store, instance, before_patch_fields, requested_by=requested_by)
    return store.get(instance.id)


def _apply_model_lane(
    instance: PersonaInstance,
    *,
    provider: str | None,
    model: str | None,
    api_mode: str | None,
    reasoning_effort: str | None,
    clear_model_override: bool,
    model_issued_at: datetime | None,
) -> bool:
    """The instance model-override tier: refuse a stale write, then clear or set.

    Returns whether the row changed; a change re-stamps
    ``model_override_issued_at`` so an older write can be refused later.
    """
    touched = clear_model_override or any(
        value is not None for value in (provider, model, api_mode, reasoning_effort)
    )
    if not touched:
        return False
    if model_issued_at is not None and instance.model_override_issued_at is not None:
        issued = _as_utc(model_issued_at)
        applied = _as_utc(instance.model_override_issued_at)
        if issued <= applied:
            raise StaleModelOverrideWrite(instance, issued_at=issued, applied_issued_at=applied)
    if clear_model_override:
        changed = _clear_model_override(instance)
    else:
        changed = _set_model_override(
            instance, provider=provider, model=model, api_mode=api_mode, reasoning_effort=reasoning_effort
        )
    if changed:
        instance.model_override_issued_at = _as_utc(model_issued_at) if model_issued_at is not None else now()
    return changed


def _clear_model_override(instance: PersonaInstance) -> bool:
    if (
        instance.model is None
        and instance.provider is None
        and instance.api_mode is None
        and instance.reasoning_effort is None
    ):
        return False
    instance.model = None
    instance.provider = None
    instance.api_mode = None
    instance.reasoning_effort = None
    return True


def _set_model_override(
    instance: PersonaInstance,
    *,
    provider: str | None,
    model: str | None,
    api_mode: str | None,
    reasoning_effort: str | None,
) -> bool:
    changed = False
    for field_name, raw in (("provider", provider), ("model", model), ("api_mode", api_mode)):
        if raw is None:
            continue
        value = _safe_model_override_text(raw, field_name=field_name)
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed = True
    # Reasoning effort rides the model lane but is a validated enum
    # (or "none"/empty-clear), not free text — normalize separately.
    if reasoning_effort is not None:
        new_reasoning = _normalize_reasoning_effort_override(reasoning_effort)
        if instance.reasoning_effort != new_reasoning:
            instance.reasoning_effort = new_reasoning
            changed = True
    return changed


def _apply_chat_fields(
    instance: PersonaInstance,
    *,
    display_name: str | None,
    current_chat_goal: str | None,
    goal_id: str | None,
) -> bool:
    """The display name, the chat goal and the goal pointer (which also becomes
    the current task when it names one)."""
    changed = False
    if display_name is not None:
        value = safe_assignment_text(display_name, limit=120)
        if not value:
            raise ValueError("display_name must not be empty")
        if instance.display_name != value:
            instance.display_name = value
            changed = True
    if current_chat_goal is not None:
        value = safe_assignment_text(current_chat_goal, limit=500) or None
        if instance.current_chat_goal != value:
            instance.current_chat_goal = value
            changed = True
    if goal_id is not None:
        value = safe_optional_token(goal_id)
        if instance.goal_id != value:
            instance.goal_id = value
            changed = True
        if value and instance.current_task_id != value:
            instance.current_task_id = value
            changed = True
    return changed


def _apply_skills_lane(
    instance: PersonaInstance,
    *,
    skills: list[str] | None,
    clear_skills: bool,
    inherit_skills: bool,
) -> bool:
    """The skills tri-state (see :func:`update_profile`'s table)."""
    if skills is None and not clear_skills and not inherit_skills:
        return False
    # ``None`` is the third value, not the absence of one — see the
    # tri-state table above. The comparison is deliberately ``!=`` on
    # the raw attribute so ``[] -> None`` registers as a change: those
    # two resolve to different skill sets the moment the template holds
    # anything, and reading them as equal would make the inherit door a
    # silent no-op for exactly the agents that need it.
    value = None if inherit_skills else ([] if clear_skills else _safe_skill_overrides(skills or []))
    if instance.skill_overrides == value:
        return False
    instance.skill_overrides = value
    return True


def _commit_profile_update(
    store: PersonaInstanceStore,
    instance: PersonaInstance,
    before_patch_fields: dict[str, Any],
    *,
    requested_by: str | None,
) -> None:
    """Write the row, append ``persona_instance.profile_updated``, and emit the
    S6 patch of exactly the fields this call moved."""
    instance.updated_at = now()
    store._write(instance)
    payload: dict[str, Any] = {
        "display_name": instance.display_name,
        "current_chat_goal": instance.current_chat_goal,
        "goal_id": instance.goal_id,
        # ``None`` travels as ``None``: the event's reader cannot tell
        # "pinned to no skills" from "follows the template" if the two
        # are spelled the same, and after ``--inherit-skills`` both
        # states are reachable through this one verb.
        "skill_overrides": (
            list(instance.skill_overrides) if instance.skill_overrides is not None else None
        ),
        "provider": instance.provider,
        "model": instance.model,
        "api_mode": instance.api_mode,
        "reasoning_effort": instance.reasoning_effort,
    }
    if requested_by:
        payload["requested_by"] = str(requested_by)[:80]
    store._event("persona_instance.profile_updated", instance, payload)
    # S6 producer: the persona-instance profile/model write funnel. Emit
    # only the operator-editable fields this call actually changed. Live
    # unless read_model.delta_patches is explicitly off (it ships on).
    after_patch_fields = store._profile_patch_snapshot(instance)
    store._emit_state_patch(
        instance,
        {
            field_name: after_patch_fields[field_name]
            for field_name in after_patch_fields
            if after_patch_fields[field_name] != before_patch_fields.get(field_name)
        },
    )


def set_backing_profile(store: PersonaInstanceStore, persona_instance_id: str, profile_id: str | None) -> PersonaInstance:
    """Re-point one instance's ``profile_id`` at a new backing Hermes profile.

    Deliberately NOT part of :meth:`update_profile`: everything that method
    writes is an operator-editable RUNTIME override that belongs to the
    instance. ``profile_id`` is not — it is a PROJECTION of the owning
    persona's ``hermes_profile``. Folding it into ``update_profile`` would
    create a second, instance-local rebind authority competing with the
    persona record.

    The ONE sanctioned caller is
    :func:`agent_runtime.persona_profile_binding.rebind_persona_profile`,
    which moves the persona authority and cascades every instance row in the
    same operation, refuses while any instance is in flight, and emits the
    single typed ``persona.profile_rebound`` event that accounts for every
    row this method touched. That is why no event is appended here: the
    operation's event names each moved row, and it is deliberately an
    UNCOVERED type (see ``patch_coverage``) so the batch degrades to a full
    core rather than shipping a patch frame that folds nothing.
    """

    instance = store.get(persona_instance_id)
    value = safe_optional_token(profile_id)
    if instance.profile_id == value:
        return instance
    instance.profile_id = value
    instance.updated_at = now()
    store._write(instance)
    return store.get(instance.id)
