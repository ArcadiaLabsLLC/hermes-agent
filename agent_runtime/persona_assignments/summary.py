"""The wire summaries of persona instances and assignments (the roster rows the
snapshot and the status lanes ship), the tool-visibility detail, and the token
sanitizers every summary field passes through.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent_runtime.agent_create_phases import timed_create_subphase
from agent_runtime.models import AgentPersona, PersonaAssignment, PersonaInstance
from agent_runtime.persona_assignments.identity import _display_name_for_template
from agent_runtime.persona_assignments.profile import _model_supports_reasoning_effort
from agent_runtime.personas import (
    declared_lane_toolsets,
    effective_toolsets,
    profile_chat_toolsets,
)
from agent_runtime.serde import safe_assignment_token
from agent_runtime.states import ACTIVE_LANE_STATES
from agent_runtime.tool_permissions import (
    default_permission_mode,
    permission_options_for_chat,
)
from agent_runtime.tool_visibility import (
    permission_state_for_persona,
    resolve_tool_visibility,
    turn_tool_context_for_persona,
)

__layer__ = "policy"

__all__ = [
    "active_persona_instance_agent_summaries",
    "persona_assignment_summary",
    "persona_instance_summary",
    "persona_instance_tool_detail",
    "PERSONA_INSTANCE_VISIBILITY_FIELDS",
    "persona_instance_visibility_ref",
    "_persona_instance_is_active_lane",
    "_profile_visibility_persona",
]


# S56 removed ``persona_instance_runtime_enabled`` and
# ``persona_assignment_store_enabled``. Both read
# ``enterprise_worker_sessions``, a config block named for a lane that no longer
# exists, and they gated the persona-instance ROSTER — the identity substrate
# every Mission Control surface keys on. The enabled shape has been the only
# shape for months (the live alice config sets all three fields true), and there
# is no disable consumer: nothing in either repo branches on a false verdict
# except the CLI's own "runtime is disabled" print. Both sections are now
# unconditional; the ``persona_instance_runtime`` WIRE block survives and
# reports the truth. See tests/agent_runtime/test_s56_config_block_removal.py (deleted 2026-09-24)
# (`::test_the_roster_section_is_emitted_unconditionally`, `:186`, and
# `::test_an_operator_config_that_still_disables_the_old_block_does_not_suppress_the_roster`,
# `:260`) -- this line named test_s56_roster_gate_removal.py, which never
# existed; repointed MCF-78 2026-08-20.


def persona_instance_summary(
    instance: PersonaInstance,
    persona: AgentPersona | None = None,
    *,
    profile_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = instance.state.value if hasattr(instance.state, "value") else str(instance.state)
    visibility_persona = persona or _profile_visibility_persona(instance)
    profile_id = instance.profile_id or getattr(visibility_persona, "hermes_profile", None)
    skills = (
        list(instance.skill_overrides)
        if instance.skill_overrides is not None
        else list(getattr(visibility_persona, "skills", []) or [])
    )
    tool_options = None
    if visibility_persona is not None:
        with timed_create_subphase("permission_options_ms"):
            tool_options = permission_options_for_chat(
                visibility_persona,
                session_id=instance.default_chat_session_id,
                task_id=instance.current_task_id,
                goal_id=instance.goal_id,
                runtime_root=instance.runtime_root,
            )
        # T9b: this preview is the persona instance's operator CHAT lane, so it
        # must reflect the chat-lane scoping (augmentation + cost cuts + restore
        # knob + registry hygiene) — not the raw effective_toolsets. Lazy import
        # avoids a module-load cycle; the chat-lane authority stays single.
        from ..persona_runtime import apply_chat_lane_tool_scope

        with timed_create_subphase("chat_lane_scope_ms"):
            apply_chat_lane_tool_scope(
                visibility_persona, tool_options, session_id=instance.default_chat_session_id
            )
    summary = {
        "agent_profile_id": instance.id,
        "agent_profile_display_name": instance.display_name,
        "source_persona_id": instance.persona_id,
        "source_profile_id": profile_id,
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "role": instance.role,
        "display_name": instance.display_name,
        "profile_id": profile_id,
        "backing_profile": profile_id,
        "repo_scope_label": getattr(persona, "repo_scope_label", None),
        "skills": skills,
        "skill_overrides": list(instance.skill_overrides) if instance.skill_overrides is not None else None,
        # Instance model-override tier (None = inherit persona live). The
        # effective_* pair is the agent-level value (override or persona
        # default); the config-default tier below persona resolves at runtime.
        "model": instance.model,
        "provider": instance.provider,
        "api_mode": instance.api_mode,
        "model_is_override": bool(instance.model or instance.provider or instance.reasoning_effort),
        "effective_model": instance.model or getattr(visibility_persona, "model", None),
        "effective_provider": instance.provider or getattr(visibility_persona, "provider", None),
        # Per-instance reasoning-effort override (None = inherit runtime default)
        # plus whether the effective model supports reasoning effort at all, so
        # the Launcher only offers the effort control for reasoning-capable
        # models (no fake affordance). Computed offline from the model id.
        "reasoning_effort": instance.reasoning_effort,
        "reasoning_supported": _model_supports_reasoning_effort(
            instance.model or getattr(visibility_persona, "model", None)
        ),
        # The DECLARED lane toolsets (S0a A2), not the persona's legacy field:
        # the field is read by no admission path since A1, so projecting it here
        # made the launcher's instance summary describe a capability set no turn
        # ever ran with. The legacy list travels beside it, labelled, inside
        # ``toolset_declaration.persona_list``.
        "toolsets": effective_toolsets(visibility_persona)
        if visibility_persona is not None
        else [],
        "toolset_declaration": declared_lane_toolsets(visibility_persona).row()
        if visibility_persona is not None
        else None,
        "runtime_root": instance.runtime_root,
        "state": state,
        "lifecycle_mode": instance.mode,
        "mode": instance.mode,
        "goal_id": instance.goal_id,
        "workspace_id": instance.workspace_id,
        "realm_id": instance.realm_id,
        "spawned_by": instance.spawned_by,
        "steered_by": list(instance.steered_by),
        "returned_to": instance.returned_to,
        "current_chat_goal": instance.current_chat_goal,
        # S70 removed the two duplicate ALIASES this row used to carry
        # (contract 54): ``current_work_assignment_id`` and ``attached_task_id``
        # projected byte-identical values to the canonical keys below them, so a
        # reader could never distinguish them. No Launcher code read either name;
        # the only reader was the orphan classifier's own alias slot, which reads
        # the canonical key in the same predicate. Note the asymmetry the ledger
        # missed: ``attached_task_id`` was NOT writer-less — ``current_task_id``
        # is written live by the steer/goal-id lane — it was merely redundant.
        "current_assignment_id": instance.current_assignment_id,
        "current_task_id": instance.current_task_id,
        # S56 removed ``active_worker_session_id`` from this row (contract 47).
        # Its only writer was ``update_from_worker``, which went with the worker
        # session store; the field could never be non-null again.
        "active_run_id": instance.active_run_id,
        "default_chat_session_id": instance.default_chat_session_id,
        "chat_session_id": instance.default_chat_session_id,
        "session_id": instance.default_chat_session_id,
        # S70 (contract 54) also dropped ``context_receipt_id`` /
        # ``compression_receipt_id`` / ``tool_budget_used`` /
        # ``watchdog_warning_count`` from this row: writer-less since the
        # worker/goal lanes died AND with no consumer past the Launcher's model
        # copy. ``token_budget_used`` / ``last_heartbeat_at`` are just as
        # writer-less but STAY — both are read live downstream (token-total
        # fallback; roster recency, gateway state frame, orphan heartbeat hold),
        # so they are a reader-side retirement, not a wire cleanup.
        "skill_manifest_hash": instance.skill_manifest_hash,
        "token_budget_used": instance.token_budget_used,
        "last_heartbeat_at": instance.last_heartbeat_at,
        "updated_at": instance.updated_at,
    }
    if visibility_persona is not None:
        # Residue-slim R2: the heavy tool-detail payloads
        # (``turn_tool_context`` / ``tool_resolution`` / ``permission_state`` /
        # ``blocked_tools`` — ~97% of this row's bytes) leave the wire row behind
        # a typed ``visibility_ref`` pointer and are rebuilt on demand by
        # ``harness persona-instance detail <id> --json``. ``agent_hud_state`` is
        # RETIRED outright (the situational-HUD lane in ``runtime_hud.py`` is the
        # single HUD authority now). The always-visible agents drawer renders only
        # the head SCALARS below, derived at emit from the same tool-visibility
        # resolution (never from the retired hud state).
        with timed_create_subphase("tool_visibility_ms"):
            tool_resolution = resolve_tool_visibility(
                visibility_persona,
                tool_options,
                profile_readiness=profile_readiness,
            )
        # Fallback follows the RUNTIME DEFAULT (see snapshot._agent_summary).
        summary["permission_mode"] = tool_resolution.get("permission_mode") or default_permission_mode()
        summary["mutation_boundary"] = tool_resolution["mutation_boundary"]
        summary["tool_count"] = tool_resolution["final_tool_count"]
        summary["blocked_tools_count"] = len(tool_resolution["blocked_tools"])
        summary["effective_toolsets"] = tool_resolution["effective_toolsets"]
        summary["visibility_ref"] = persona_instance_visibility_ref(instance.id)
    return summary


#: The tool-detail fields R2 evicts from ``persona_instance_summary`` /
#: ``_agent_summary`` and serves on demand. ``agent_hud_state`` is deliberately
#: absent — retired, not evicted.
PERSONA_INSTANCE_VISIBILITY_FIELDS = (
    "tool_resolution",
    "turn_tool_context",
    "permission_state",
    "blocked_tools",
)


def persona_instance_visibility_ref(entity_id: str) -> dict[str, Any]:
    """Typed pointer replacing the evicted tool-detail payloads on a wire row.

    Mirrors the S8 ``detail_ref`` grammar (``evicted`` / id / evicted ``fields`` /
    ``fetch`` verb). The launcher renders an honest fetch affordance and pulls the
    full payloads via the fetch verb when the visibility dialog opens. Shared by
    ``persona_instance_summary`` and ``_agent_summary`` — both evict the same four
    fields and both fetch through ``harness persona-instance detail`` (which
    resolves a persona-instance id OR a persona id)."""

    return {
        "evicted": True,
        "id": entity_id,
        "fields": list(PERSONA_INSTANCE_VISIBILITY_FIELDS),
        "fetch": "harness persona-instance detail <id> --json",
    }


def persona_instance_tool_detail(
    instance: PersonaInstance, persona: AgentPersona | None = None
) -> dict[str, Any] | None:
    """The evicted tool-detail payloads for one persona instance, rebuilt from the
    same tool-visibility resolution ``persona_instance_summary`` used before R2.

    Served by ``harness persona-instance detail`` — the on-demand fetch behind the
    ``visibility_ref`` pointer. Returns ``None`` when no backing persona resolves
    (an honest "unavailable" the launcher surfaces, never a fake-empty payload).
    ``agent_hud_state`` is intentionally NOT rebuilt here (retired)."""

    visibility_persona = persona or _profile_visibility_persona(instance)
    if visibility_persona is None:
        return None
    tool_options = permission_options_for_chat(
        visibility_persona,
        session_id=instance.default_chat_session_id,
        task_id=instance.current_task_id,
        goal_id=instance.goal_id,
        runtime_root=instance.runtime_root,
    )
    # T9b: this on-demand tool detail is the persona instance's operator CHAT
    # lane — scope the preview to it (see apply_chat_lane_tool_scope).
    from ..persona_runtime import apply_chat_lane_tool_scope

    apply_chat_lane_tool_scope(
        visibility_persona, tool_options, session_id=instance.default_chat_session_id
    )
    tool_resolution = resolve_tool_visibility(visibility_persona, tool_options)
    return {
        "persona_instance_id": instance.id,
        "persona_id": instance.persona_id,
        "display_name": instance.display_name,
        "tool_resolution": tool_resolution,
        "turn_tool_context": turn_tool_context_for_persona(
            visibility_persona, tool_options, visibility=tool_resolution
        ),
        "permission_state": permission_state_for_persona(
            visibility_persona, tool_options, visibility=tool_resolution
        ),
        "blocked_tools": tool_resolution["blocked_tools"],
    }


def active_persona_instance_agent_summaries(
    instances: list[PersonaInstance],
    personas_by_id: dict[str, AgentPersona] | None = None,
    readiness_by_persona_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    personas_by_id = personas_by_id or {}
    readiness_by_persona_id = readiness_by_persona_id or {}
    for instance in instances:
        instance_id = safe_assignment_token(getattr(instance, "id", None))
        if not instance_id or instance_id in seen:
            continue
        if not _persona_instance_is_active_lane(instance):
            continue
        persona_id = safe_assignment_token(getattr(instance, "persona_id", None)) or instance_id
        row = persona_instance_summary(
            instance,
            personas_by_id.get(persona_id),
            profile_readiness=readiness_by_persona_id.get(persona_id),
        )
        row["runtime_agent_kind"] = "persona_instance"
        row["source_persona_id"] = persona_id
        row["persona_id"] = instance_id
        row["agent_profile_id"] = instance_id
        row["persona_instance_id"] = instance_id
        row["base_persona_id"] = persona_id
        row["display_name"] = row.get("display_name") or instance_id
        seen.add(instance_id)
        rows.append(row)
    return rows


def _persona_instance_is_active_lane(instance: PersonaInstance) -> bool:
    state = getattr(instance, "state", None)
    state_text = state.value if hasattr(state, "value") else str(state or "")
    if state_text in ACTIVE_LANE_STATES:
        return True
    return any(
        bool(getattr(instance, attr, None))
        for attr in ("current_task_id", "goal_id", "current_assignment_id", "active_run_id")
    )


def _profile_visibility_persona(instance: PersonaInstance) -> AgentPersona | None:
    profile_id = (instance.profile_id or "").strip()
    persona_id = (instance.persona_id or "").strip()
    if not profile_id and not persona_id.lower().startswith("profile:"):
        return None
    if not profile_id and persona_id.lower().startswith("profile:"):
        profile_id = persona_id.split(":", 1)[1].strip()
    resolved_persona_id = persona_id or (f"profile:{profile_id}" if profile_id else "profile:unknown")
    display_name = instance.display_name or _display_name_for_template(profile_id or resolved_persona_id)
    try:
        from ..config import ensure_persisted_personas, load_agent_runtime_config

        persisted_personas = list(ensure_persisted_personas(load_agent_runtime_config()))
    except Exception:
        persisted_personas = []
    configured = next(
        (
            candidate
            for candidate in persisted_personas
            if safe_assignment_token(getattr(candidate, "id", None))
            == safe_assignment_token(resolved_persona_id)
            or (
                profile_id
                and safe_assignment_token(getattr(candidate, "hermes_profile", None))
                == safe_assignment_token(profile_id)
            )
        ),
        None,
    )
    if configured is not None:
        return replace(
            configured,
            id=resolved_persona_id,
            display_name=display_name,
            hermes_profile=profile_id or configured.hermes_profile,
            skills=(
                list(instance.skill_overrides)
                if instance.skill_overrides is not None
                else list(configured.skills)
            ),
        )
    return AgentPersona(
        id=resolved_persona_id,
        display_name=display_name,
        role=instance.role,
        model=instance.model,
        provider=instance.provider,
        api_mode=instance.api_mode,
        toolsets=profile_chat_toolsets(profile_id, persisted_personas),
        system_prompt_path="",
        hermes_profile=profile_id or None,
        skills=list(instance.skill_overrides or []),
    )


def persona_assignment_summary(assignment: PersonaAssignment) -> dict[str, Any]:
    return {
        "agent_profile_id": assignment.persona_instance_id,
        "assignment_id": assignment.id,
        "persona_instance_id": assignment.persona_instance_id,
        "persona_id": assignment.persona_id,
        "kind": assignment.kind,
        "state": assignment.state,
        "title": assignment.title,
        "message": assignment.message,
        "task_id": assignment.task_id,
        "goal_id": assignment.goal_id,
        "stage_id": assignment.stage_id,
        "operation_id": assignment.operation_id,
        "repo_bundle_id": assignment.repo_bundle_id,
        "repo": assignment.repo,
        "affected_paths": list(assignment.affected_paths or []),
        "proof_targets": list(assignment.proof_targets or []),
        "acceptance": list(assignment.acceptance or []),
        "non_goals": list(assignment.non_goals or []),
        "allowed_decisions": list(assignment.allowed_decisions or []),
        "allowed_tools": list(assignment.allowed_tools or []),
        "run_ids": list(assignment.run_ids or []),
        "proof_ids": list(assignment.proof_ids or []),
        "context_receipt_ids": list(assignment.context_receipt_ids or []),
        "evidence_kind": assignment.evidence_kind,
        "production_proof_eligible": bool(assignment.production_proof_eligible),
        "archive_scope": assignment.archive_scope,
        "client_message_id": assignment.client_message_id,
        "created_by": assignment.created_by,
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
        "completed_at": assignment.completed_at,
        "last_error": assignment.last_error,
        "signal_hash": assignment.signal_hash,
    }
