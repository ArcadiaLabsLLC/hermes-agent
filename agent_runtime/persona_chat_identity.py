"""Pure field projections for resident persona-chat identity."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from typing import Any

from .cli_format import emit_json

__layer__ = "policy"


def revision_hash(value: Any) -> str:
    return hashlib.sha256(emit_json(value).encode("utf-8")).hexdigest()


def _as_plain(value: Any) -> Any:
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else value


# ── actor identity vs. row liveness ──────────────────────────────────────────
#
# ``mission_chat_runtime_signature`` is a REUSE key: two turns share an actor only
# when every input that decides what that actor IS is identical. It used to fold
# ``asdict(persona)`` and ``asdict(instance)`` whole, which quietly made it a key
# over the ROWS rather than over the actor — and a persona-instance row is
# written on chat activity.
#
# **Live receipt (2026-08-23T14:45:14Z).** The operator turned
# ``persona_chat.hot_sessions`` on and restarted the serve, so the resident-actor
# registry finally existed. The SECOND message of one neko chat, ~45 s after the
# first, with no persona / config / permission change between them, recorded
# ``resident_rebuild_runtime_signature_changed`` and ``resident_actor_reused=0``.
# The instance row had moved: ``state`` flips busy→idle across a turn,
# ``updated_at`` and ``last_heartbeat_at`` are stamped on every write, and the
# mission-chat handler itself writes ``skill_manifest_hash`` back onto the
# instance at the end of each turn. So the key could never match twice and hot
# sessions bought nothing at all.
#
# Both lists are ALLOWLISTS, not denylists, and that is the point: a new field on
# either record is presumed bookkeeping until someone decides it changes the
# actor and names it here. A denylist inverts the default and re-opens this
# defect on the next field anyone adds.
#
# A name that is not on the record at all is recorded as ABSENT rather than
# defaulted, so a record shape that LOSES a field cannot hash identical to one
# that carries it set to ``None``.

#: Persona fields that decide what a constructed actor is: its identity and
#: prompt material, its provider/model triple, its tool surface, its skills, its
#: profile binding and its budgets. ``readiness`` is deliberately absent — it is
#: a stored report ABOUT the persona, refreshed by readiness passes, and nothing
#: an actor is built from reads it.
PERSONA_IDENTITY_FIELDS: tuple[str, ...] = (
    "api_mode",
    "autonomy",
    "display_name",
    "hermes_profile",
    "id",
    "include_core_context_files",
    "include_profile_memory",
    "iteration_budget",
    "max_api_calls",
    "max_total_tokens",
    "max_wall_seconds",
    "model",
    "model_override_issued_at",
    "provider",
    "repo_scope",
    "repo_scope_label",
    "required_mcp_servers",
    "role",
    "schema_version",
    "skills",
    "soul_overlay_path",
    "system_prompt_path",
    "toolsets",
)

#: Instance fields that decide what a constructed actor is: which persona and
#: profile it places, where it is placed, and the per-instance model-override
#: tier (``set-model`` writes ``model`` / ``provider`` / ``api_mode`` /
#: ``reasoning_effort`` / ``model_override_issued_at`` together, so all five are
#: here and a real override change still rotates the key).
#:
#: Everything else is liveness or routing and is deliberately absent:
#: ``state`` / ``updated_at`` / ``last_heartbeat_at`` / ``token_budget_used``
#: (stamped by activity), ``skill_manifest_hash`` (written back by the turn that
#: just ran), ``active_run_id`` / ``current_assignment_id`` / ``current_task_id``
#: (run bookkeeping), the chat pointers ``default_chat_session_id`` /
#: ``session_id`` / ``chat_head_home`` (the chat root is already in the signature
#: as ``root``), and the graph edges ``spawned_by`` / ``steered_by`` /
#: ``returned_to`` / ``goal_id`` (they render into the HUD, which rides the
#: volatile tail and is therefore not part of the cached actor at all).
#:
#: ``current_chat_goal`` was here and is not any more (2026-08-23), by that same
#: last rule read consistently: its only readers are the chat-list TITLE
#: (``persona_chat_history``) and the operator projections / situational HUD, and
#: the HUD reaches the model as per-turn ENVELOPE content, never as anything the
#: agent factory is called with. A ``persona instance steer --goal`` therefore
#: changes what the next turn SAYS, not what its actor IS — and paying a full
#: rebuild for it was the same category error ``goal_id``'s exclusion already
#: names one line above.
INSTANCE_IDENTITY_FIELDS: tuple[str, ...] = (
    "api_mode",
    "display_name",
    "id",
    "mode",
    "model",
    "model_override_issued_at",
    "persona_id",
    "profile_id",
    "provider",
    "realm_id",
    "reasoning_effort",
    "role",
    "runtime_root",
    "schema_version",
    "skill_overrides",
    "workspace_id",
)


def identity_revision(value: Any, fields: tuple[str, ...]) -> str:
    """Hash a record's ACTOR-IDENTITY projection. See the note above."""

    plain = _as_plain(value)
    source = plain if isinstance(plain, dict) else None
    projected: dict[str, Any] = {}
    absent: list[str] = []
    missing = object()
    for name in fields:
        if source is not None:
            if name in source:
                projected[name] = source[name]
            else:
                absent.append(name)
            continue
        found = getattr(value, name, missing)
        if found is missing:
            absent.append(name)
        else:
            projected[name] = found
    return revision_hash({"fields": projected, "absent": absent})


