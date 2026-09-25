"""The mission-chat turn's observability row: ``mission_chat_prompt_observability``.

Separate because it is the chat lane's one entry point into this package and
composes every store and policy module below it.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext
from typing import Any, Iterable

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from .context_budget import _context_budget
from .context_files import (
    WorkspaceAgentsContext,
    _attach_context_file_prompt_contributions,
    _layer_text_size,
    _mission_chat_identity_prompt_chars,
    _mission_chat_identity_prompt_content,
    _mission_chat_operative_rules_chars,
    _mission_chat_operative_rules_content,
    _profile_context_files,
    _soul_overlay_prompt_chars,
    _workspace_agents_prompt_chars,
)
from .safe_views import (
    SAFE_PREVIEW_LIMIT,
    _chat_history_context,
    _safe_final_model_input,
    _safe_turn_usage,
)
from .skills_context import _chat_metadata, available_skills_context, used_skills_context
from .skills_resolver import (
    _SkillObservabilityResolver,
    _accessible_skills_context,
    _installed_skill_catalog,
    _persona_skill_assignment_removals,
)
from .spans import (
    PROMPT_OBSERVABILITY_TIMINGS_KEY,
    _SPAN_CATALOG_WALK,
    _SPAN_SHARED_CATALOG,
    _mission_chat_memory_loaded,
    _observability_catalog_walks,
    _observability_span_ms,
    _reset_observability_spans,
)
from .turn_results import _safe_model_selection, _safe_persona_id

__layer__ = "lanes"
__all__ = [
    "mission_chat_prompt_observability",
]


def mission_chat_prompt_observability(
    *,
    persona: Any,
    persona_instance_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    goal_id: str | None = None,
    turn_id: str | None = None,
    surface_prompt: str | None = "",
    limiting_wrapper_active: bool = False,
    session_db: Any | None = None,
    current_message: str | None = None,
    final_model_input: dict[str, Any] | None = None,
    model_selection: dict[str, Any] | None = None,
    turn_usage: dict[str, Any] | None = None,
    trace_events: Iterable[dict[str, Any]] | None = None,
    prompt_mode: str = "normal_hermes_profile_chat",
    workspace_id: str | None = None,
    workspace_name: str | None = None,
    workspace_agents: WorkspaceAgentsContext | None = None,
    situational_hud: dict[str, Any] | None = None,
    situational_hud_revision: str | None = None,
    situational_hud_delivery: str | None = None,
    queued_skills: Iterable[str] | None = None,
    required_preload_skills: Iterable[str] | None = None,
    preloaded_skills_loaded: Iterable[str] | None = None,
    preloaded_skills_missing: Iterable[str] | None = None,
    instance_skill_overrides: Iterable[str] | None = None,
    skill_resolver: "_SkillObservabilityResolver | None" = None,
) -> dict[str, Any]:
    """Build redaction-safe prompt/context observability for Mission Control.

    This intentionally reports prompt layers and file provenance, not raw secret
    config values. Context files get hashes and short previews only when their
    filenames are known prompt/memory files.
    """

    persona_id = _safe_persona_id(getattr(persona, "id", None))
    profile = safe_assignment_token(getattr(persona, "hermes_profile", None)) or persona_id
    context_id = "ctx_" + hashlib.sha256(
        "|".join(
            str(item or "")
            for item in (
                persona_id,
                persona_instance_id,
                session_id,
                task_id,
                goal_id,
                turn_id,
                current_message,
                workspace_id,
                workspace_name,
                (
                    workspace_agents.receipt.get("sha256")
                    if workspace_agents is not None
                    else None
                ),
            )
        ).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    surface = safe_assignment_text(surface_prompt, limit=4000) or ""
    history = _chat_history_context(session_db=session_db, session_id=session_id)
    chat = _chat_metadata(session_db=session_db, session_id=session_id, task_id=task_id)
    queued_names = [safe_assignment_token(item) for item in queued_skills or ()]
    queued_names = [item for item in queued_names if item]
    required_names = [
        safe_assignment_token(item) for item in required_preload_skills or ()
    ]
    required_names = [item for item in required_names if item]
    loaded_names = [safe_assignment_token(item) for item in preloaded_skills_loaded or ()]
    loaded_names = [item for item in loaded_names if item]
    missing_names = [safe_assignment_token(item) for item in preloaded_skills_missing or ()]
    missing_names = [item for item in missing_names if item]
    override_names = {
        token
        for item in instance_skill_overrides or ()
        if (token := safe_assignment_token(item))
    }
    # CONTEXT-LOCAL binding, deliberately — not the env-exporting
    # ``persona_profile_context``. Both of this function's production lanes want
    # that, and for the same reason: neither holds ``_WORKDIR_LOCK``, so the env
    # mirror was an unserialized process-global mutation that every OTHER thread
    # read as its own scope.
    #
    #   * the SNAPSHOT lane — ``snapshot_prompt_observability`` calls this once
    #     per persona instance on the builder thread, and this is the section
    #     that bills ``prompt_observability:4520`` of a cold build, so the
    #     binding window is wide;
    #   * the TURN lane — ``persona_commands._cmd_mission_chat_message`` calls
    #     this at ``observability_built``, BEFORE ``profile_runner`` installs its
    #     own locked binding. So a turn was rebinding the process for every
    #     concurrent turn (``harness-serve_1`` / ``harness-serve_2``) and for the
    #     snapshot builder, not only the other way around.
    #
    # Sound because this block reaches no env-pinned reader. It spawns no
    # subprocess and drives no plugin. Its skill discovery resolves through
    # ``get_hermes_home()`` (ContextVar-first): ``skills_tool._skills_dir``,
    # ``skill_utils.get_skills_dir``, ``get_config_path``. The raw-``HERMES_HOME``
    # reader it does reach, ``get_default_hermes_root()`` (via
    # ``get_shared_skills_dir`` / ``RealmStore``'s runtime root), COLLAPSES — a
    # binding's ``profile_home`` is always ``<root>/profiles/<name>``, which maps
    # back to the same ``<root>`` the ambient home does; ``get_shared_skills_dir``
    # documents exactly that property. The realm rows are a sidecar file read
    # ("zero git calls in the snapshot", Decision 7). The per-persona hash check
    # takes an EXPLICIT ``hermes_home=`` and never the ambient one. Residue:
    # ``HOME`` is not redirected — see ``persona_profile_scope``.
    try:
        from ..profile_context import persona_profile_scope, resolve_persona_profile

        skill_profile_context = persona_profile_scope(
            resolve_persona_profile(persona)
        )
    except Exception:
        skill_profile_context = nullcontext()
    skill_resolver = skill_resolver or _SkillObservabilityResolver()
    # Stage 6 item 2 opens here: everything between this reset and the read
    # below is the skill half of ``observability_built − context_built``.
    _reset_observability_spans()
    _skill_block_started = time.monotonic()
    with skill_profile_context:
        skill_cache_key = (
            profile,
            persona_id,
            tuple(str(item) for item in (getattr(persona, "skills", None) or [])),
            tuple(sorted(loaded_names)),
            tuple(sorted(queued_names)),
            tuple(sorted(override_names)),
        )
        cached_skill_rows = skill_resolver.skill_context(skill_cache_key)
        if cached_skill_rows is None:
            installed_names = [
                safe_assignment_token(item.get("name"))
                for item in _installed_skill_catalog()
                if isinstance(item, dict) and safe_assignment_token(item.get("name"))
            ]
            skill_resolver.resolve([
                *installed_names,
                *(getattr(persona, "skills", None) or []),
            ])
            accessible_skills = _accessible_skills_context(
                persona,
                profile,
                loaded_skill_names=set(loaded_names),
                queued_skill_names=set(queued_names),
                instance_override_names=override_names,
                skill_resolver=skill_resolver,
            )
            skill_assignment_removals = _persona_skill_assignment_removals(persona)
            available_skills = available_skills_context(
                accessible_skills=accessible_skills,
                skill_resolver=skill_resolver,
            )
            skill_resolver.remember_skill_context(
                skill_cache_key,
                accessible_skills=accessible_skills,
                available_skills=available_skills,
                assignment_removals=skill_assignment_removals,
            )
        else:
            accessible_skills, available_skills, skill_assignment_removals = (
                cached_skill_rows
            )
        used_skills = used_skills_context(
            final_model_input=final_model_input,
            trace_events=trace_events,
            queued_skills=preloaded_skills_loaded,
            required_preload_skills=required_names,
            root_registries=skill_resolver._root_registries,
        )
    # …and closes here. The three spans are DISJOINT by construction: the two
    # walks are subtracted out of the block's total, so ``skill_rows`` is the
    # resolve and the row composition and nothing else, and an operator adding
    # the three up gets the block back rather than a number larger than it.
    _skill_block_ms = max(0, int((time.monotonic() - _skill_block_started) * 1000))
    _catalog_walk_ms = _observability_span_ms(_SPAN_CATALOG_WALK)
    _shared_catalog_ms = _observability_span_ms(_SPAN_SHARED_CATALOG)
    observability_timings = {
        "observability_skill_rows_ms": max(
            0, _skill_block_ms - _catalog_walk_ms - _shared_catalog_ms
        ),
        "observability_catalog_walk_ms": _catalog_walk_ms,
        "observability_shared_catalog_ms": _shared_catalog_ms,
        # A MEASUREMENT, not a default: ``1`` says the 15 s TTL held for every
        # catalog read this build made, ``0`` says at least one of them walked.
        # §0.3's two floors (≈430 ms warm against ≈840 ms 17 s later) are this
        # bit; without it the two are indistinguishable on the record.
        "observability_catalog_cached": 0 if _observability_catalog_walks() else 1,
    }
    skill_manifest_hash = hashlib.sha256(
        json.dumps(
            {
                "assigned": accessible_skills,
                "available": available_skills,
                "queued": queued_names,
                "required_preload": required_names,
                "loaded": loaded_names,
                "missing": missing_names,
                "removed": skill_assignment_removals,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    # Per-item in-prompt attribution — the parts reachable at THIS pre-turn
    # seam. Runtime identity and operator-channel rules are separate typed
    # layers; soul/memory continue to ride their provenance file rows so token
    # accounting has one owner and never double-counts.
    # SOUL.md / workspace-AGENTS.md rows get their pasted-part chars; config.yaml
    # gets a deliberate 0. .skills_prompt_snapshot.json is attached post-turn.
    runtime_identity_chars = _mission_chat_identity_prompt_chars(persona)
    operator_rules_chars = _mission_chat_operative_rules_chars()
    runtime_identity_content = _mission_chat_identity_prompt_content(persona)
    operator_rules_content = _mission_chat_operative_rules_content()
    soul_prompt_chars = _soul_overlay_prompt_chars(persona)
    workspace_prompt_chars = _workspace_agents_prompt_chars(workspace_agents)
    memory_loaded = _mission_chat_memory_loaded(persona)
    context_files: list[dict[str, Any]] = [
        *_profile_context_files(profile),
        *([workspace_agents.receipt] if workspace_agents is not None else []),
    ]
    _attach_context_file_prompt_contributions(
        context_files,
        soul_chars=soul_prompt_chars,
        workspace_chars=workspace_prompt_chars,
        memory_loaded=memory_loaded,
    )
    soul_row = next((row for row in context_files if row.get("name") == "SOUL.md"), None)
    soul_loaded = soul_prompt_chars is not None
    display_name = safe_assignment_text(getattr(persona, "display_name", None), limit=120) or persona_id
    return {
        "context_id": context_id,
        "prompt_mode": prompt_mode,
        "persona_id": persona_id,
        "persona_instance_id": safe_assignment_token(persona_instance_id),
        "profile": profile,
        "display_name": display_name,
        "role": safe_assignment_token(getattr(persona, "role", None)) or "agent",
        "session_id": safe_assignment_text(session_id, limit=200),
        "chat_id": chat.get("id"),
        "chat_title": chat.get("title"),
        "chat_name": chat.get("name"),
        "chat": chat,
        "task_id": safe_assignment_token(task_id),
        "goal_id": safe_assignment_token(goal_id),
        # The full runtime situational HUD (runtime · scope · mission · lane ·
        # roster · mission_hud) — the single projection the operator's runtime
        # HUD strip and the agent's mission-chat turn both render, so operator
        # and agent share one view. Empty until threaded (snapshot path); the
        # chat lane feeds the same projection into the model. See runtime_hud.py.
        "situational_hud": situational_hud if isinstance(situational_hud, dict) else {},
        "situational_hud_revision": safe_assignment_token(situational_hud_revision),
        "situational_hud_delivery": safe_assignment_token(situational_hud_delivery),
        "workspace_id": safe_assignment_token(workspace_id),
        "workspace_name": safe_assignment_text(workspace_name, limit=120),
        "turn_id": safe_assignment_token(turn_id),
        "surface_prompt": surface,
        "surface_prompt_is_blank": surface == "",
        "limiting_wrapper_active": bool(limiting_wrapper_active),
        "prompt_stack_schema_version": 2,
        "prompt_layers": [
            {
                "name": "Hermes core prompt",
                "kind": "system_core",
                "status": "loaded_by_profile_runner",
                "summary": "Universal Hermes identity fallback, tool guidance, skills index, environment guidance, and model/session metadata.",
                "owner": "hermes",
                "group": "hermes_core",
                "order": 10,
                "injection_location": "system_stable",
                "included": True,
                "token_attribution": "residual",
            },
            {
                "name": "Runtime identity",
                "kind": "runtime_identity",
                "status": "loaded",
                "summary": f"Identifies this channel as {display_name}, names its Mission Control persona id, and prevents self-relay.",
                "owner": "mission_control",
                "group": "mission_control_persona",
                "order": 20,
                "injection_location": "system_context",
                "included": True,
                "token_attribution": "direct",
                **(
                    {"content": runtime_identity_content}
                    if runtime_identity_content is not None
                    else {}
                ),
                **(
                    {
                        "chars": runtime_identity_chars,
                        "token_estimate": runtime_identity_chars // 4,
                    }
                    if runtime_identity_chars is not None
                    else {}
                ),
            },
            {
                "name": "Profile SOUL",
                "kind": "profile_soul",
                "status": "loaded" if soul_loaded else "not_configured",
                "summary": (
                    f"Durable identity and voice from the {profile} Hermes profile."
                    if soul_loaded
                    else f"No SOUL overlay resolved for the {profile} Hermes profile."
                ),
                "owner": "profile",
                "group": "mission_control_persona",
                "order": 30,
                "injection_location": "system_context",
                "included": soul_loaded,
                "token_attribution": "context_file",
                "source_context_file": "SOUL.md",
                **(
                    {
                        "source_path": soul_row.get("path"),
                        "source_sha256": soul_row.get("sha256"),
                        "source_prompt_token_estimate": soul_prompt_chars // 4,
                    }
                    if soul_loaded and isinstance(soul_row, dict)
                    else {}
                ),
            },
            {
                "name": "Operator-channel rules",
                "kind": "operator_channel_rules",
                "status": "loaded",
                "summary": "Mission Control behavior for real tool use, permissions, clarification, goals, agent threads, and anti-fabrication.",
                "owner": "mission_control",
                "group": "mission_control_persona",
                "order": 40,
                "injection_location": "system_context",
                "included": True,
                "token_attribution": "direct",
                **(
                    {"content": operator_rules_content}
                    if operator_rules_content is not None
                    else {}
                ),
                **(
                    {
                        "chars": operator_rules_chars,
                        "token_estimate": operator_rules_chars // 4,
                    }
                    if operator_rules_chars is not None
                    else {}
                ),
            },
            *(
                [
                    {
                        "name": "Workspace instructions",
                        "kind": "workspace_context",
                        "status": workspace_agents.receipt.get("status", "unknown"),
                        "summary": (
                            "Injected from the operator-selected workspace directory."
                            if workspace_agents.content is not None
                            else "Workspace instructions were not injected; see the file receipt."
                        ),
                        "owner": "workspace",
                        "group": "session_context",
                        "order": 50,
                        "injection_location": "system_context",
                        "included": workspace_agents.content is not None,
                        "token_attribution": "context_file",
                        "source_context_file": "AGENTS.md",
                        "source_path": workspace_agents.receipt.get("path"),
                        "source_sha256": workspace_agents.receipt.get("sha256"),
                        # Its bytes are attributed via the AGENTS.md context-file
                        # row, so this layer deliberately carries no estimate.
                    }
                ]
                if workspace_agents is not None
                else []
            ),
            {
                "name": "Session surface override",
                "kind": "surface",
                "status": "blank" if surface == "" else "configured",
                "summary": (
                    "No per-session override is configured; the standard persona and channel rules apply."
                    if surface == ""
                    else "Additional session-specific instructions supplied by the Mission Control surface."
                ),
                "owner": "mission_control",
                "group": "session_context",
                "order": 60,
                "injection_location": "system_context",
                "included": surface != "",
                "token_attribution": "direct",
                "preview": surface[:SAFE_PREVIEW_LIMIT],
                **_layer_text_size(surface),
            },
            {
                "name": "Profile memory",
                "kind": "profile_context",
                "status": "loaded" if memory_loaded else "skipped",
                "summary": (
                    "Profile MEMORY.md / USER.md loaded (persona opts in via include_profile_memory)."
                    if memory_loaded
                    else "Profile memory skipped; this persona does not opt into its bound profile's memory."
                ),
                "owner": "profile",
                "group": "profile_context",
                "order": 70,
                "injection_location": "system_volatile",
                "included": memory_loaded,
                "token_attribution": "context_file",
                # Its bytes are attributed via the MEMORY.md / USER.md context-file
                # rows; no per-layer estimate here so the launcher never double-counts.
            },
            {
                "name": "Chat history context",
                "kind": "conversation",
                "status": "loaded" if history else "empty",
                "summary": f"{len(history)} prior redaction-safe chat message(s) supplied before this turn.",
                "owner": "conversation",
                "group": "runtime_context",
                "order": 80,
                "injection_location": "conversation_history",
                "included": bool(history),
                "token_attribution": "history_rows",
            },
            {
                "name": "Runtime Situation HUD",
                "kind": "situational_hud",
                "status": "loaded" if (isinstance(situational_hud, dict) and situational_hud) else "empty",
                "summary": (
                    "Live runtime, scope, mission, lane, and roster state added to the operator's user turn."
                    if (isinstance(situational_hud, dict) and situational_hud)
                    else "No runtime situation resolved for this turn."
                ),
                "owner": "mission_control",
                "group": "runtime_context",
                "order": 90,
                "injection_location": "user_turn",
                "included": bool(isinstance(situational_hud, dict) and situational_hud),
                "token_attribution": "final_model_input",
                # Its bytes ride in the operator user-turn message
                # (``final_model_input`` messages), so this layer carries no
                # per-layer token estimate — the launcher already counts them via
                # that message and would otherwise double-count the HUD.
            },
        ],
        "context_files": context_files,
        "used_skills": used_skills,
        "queued_skills": queued_names,
        "required_preload_skills": required_names,
        "preloaded_skills_loaded": loaded_names,
        "preloaded_skills_missing": missing_names,
        "skill_manifest_hash": skill_manifest_hash,
        "skill_assignment_removals": skill_assignment_removals,
        # C1 RECORD-ONCE (2026-07-17): the built row carries ONE copy of each
        # fact — the pre-C1 alias keys (``skills_catalog`` ≡ available_skills,
        # ``skills`` ≡ accessible_skills) are DELETED, no compat emission
        # (ruling 0). Readers were audited and retargeted to the canonical two;
        # legacy persisted rows that still carry the aliases are normalized at
        # the read/persist boundaries.
        "accessible_skills": accessible_skills,
        "available_skills": available_skills,
        "chat_history_context": history,
        "retrieval_context": [],
        "final_model_input": _safe_final_model_input(final_model_input),
        "model_selection": _safe_model_selection(model_selection),
        # What this ONE operator message actually burned, metered per API call
        # and summed over the turn's tool loop. Distinct from context_budget,
        # which is the size of the assembled context for a single call — the
        # two were conflated, which is how a 6K inspector sat next to a 13K bill.
        "turn_usage": _safe_turn_usage(turn_usage),
        "context_budget": _context_budget(model_selection, final_model_input, turn_usage),
        "prompt_flags": {
            "skip_context_files": not bool(getattr(persona, "include_core_context_files", False)),
            "skip_memory": not _mission_chat_memory_loaded(persona),
            # Legacy profile-runner flag: this lane does not ask Hermes core to
            # substitute SOUL as its base identity. The independently assembled
            # profile_soul layer below is the authoritative overlay signal.
            "load_soul_identity": False,
            "soul_overlay_loaded": soul_loaded,
            "profile_memory_loaded": memory_loaded,
            "surface_prompt_blank": surface == "",
            "limiting_wrapper_active": bool(limiting_wrapper_active),
            "workspace_agents_injected": bool(
                workspace_agents is not None and workspace_agents.content is not None
            ),
        },
        "redaction": {
            "status": "safe",
            "notes": [
                "Prompt observability shows file provenance, hashes, and short redaction-safe previews.",
                "Secrets and raw provider credentials are not included.",
            ],
        },
        # chat-turn-prep Stage 6 item 2, riding OUT on the built object and no
        # further: the turn handler folds it onto ``profile_timing`` (where the
        # store bounds it) and :func:`persist_prompt_observability_context`
        # strips it, so this mapping never reaches a persisted row. It is here
        # rather than on a side channel because the builder is called through
        # one return value and a second one would be a seam every caller has to
        # remember.
        PROMPT_OBSERVABILITY_TIMINGS_KEY: observability_timings,
    }
