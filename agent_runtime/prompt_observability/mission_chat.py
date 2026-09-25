"""The mission-chat turn's observability row: ``mission_chat_prompt_observability``.

Separate because it is the chat lane's one entry point into this package and
composes every store and policy module below it. The row is built by
:class:`MissionChatObservability`, one method per section of the row it writes.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
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
    "MissionChatObservability",
    "mission_chat_prompt_observability",
]


def mission_chat_prompt_observability(**request: Any) -> dict[str, Any]:
    """Build redaction-safe prompt/context observability for Mission Control.

    This intentionally reports prompt layers and file provenance, not raw secret
    config values. Context files get hashes and short previews only when their
    filenames are known prompt/memory files. The keyword arguments are
    :class:`MissionChatObservability`'s fields.
    """

    return MissionChatObservability(**request).build()


def _observability_timings(skill_block_started: float) -> dict[str, int]:
    """The skill block's three disjoint sub-spans and the catalog-cache bit.

    The three spans are DISJOINT by construction: the two walks are subtracted
    out of the block's total, so ``skill_rows`` is the resolve and the row
    composition and nothing else, and an operator adding the three up gets the
    block back rather than a number larger than it.
    """

    _skill_block_ms = max(0, int((time.monotonic() - skill_block_started) * 1000))
    _catalog_walk_ms = _observability_span_ms(_SPAN_CATALOG_WALK)
    _shared_catalog_ms = _observability_span_ms(_SPAN_SHARED_CATALOG)
    return {
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


def _skill_profile_context(persona: Any) -> Any:
    """The skill block's profile binding: context-local, never the process env.

    CONTEXT-LOCAL binding, deliberately — not the env-exporting
    ``persona_profile_context``. Both of this builder's production lanes want
    that, and for the same reason: neither holds ``_WORKDIR_LOCK``, so the env
    mirror was an unserialized process-global mutation that every OTHER thread
    read as its own scope.

      * the SNAPSHOT lane — ``snapshot_prompt_observability`` calls the builder
        once per persona instance on the builder thread, and this is the section
        that bills ``prompt_observability:4520`` of a cold build, so the
        binding window is wide;
      * the TURN lane — ``persona_commands._cmd_mission_chat_message`` calls
        it at ``observability_built``, BEFORE ``profile_runner`` installs its
        own locked binding. So a turn was rebinding the process for every
        concurrent turn (``harness-serve_1`` / ``harness-serve_2``) and for the
        snapshot builder, not only the other way around.

    Sound because this block reaches no env-pinned reader. It spawns no
    subprocess and drives no plugin. Its skill discovery resolves through
    ``get_hermes_home()`` (ContextVar-first): ``skills_tool._skills_dir``,
    ``skill_utils.get_skills_dir``, ``get_config_path``. The raw-``HERMES_HOME``
    reader it does reach, ``get_default_hermes_root()`` (via
    ``get_shared_skills_dir`` / ``RealmStore``'s runtime root), COLLAPSES — a
    binding's ``profile_home`` is always ``<root>/profiles/<name>``, which maps
    back to the same ``<root>`` the ambient home does; ``get_shared_skills_dir``
    documents exactly that property. The realm rows are a sidecar file read
    ("zero git calls in the snapshot", Decision 7). The per-persona hash check
    takes an EXPLICIT ``hermes_home=`` and never the ambient one. Residue:
    ``HOME`` is not redirected — see ``persona_profile_scope``.
    """

    try:
        from ..profile_context import persona_profile_scope, resolve_persona_profile

        return persona_profile_scope(resolve_persona_profile(persona))
    except Exception:
        return nullcontext()


def _tokens(items: Iterable[Any] | None) -> list[str]:
    """The safe tokens of an optional iterable, empties dropped, order kept."""

    tokens = [safe_assignment_token(item) for item in items or ()]
    return [item for item in tokens if item]


@dataclass
class MissionChatObservability:
    """One mission-chat turn's observability row, built in the phases of the row it writes.

    The init fields are :func:`mission_chat_prompt_observability`'s keyword
    arguments. :meth:`build` runs :meth:`bind` (identity, context id, the skill
    name lists), :meth:`skills` (the skill rows under the profile binding, with
    the Stage 6 sub-spans), :meth:`attribute_context_files` (the per-file
    in-prompt contribution) and then :meth:`row`; each phase fills the fields
    the next one reads.
    """

    persona: Any
    persona_instance_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    goal_id: str | None = None
    turn_id: str | None = None
    surface_prompt: str | None = ""
    limiting_wrapper_active: bool = False
    session_db: Any | None = None
    current_message: str | None = None
    final_model_input: dict[str, Any] | None = None
    model_selection: dict[str, Any] | None = None
    turn_usage: dict[str, Any] | None = None
    trace_events: Iterable[dict[str, Any]] | None = None
    prompt_mode: str = "normal_hermes_profile_chat"
    workspace_id: str | None = None
    workspace_name: str | None = None
    workspace_agents: WorkspaceAgentsContext | None = None
    situational_hud: dict[str, Any] | None = None
    situational_hud_revision: str | None = None
    situational_hud_delivery: str | None = None
    queued_skills: Iterable[str] | None = None
    required_preload_skills: Iterable[str] | None = None
    preloaded_skills_loaded: Iterable[str] | None = None
    preloaded_skills_missing: Iterable[str] | None = None
    instance_skill_overrides: Iterable[str] | None = None
    skill_resolver: "_SkillObservabilityResolver | None" = None

    # bind()
    persona_id: str = field(init=False)
    profile: str = field(init=False)
    context_id: str = field(init=False)
    surface: str = field(init=False)
    history: list[Any] = field(init=False)
    chat: dict[str, Any] = field(init=False)
    queued_names: list[str] = field(init=False)
    required_names: list[str] = field(init=False)
    loaded_names: list[str] = field(init=False)
    missing_names: list[str] = field(init=False)
    override_names: set[str] = field(init=False)
    # skills()
    accessible_skills: Any = field(init=False)
    available_skills: Any = field(init=False)
    skill_assignment_removals: Any = field(init=False)
    used_skills: list[dict[str, Any]] = field(init=False)
    observability_timings: dict[str, int] = field(init=False)
    skill_manifest_hash: str = field(init=False)
    # attribute_context_files()
    context_files: list[dict[str, Any]] = field(init=False)
    soul_prompt_chars: int | None = field(init=False)
    memory_loaded: bool = field(init=False)

    def build(self) -> dict[str, Any]:
        self.bind()
        self.skills()
        self.attribute_context_files()
        return self.row()

    def bind(self) -> None:
        persona = self.persona
        self.persona_id = _safe_persona_id(getattr(persona, "id", None))
        self.profile = safe_assignment_token(getattr(persona, "hermes_profile", None)) or self.persona_id
        workspace_agents = self.workspace_agents
        self.context_id = "ctx_" + hashlib.sha256(
            "|".join(
                str(item or "")
                for item in (
                    self.persona_id,
                    self.persona_instance_id,
                    self.session_id,
                    self.task_id,
                    self.goal_id,
                    self.turn_id,
                    self.current_message,
                    self.workspace_id,
                    self.workspace_name,
                    (
                        workspace_agents.receipt.get("sha256")
                        if workspace_agents is not None
                        else None
                    ),
                )
            ).encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        self.surface = safe_assignment_text(self.surface_prompt, limit=4000) or ""
        self.history = _chat_history_context(session_db=self.session_db, session_id=self.session_id)
        self.chat = _chat_metadata(session_db=self.session_db, session_id=self.session_id, task_id=self.task_id)
        self.queued_names = _tokens(self.queued_skills)
        self.required_names = _tokens(self.required_preload_skills)
        self.loaded_names = _tokens(self.preloaded_skills_loaded)
        self.missing_names = _tokens(self.preloaded_skills_missing)
        self.override_names = set(_tokens(self.instance_skill_overrides))

    def skills(self) -> None:
        skill_profile_context = _skill_profile_context(self.persona)
        self.skill_resolver = self.skill_resolver or _SkillObservabilityResolver()
        # Stage 6 item 2 opens here: everything between this reset and the read
        # below is the skill half of ``observability_built − context_built``.
        _reset_observability_spans()
        _skill_block_started = time.monotonic()
        with skill_profile_context:
            self._skill_rows()
            self.used_skills = used_skills_context(
                final_model_input=self.final_model_input,
                trace_events=self.trace_events,
                queued_skills=self.preloaded_skills_loaded,
                required_preload_skills=self.required_names,
                root_registries=self.skill_resolver._root_registries,
            )
        # …and closes here (see :func:`_observability_timings`).
        self.observability_timings = _observability_timings(_skill_block_started)
        self.skill_manifest_hash = hashlib.sha256(
            json.dumps(
                {
                    "assigned": self.accessible_skills,
                    "available": self.available_skills,
                    "queued": self.queued_names,
                    "required_preload": self.required_names,
                    "loaded": self.loaded_names,
                    "missing": self.missing_names,
                    "removed": self.skill_assignment_removals,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _skill_rows(self) -> None:
        persona, skill_resolver = self.persona, self.skill_resolver
        assert skill_resolver is not None
        skill_cache_key = (
            self.profile,
            self.persona_id,
            tuple(str(item) for item in (getattr(persona, "skills", None) or [])),
            tuple(sorted(self.loaded_names)),
            tuple(sorted(self.queued_names)),
            tuple(sorted(self.override_names)),
        )
        cached_skill_rows = skill_resolver.skill_context(skill_cache_key)
        if cached_skill_rows is not None:
            self.accessible_skills, self.available_skills, self.skill_assignment_removals = (
                cached_skill_rows
            )
            return
        installed_names = [
            safe_assignment_token(item.get("name"))
            for item in _installed_skill_catalog()
            if isinstance(item, dict) and safe_assignment_token(item.get("name"))
        ]
        skill_resolver.resolve([
            *installed_names,
            *(getattr(persona, "skills", None) or []),
        ])
        self.accessible_skills = _accessible_skills_context(
            persona,
            self.profile,
            loaded_skill_names=set(self.loaded_names),
            queued_skill_names=set(self.queued_names),
            instance_override_names=self.override_names,
            skill_resolver=skill_resolver,
        )
        self.skill_assignment_removals = _persona_skill_assignment_removals(persona)
        self.available_skills = available_skills_context(
            accessible_skills=self.accessible_skills,
            skill_resolver=skill_resolver,
        )
        skill_resolver.remember_skill_context(
            skill_cache_key,
            accessible_skills=self.accessible_skills,
            available_skills=self.available_skills,
            assignment_removals=self.skill_assignment_removals,
        )

    def attribute_context_files(self) -> None:
        # Per-item in-prompt attribution — the parts reachable at THIS pre-turn
        # seam. Runtime identity and operator-channel rules are separate typed
        # layers; soul/memory continue to ride their provenance file rows so token
        # accounting has one owner and never double-counts.
        # SOUL.md / workspace-AGENTS.md rows get their pasted-part chars; config.yaml
        # gets a deliberate 0. .skills_prompt_snapshot.json is attached post-turn.
        self.soul_prompt_chars = _soul_overlay_prompt_chars(self.persona)
        workspace_prompt_chars = _workspace_agents_prompt_chars(self.workspace_agents)
        self.memory_loaded = _mission_chat_memory_loaded(self.persona)
        self.context_files = [
            *_profile_context_files(self.profile),
            *([self.workspace_agents.receipt] if self.workspace_agents is not None else []),
        ]
        _attach_context_file_prompt_contributions(
            self.context_files,
            soul_chars=self.soul_prompt_chars,
            workspace_chars=workspace_prompt_chars,
            memory_loaded=self.memory_loaded,
        )

    @property
    def soul_loaded(self) -> bool:
        return self.soul_prompt_chars is not None

    @property
    def display_name(self) -> str:
        return safe_assignment_text(getattr(self.persona, "display_name", None), limit=120) or self.persona_id

    @property
    def hud_loaded(self) -> bool:
        return bool(isinstance(self.situational_hud, dict) and self.situational_hud)

    def row(self) -> dict[str, Any]:
        return {
            **self._identity_fields(),
            "prompt_layers": [
                *self._core_layers(),
                *self._persona_layers(),
                *self._session_layers(),
                *self._context_layers(),
            ],
            **self._skill_fields(),
            **self._turn_fields(),
        }

    def _identity_fields(self) -> dict[str, Any]:
        chat, surface, situational_hud = self.chat, self.surface, self.situational_hud
        return {
            "context_id": self.context_id,
            "prompt_mode": self.prompt_mode,
            "persona_id": self.persona_id,
            "persona_instance_id": safe_assignment_token(self.persona_instance_id),
            "profile": self.profile,
            "display_name": self.display_name,
            "role": safe_assignment_token(getattr(self.persona, "role", None)) or "agent",
            "session_id": safe_assignment_text(self.session_id, limit=200),
            "chat_id": chat.get("id"),
            "chat_title": chat.get("title"),
            "chat_name": chat.get("name"),
            "chat": chat,
            "task_id": safe_assignment_token(self.task_id),
            "goal_id": safe_assignment_token(self.goal_id),
            # The full runtime situational HUD (runtime · scope · mission · lane ·
            # roster · mission_hud) — the single projection the operator's runtime
            # HUD strip and the agent's mission-chat turn both render, so operator
            # and agent share one view. Empty until threaded (snapshot path); the
            # chat lane feeds the same projection into the model. See runtime_hud.py.
            "situational_hud": situational_hud if isinstance(situational_hud, dict) else {},
            "situational_hud_revision": safe_assignment_token(self.situational_hud_revision),
            "situational_hud_delivery": safe_assignment_token(self.situational_hud_delivery),
            "workspace_id": safe_assignment_token(self.workspace_id),
            "workspace_name": safe_assignment_text(self.workspace_name, limit=120),
            "turn_id": safe_assignment_token(self.turn_id),
            "surface_prompt": surface,
            "surface_prompt_is_blank": surface == "",
            "limiting_wrapper_active": bool(self.limiting_wrapper_active),
            "prompt_stack_schema_version": 2,
        }

    def _core_layers(self) -> list[dict[str, Any]]:
        runtime_identity_content = _mission_chat_identity_prompt_content(self.persona)
        runtime_identity_chars = _mission_chat_identity_prompt_chars(self.persona)
        return [
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
                "summary": f"Identifies this channel as {self.display_name}, names its Mission Control persona id, and prevents self-relay.",
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
        ]

    def _persona_layers(self) -> list[dict[str, Any]]:
        profile, soul_loaded, soul_prompt_chars = self.profile, self.soul_loaded, self.soul_prompt_chars
        soul_row = next((row for row in self.context_files if row.get("name") == "SOUL.md"), None)
        operator_rules_content = _mission_chat_operative_rules_content()
        operator_rules_chars = _mission_chat_operative_rules_chars()
        return [
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
                    if soul_loaded and soul_prompt_chars is not None and isinstance(soul_row, dict)
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
        ]

    def _session_layers(self) -> list[dict[str, Any]]:
        workspace_agents, surface = self.workspace_agents, self.surface
        return [
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
        ]

    def _context_layers(self) -> list[dict[str, Any]]:
        memory_loaded, history, hud_loaded = self.memory_loaded, self.history, self.hud_loaded
        return [
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
                "status": "loaded" if hud_loaded else "empty",
                "summary": (
                    "Live runtime, scope, mission, lane, and roster state added to the operator's user turn."
                    if hud_loaded
                    else "No runtime situation resolved for this turn."
                ),
                "owner": "mission_control",
                "group": "runtime_context",
                "order": 90,
                "injection_location": "user_turn",
                "included": hud_loaded,
                "token_attribution": "final_model_input",
                # Its bytes ride in the operator user-turn message
                # (``final_model_input`` messages), so this layer carries no
                # per-layer token estimate — the launcher already counts them via
                # that message and would otherwise double-count the HUD.
            },
        ]

    def _skill_fields(self) -> dict[str, Any]:
        return {
            "context_files": self.context_files,
            "used_skills": self.used_skills,
            "queued_skills": self.queued_names,
            "required_preload_skills": self.required_names,
            "preloaded_skills_loaded": self.loaded_names,
            "preloaded_skills_missing": self.missing_names,
            "skill_manifest_hash": self.skill_manifest_hash,
            "skill_assignment_removals": self.skill_assignment_removals,
            # C1 RECORD-ONCE (2026-07-17): the built row carries ONE copy of each
            # fact — the pre-C1 alias keys (``skills_catalog`` ≡ available_skills,
            # ``skills`` ≡ accessible_skills) are DELETED, no compat emission
            # (ruling 0). Readers were audited and retargeted to the canonical two;
            # legacy persisted rows that still carry the aliases are normalized at
            # the read/persist boundaries.
            "accessible_skills": self.accessible_skills,
            "available_skills": self.available_skills,
            "chat_history_context": self.history,
            "retrieval_context": [],
        }

    def _turn_fields(self) -> dict[str, Any]:
        persona, surface, workspace_agents = self.persona, self.surface, self.workspace_agents
        return {
            "final_model_input": _safe_final_model_input(self.final_model_input),
            "model_selection": _safe_model_selection(self.model_selection),
            # What this ONE operator message actually burned, metered per API call
            # and summed over the turn's tool loop. Distinct from context_budget,
            # which is the size of the assembled context for a single call — the
            # two were conflated, which is how a 6K inspector sat next to a 13K bill.
            "turn_usage": _safe_turn_usage(self.turn_usage),
            "context_budget": _context_budget(self.model_selection, self.final_model_input, self.turn_usage),
            "prompt_flags": {
                "skip_context_files": not bool(getattr(persona, "include_core_context_files", False)),
                "skip_memory": not _mission_chat_memory_loaded(persona),
                # Legacy profile-runner flag: this lane does not ask Hermes core to
                # substitute SOUL as its base identity. The independently assembled
                # profile_soul layer below is the authoritative overlay signal.
                "load_soul_identity": False,
                "soul_overlay_loaded": self.soul_loaded,
                "profile_memory_loaded": self.memory_loaded,
                "surface_prompt_blank": surface == "",
                "limiting_wrapper_active": bool(self.limiting_wrapper_active),
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
            PROMPT_OBSERVABILITY_TIMINGS_KEY: self.observability_timings,
        }