# ── the permission projection the ACTOR is built from ────────────────────────
#
# ``permission_state_for_chat`` answers the OPERATOR's question ("what may this
# chat do, spelled out"): a resolved ``blocked_tools`` entry list, ``workdir``,
# ``repo_scope``, ``can_run_terminal`` / ``can_mutate_files``, and the grant's
# ``expires_at`` / ``turns_remaining`` counters. None of that reaches the agent
# factory. ``ProfileAgentRunner._execute_agent_run`` builds an actor from
# ``enabled_toolsets`` and ``blocked_tool_names`` — which this signature already
# carries VERBATIM as ``tool_contract``, composed from the same one bundle
# resolve — plus scopes derived from the permission MODE.
#
# So the whole projection in the key was the row-liveness defect of
# ``7f2c82f090`` wearing different clothes. Under the shipped default permission
# mode (``unbounded``: ``SHIPPED_DEFAULT_PERMISSION_MODE``) the resolved
# ``blocked_tools`` list is computed over EVERY tool registered in the process,
# so in a warm multi-persona ``harness serve`` it moves whenever anything
# registers or deregisters — another persona's MCP admission, a profile
# bootstrap's plugin pass — none of which changes what THIS chat's actor is.
#
# What stays is what decides the constructed actor and is not already stated by
# ``tool_contract``: the mode itself (it selects the admission mode, the
# terminal-envelope scope and the toolset resolution), where the mode came from,
# and whether the grant behind it has lapsed. ``turns_remaining`` decrementing
# 5 → 4 changes nothing about the actor; the turn it reaches 0 flips ``expired``,
# which is here, so the key still rotates exactly when the answer changes.
_ACTOR_PERMISSION_FIELDS: tuple[str, ...] = ("mode", "source", "expired")


def actor_permission_identity(state: Any) -> dict[str, Any]:
    """The permission facts a CONSTRUCTED actor depends on. See the note above."""

    source = state if isinstance(state, dict) else {}
    return {name: source.get(name) for name in _ACTOR_PERMISSION_FIELDS}


