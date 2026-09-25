"""Persona resolution and the mission-chat target decision; auto-title and free-floating assignment closes.

Separate because every verb that names a persona resolves it through
``_persona_by_id`` / ``_resolve_mission_chat_persona_id``.
"""

from __future__ import annotations

from agent_runtime.cli_format import emit_json
from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import (
    PERSONA_INSTANCE_ID_PREFIX,
    PersonaAssignmentStore,
    PersonaInstanceStore,
    normalize_persona_id as _normalize_cli_persona_id,
    normalize_persona_or_template_id as _normalize_cli_persona_or_template_id,
    persona_id_from_instance_id as _persona_id_from_instance_id,
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.personas import profile_chat_toolsets, profile_persona_resolution

__layer__ = "stores"
__all__ = [
    "_close_free_floating_assignments",
    "_display_name_for_profile",
    "_maybe_auto_title_persona_chat",
    "_mission_chat_bare_persona_target",
    "_mission_chat_target_decision",
    "_persona_by_id",
    "_resolve_mission_chat_persona_id",
]


def _persona_by_id(cfg, persona_id: str):
    raw = str(persona_id or "").strip()
    # ensure_persisted_personas returns the seeded base profile plus the dormant
    # resolvable catalog, so typed pipeline ids and profile model-inheritance both resolve.
    personas = list(ensure_persisted_personas(cfg))
    normalized = _normalize_cli_persona_id(raw)
    exact = next(
        (persona for persona in personas if getattr(persona, "id", None) == raw),
        None,
    ) or next(
        (persona for persona in personas if getattr(persona, "id", None) == normalized),
        None,
    )
    if exact is not None:
        return exact
    if raw.lower().startswith("profile:"):
        profile_id = safe_assignment_token(raw.split(":", 1)[1])
        if not profile_id:
            return None
        matching_profile_persona, _, _ = profile_persona_resolution(profile_id, personas)
        default_model = getattr(matching_profile_persona, "model", None) if matching_profile_persona is not None else None
        default_provider = getattr(matching_profile_persona, "provider", None) if matching_profile_persona is not None else None
        default_api_mode = getattr(matching_profile_persona, "api_mode", None) if matching_profile_persona is not None else None
        default_autonomy = getattr(matching_profile_persona, "autonomy", None) if matching_profile_persona is not None else None
        default_include_core = (
            bool(getattr(matching_profile_persona, "include_core_context_files", False))
            if matching_profile_persona is not None
            else False
        )
        default_readiness = (
            dict(getattr(matching_profile_persona, "readiness", {}) or {})
            if matching_profile_persona is not None
            else {}
        )
        return AgentPersona(
            id=f"profile:{profile_id}",
            display_name=f"{_display_name_for_profile(profile_id)} Agent",
            role="profile",
            model=default_model or getattr(cfg, "default_model", None),
            provider=default_provider or getattr(cfg, "default_provider", None),
            api_mode=default_api_mode or getattr(cfg, "default_api_mode", None),
            toolsets=profile_chat_toolsets(profile_id, personas),
            system_prompt_path="",
            autonomy=str(default_autonomy or "review"),
            hermes_profile=profile_id,
            skills=[],
            include_profile_memory=True,
            include_core_context_files=default_include_core,
            readiness=default_readiness,
        )
    return None


def _display_name_for_profile(profile_id: str) -> str:
    return " ".join(part.capitalize() for part in profile_id.replace("_", "-").split("-") if part) or "Profile"


def _maybe_auto_title_persona_chat(*, session_db, session_id: str, user_message: str, assistant_response: str) -> None:
    if session_db is None or not session_id or not assistant_response:
        return
    try:
        from agent.title_generator import auto_title_session

        auto_title_session(
            session_db,
            session_id,
            user_message,
            assistant_response,
        )
    except Exception:
        return


def _close_free_floating_assignments(persona_instance_id: str, *, reason: str, json_output: bool, terminal_state: str) -> int:
    # Function-local, like the rest of this file.
    from agent_runtime.mission_chat_outcome import (
        FinalizationWarning,
        FinalizationWarningKind,
    )

    cfg = load_agent_runtime_config()
    normalized_instance = safe_assignment_token(persona_instance_id)
    store = PersonaAssignmentStore()
    matches = [
        item
        for item in store.list_all()
        if item.persona_instance_id == normalized_instance
        and item.evidence_kind == "free_floating"
        and item.state not in {"completed", "blocked", "cancelled"}
    ]
    if not matches:
        data = {"ok": False, "error": f"no active free-floating assignments for {persona_instance_id}"}
        print(emit_json(data) if json_output else data["error"])
        return 2
    closed = [store.complete(item.id, state=terminal_state, error=reason) for item in matches]
    finalization_warnings: list[FinalizationWarning] = []
    try:
        instance_store = PersonaInstanceStore()
        instance = instance_store.get(normalized_instance)
        if instance.current_assignment_id in {item.id for item in closed}:
            instance.current_assignment_id = None
            instance.mode = "configured"
            instance_store.update(instance)
    except Exception as instance_commit_exc:
        # Third copy of the same swallow. The assignments ARE closed by this
        # point, so a failure here leaves the instance pointing at work that no
        # longer exists — reported, not hidden.
        finalization_warnings.append(
            FinalizationWarning(
                kind=FinalizationWarningKind.INSTANCE_STATE_COMMIT_FAILED,
                detail=type(instance_commit_exc).__name__,
                step="clear_instance_assignment",
            )
        )
    data = {
        "ok": True,
        "persona_instance_id": normalized_instance,
        "closed_assignment_ids": [item.id for item in closed],
        "state": terminal_state,
        "production_proof_eligible": False,
        **(
            {
                "finalization_warnings": [
                    warning.as_dict() for warning in finalization_warnings
                ]
            }
            if finalization_warnings
            else {}
        ),
    }
    print(emit_json(data) if json_output else f"closed {len(closed)} free-floating assignments for {normalized_instance}")
    return 0


def _mission_chat_target_decision(
    *,
    instance_store,
    normalized_persona: str,
    raw_persona_id,
    persona_instance_id,
    session_id,
    relay_chain,
    requested_by_session=None,
):
    """Decide the ``ambiguous_target`` refusal for a mission-chat send.

    Reads the persona's live instances from the store (the roster's
    on-the-level set — retired instances are archived out of ``list_all``),
    NARROWS them to the sender's workspace, and computes whether the caller
    already pinned a specific instance, then defers the actual decision to the
    pure ``target_policy.evaluate_target`` authority (unit-testable in
    isolation, no store).

    ``caller_pinned`` is True whenever the send is NOT on the silent-fallback
    path — an explicit ``persona_instance_id``, a ``personainst_*`` target, or
    ANY caller-chosen ``session_id`` (the operator console always carries an
    instance-bearing session id, so its sends never trip this). Only the
    omitted-session + no-instance path can be ambiguous.

    ``requested_by_session`` is the SENDER's chat-root session id (threaded from
    the relay envelope). A BARE persona id is resolved only among the placements
    in the sender's own workspace, so a persona placed into several workspace
    scenes does not fan a two-agent order out onto duplicate placements in
    unrelated workspaces. Runtime-global PLACEMENT rows (no workspace pointer)
    stay in scope everywhere, but runtime-global CANONICAL rows are excluded
    from the candidate list under a real scope (instance = in-level placement)
    — an unplaced persona then has zero candidates, which ``evaluate_target``
    allows through to today's canonical-channel fallback (retiring that
    fallback is gated on the global-row adoption migration). An operator CLI
    invocation with no sender session falls back to the active workspace.

    "Placements shadow canonical": when an in-scope PLACEMENT of the persona
    exists, its auto-derived CANONICAL row is dropped from the candidate list —
    so a bare persona id with one in-scope placement resolves to that single
    placement (``evaluate_target`` auto-routes on one candidate, retiring the
    ambiguity prompt) instead of the plumbing canonical row, while TWO in-scope
    placements stay genuinely ambiguous. The scope + shadow is the one shared
    ``workspace_scope.addressable_roster`` authority; the count-based policy is
    unchanged.
    """
    from agent_runtime import target_policy, workspace_scope
    from agent_runtime.persona_assignments import (
        is_canonical_persona_channel,
        sender_scope_workspace_id,
    )

    is_profile = normalized_persona.startswith("profile:")
    raw_token = safe_assignment_token(raw_persona_id)
    caller_pinned = bool(
        persona_instance_id
        or raw_token.startswith(PERSONA_INSTANCE_ID_PREFIX)
        or safe_assignment_text(session_id, limit=200)
    )
    # Derive the sender's workspace scope (session → owner instance → its
    # workspace pointer; bare operator CLI send falls back to the active
    # workspace), then scope + shadow the persona's rows through the one shared
    # addressable-roster authority.
    scope_workspace_id = sender_scope_workspace_id(
        requested_by_session, instance_store=instance_store
    )
    addressable = workspace_scope.addressable_roster(
        (
            instance
            for instance in instance_store.list_all()
            if getattr(instance, "persona_id", None) == normalized_persona
        ),
        scope_workspace_id=scope_workspace_id,
        is_canonical=is_canonical_persona_channel,
    )
    candidates = sorted(
        (
            target_policy.TargetCandidate(
                instance_id=instance.id,
                display_name=safe_assignment_text(getattr(instance, "display_name", None), limit=120)
                or instance.id,
            )
            for instance in addressable
        ),
        key=lambda candidate: candidate.instance_id,
    )
    return target_policy.evaluate_target(
        persona_id=normalized_persona,
        candidates=candidates,
        caller_pinned_instance=caller_pinned,
        is_profile_target=is_profile,
        relay_chain=relay_chain,
    )


def _mission_chat_bare_persona_target(
    instance_store,
    *,
    normalized_persona: str,
    requested_by_session=None,
):
    """Resolve a BARE persona id to its single in-scope PLACEMENT id, or ``None``.

    The routing counterpart to the ambiguous-target guard: both read the one
    ``workspace_scope.addressable_roster`` authority with the same sender scope,
    so they never disagree. When exactly one placement of the persona is in the
    sender's scope, a bare persona send threads onto THAT placement (the
    "placements shadow canonical" ruling — the plumbing canonical row is not the
    default target while a deliberate placement is on the level). Returns
    ``None`` when there is no in-scope placement (the caller falls back to the
    canonical channel, reachability fallback) or when the guard would already
    have refused two-or-more in-scope placements.
    """
    from agent_runtime import workspace_scope
    from agent_runtime.persona_assignments import (
        is_canonical_persona_channel,
        sender_scope_workspace_id,
    )

    scope_workspace_id = sender_scope_workspace_id(
        requested_by_session, instance_store=instance_store
    )
    addressable = workspace_scope.addressable_roster(
        (
            instance
            for instance in instance_store.list_all()
            if getattr(instance, "persona_id", None) == normalized_persona
        ),
        scope_workspace_id=scope_workspace_id,
        is_canonical=is_canonical_persona_channel,
    )
    placements = [
        instance for instance in addressable if not is_canonical_persona_channel(instance)
    ]
    if len(placements) == 1:
        return placements[0].id
    return None


def _resolve_mission_chat_persona_id(persona_id, persona_instance_id) -> str:
    """Resolve the chat target persona from whichever identity the caller sent.

    Prefer the persona id; when it is mangled (a stale instance-shaped id from a
    legacy SessionDB row, a display token, etc.) but the caller also supplied a
    resolvable persona_instance_id, the instance wins instead of failing the
    whole send.
    """
    try:
        return _normalize_cli_persona_or_template_id(persona_id)
    except ValueError:
        instance_token = safe_assignment_token(persona_instance_id)
        if instance_token:
            return _persona_id_from_instance_id(instance_token)
        raise


# ``_normalize_cli_persona_id``, ``_persona_id_from_instance_id`` and
# ``_normalize_cli_persona_or_template_id`` were defined here. They are pure
# functions of ``agent_runtime.persona_assignments`` primitives and moved into
# that module (aliased back to these names in this part's import header) so the
# chat-root durability step, which normalizes the persona id it stamps on the
# session row, could stop being reachable only from a CLI part.