# ── the config projection: an AMBIENT document is not an actor fact ───────────
#
# ``relevant_config_revision`` used to be ``revision_hash(_as_plain(config))`` —
# the WHOLE loaded ``AgentRuntimeConfig``. That is the row-liveness defect of
# ``7f2c82f090`` and the permission defect of ``14271f261f`` in a third costume,
# with one extra edge: the config object is not merely wider than the actor, it
# is AMBIENT.
#
# **Live receipt (2026-08-23T21:38:29Z)**, root
# ``persona_chat_personainst_neko_supervisor_agent_f6f7a51b_66a438245225``:
# ``resident_signature_diff … components=relevant_config_revision`` — and again
# at 21:39:07, 21:39:19, 21:40:36, 21:40:40. EVERY turn of that chat rebuilt its
# actor on this ONE component, while no config file was written in the window
# (root ``config.yaml`` hours older, the profile's days older) and the loader
# hashes a static file identically twice in one process and across two.
#
# What moved was not the file — it was WHICH FILE.
# ``load_agent_runtime_config()`` resolves ``get_hermes_home()/config.yaml``,
# and with no context-local override on the turn's thread that is the
# process-global ``HERMES_HOME``. ``profile_context.persona_profile_context``
# rewrites that variable for the duration of a profile binding (its own
# docstring states the invariant: sound only while runs are serialized by
# ``profile_runner._WORKDIR_LOCK``), and the readiness walk behind every
# snapshot build enters it once per persona — in the serve process that also
# hosts chat turns, on another thread, every few seconds. So the document a turn
# hashed was whichever profile the walk was standing in when the turn happened
# to look, and two turns of one unchanged chat could not agree.
#
# The rule that answers it is the one this module already applies twice: key on
# what the ACTOR IS, via an ALLOWLIST, and let a resolved component speak for
# every input it already states.
#
#: Config fields an actor's CONSTRUCTION consumes and that no other component
#: already states. It is EMPTY, and that is a finding rather than a stub — the
#: audit, block by block, of what ``_construct_agent`` (``profile_runner``) is
#: actually called with:
#:
#: * ``default_provider`` / ``default_model`` / ``default_api_mode`` — reach the
#:   factory only through the model cascade, already keyed as ``provider`` /
#:   ``model`` / ``api_mode`` / ``reasoning_effort``.
#: * ``personas.<id>.*`` — resolved into the persona record before anything is
#:   built, already keyed as ``persona_revision``.
#: * ``store_root`` — already keyed as ``runtime_root``.
#: * ``tool_permissions.default_mode`` — reaches the actor as the RESOLVED lane
#:   mode, already keyed as ``permissions.mode``.
#: * ``mcp_admission`` and the chat-lane toolset knobs
#:   (``personas.<id>.chat_lane_restore_toolsets``) — folded into the bundle's
#:   ``enabled_toolsets`` / ``blocked_tool_names`` by the SAME resolve the run
#:   builds from (``chat_lane_bundle``: admission is an input to
#:   ``_enabled_toolsets_for_chat``), already keyed verbatim as
#:   ``tool_contract``.
#: * ``terminal_envelope.grants`` — the run BINDS a scope per turn
#:   (``profile_runner``: ``terminal_envelope_scope(request.…)``); nothing about
#:   it is baked into the agent object.
#: * ``mission_chat.*`` — per-turn budgets. The compaction cap is re-applied on
#:   every turn INCLUDING a reused actor's (``profile_runner``, the
#:   ``root_chat_session_id`` block runs after the registry hands one back), so
#:   it cannot be stale on a resident actor.
#: * ``persona_chat.*`` — the registry's own policy. It decides whether an actor
#:   is resident at all, never what one IS.
#: * ``read_model`` / ``event_log`` / ``supervision`` /
#:   ``coordinator_permissions`` / ``redaction_mode`` /
#:   ``lock_acquire_timeout_seconds`` / ``schema_version`` — no reader anywhere
#:   in an actor's construction.
#:
#: Empty is therefore the complete answer, not a shortcut, and it is the only
#: answer that also holds while the process is briefly pointed at another
#: profile: any non-empty projection of an AMBIENT document can still move for a
#: reason that has nothing to do with this chat. A field that genuinely decides
#: what an actor IS goes here by name, and the key rotates on it again —
#: ``test_a_NAMED_actor_config_field_still_rotates_the_key`` witnesses that the
#: mechanism is live rather than decorative.
ACTOR_CONFIG_IDENTITY_FIELDS: tuple[str, ...] = ()
