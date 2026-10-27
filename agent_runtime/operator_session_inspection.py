"""Session inspection through the native model, history and skill authorities."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

from . import paths
from .config import ensure_persisted_personas, load_agent_runtime_config
from .models import AgentPersona, PersonaInstance, apply_instance_model_overrides
from .config.schema import AgentRuntimeConfig
from .operator_conversation import OperatorConversationRefused, exact_operator_target
from .persona_chat_history.messages import (
    ChatSessionReadRefused, ExistingChatSession, existing_chat_session,
)
from .persona_chat_history.history_rows import _lineage_aggregate, _token_usage_fields
from .persona_chat_session import (
    _chat_effective_model_payload, _chat_model_override_from_config,
    _persona_chat_native_history, _persona_chat_native_tip, _session_model_config,
)
from .profile_context import persona_profile_context, resolve_persona_profile

__layer__ = "lanes"


@contextmanager
def operator_session_read(params: dict[str, Any]) -> Iterator[tuple[PersonaInstance, ExistingChatSession]]:
    instance = exact_operator_target(params)
    try:
        with existing_chat_session(session_id=params["session_id"],
                                   client_scope=params.get("client_scope")) as session:
            yield instance, session
    except ChatSessionReadRefused as exc:
        raise OperatorConversationRefused(exc.envelope["error_kind"]) from exc


def inspection_identity(params: dict[str, Any], owner: str | None) -> dict[str, Any]:
    return {**{key: params.get(key) for key in (
        "install_id", "workspace_id", "persona_id", "persona_instance_id", "session_id")},
        "client_scope": owner}


def inspect_operator_settings(params: dict[str, Any]) -> dict[str, Any]:
    with operator_session_read(params) as (instance, session):
        config = load_agent_runtime_config()
        persona = _inspection_persona(instance, config)
        override = _chat_model_override_from_config(
            _session_model_config(session.db, params["session_id"]))
        tip = _persona_chat_native_tip(session.db, params["session_id"])
        usage = _lineage_aggregate(session.db, root_session_id=params["session_id"],
                                   active_session_id=tip)
        return {
            **inspection_identity(params, session.owner),
            "model": _chat_effective_model_payload(persona=persona, config=config,
                                                   override=override, instance=instance),
            "usage": _token_usage_fields({**session.row, **usage}),
        }


def _inspection_persona(instance: PersonaInstance, config: AgentRuntimeConfig) -> AgentPersona:
    persona = next((row for row in ensure_persisted_personas(config)
                    if row.id == instance.persona_id), None)
    if persona is None:
        raise OperatorConversationRefused("agent_unavailable")
    return persona


def inspect_operator_permissions(params: dict[str, Any]) -> dict[str, Any]:
    """Read the existing permission authority without activating a chat or consuming a grant."""
    from .tool_permissions import permission_state_for_chat

    with operator_session_read(params) as (instance, session):
        persona = _inspection_persona(instance, load_agent_runtime_config())
        binding = resolve_persona_profile(persona)
        if binding.readiness != "ready":
            raise OperatorConversationRefused("profile_unavailable")
        with persona_profile_context(binding, runtime_root=paths.store_root()):
            facts = permission_state_for_chat(persona, session_id=params["session_id"])
        return {**inspection_identity(params, session.owner), "permission_state": facts}


def inspect_operator_skills(params: dict[str, Any]) -> dict[str, Any]:
    """The conversation's skills; with ``child_ref`` (or for ``lend``) the addressed worker child's."""
    from .subagents.params import SKILLS_OPERATIONS

    operation = params.get("operation")
    if operation not in SKILLS_OPERATIONS:
        raise OperatorConversationRefused("invalid_skill_operation")
    if params.get("child_ref") is not None or operation == "lend":
        from .subagents.operator import inspect_operator_child_skills

        return inspect_operator_child_skills(operation, params)
    with operator_session_read(params) as (instance, session):
        if operation == "history":
            data = _operator_skill_history(session.db, params["session_id"])
        else:
            persona = _inspection_persona(instance, load_agent_runtime_config())
            persona = apply_instance_model_overrides(persona, instance)
            tip = _persona_chat_native_tip(session.db, params["session_id"])
            current = session.db.get_session(tip) or session.row
            data = _operator_skill_document(persona, params, cwd=current.get("cwd"))
        return {**inspection_identity(params, session.owner), **data}


def _operator_skill_document(persona: AgentPersona, params: dict[str, Any], *, cwd: str | None) -> dict[str, Any]:
    from agent.runtime_cwd import reset_session_cwd, set_session_cwd
    from .chat_lane_scope import apply_chat_lane_tool_scope
    from .skill_inspection import skill_inspection_reader
    from .tool_permissions import permission_options_for_chat
    from .tool_visibility import resolve_tool_visibility

    binding = resolve_persona_profile(persona)
    if binding.readiness != "ready":
        raise OperatorConversationRefused("profile_unavailable")
    with persona_profile_context(binding, runtime_root=paths.store_root()):
        options = permission_options_for_chat(persona, session_id=params["session_id"])
        options = apply_chat_lane_tool_scope(persona, options, session_id=params["session_id"])
        visibility = resolve_tool_visibility(persona, options, include_readiness=False)
        can_load = "skill_view" in visibility["final_model_tools"]
        workdir = options.mission_chat_workdir
        token = set_session_cwd(cwd or (workdir.path if workdir else None))
        try:
            reader = skill_inspection_reader()
            if params["operation"] == "list":
                return {"skills": reader.catalog(can_load=can_load)}
            identifier = params.get("skill_id")
            if not isinstance(identifier, str) or not identifier or len(identifier) > 512:
                raise OperatorConversationRefused("invalid_skill_id")
            return {"skill": reader.detail(identifier, can_load=can_load)}
        finally:
            reset_session_cwd(token)


def _operator_skill_history(db: Any, session_id: str) -> dict[str, Any]:
    from .chat_turn_reservations import unsettled_chat_receipts
    from .mission_chat_turns.reads import mission_chat_turn_records
    from .mission_chat_turns.states import INFLIGHT_TURN_STATES, SETTLING_TURN_STATES
    from .skill_activity import skill_load_history

    tip = _persona_chat_native_tip(db, session_id)
    history = _persona_chat_native_history(db, tip)
    unsettled = any(turn["state"] in INFLIGHT_TURN_STATES | SETTLING_TURN_STATES
                    for turn in mission_chat_turn_records(session_id=session_id))
    return {"loaded": skill_load_history(history),
            "historyComplete": not unsettled and not unsettled_chat_receipts(session_id)}


_MEMORY_PENDING_KEYS = ("id", "action", "summary", "origin", "created_at")


def inspect_operator_memory(params: dict[str, Any]) -> dict[str, Any]:
    """What the conversation's persona remembers, read from its own profile home.

    Read-only: no store mutation, no pending write applied or discarded. ``on_lane``
    says whether this persona's turns load that memory at all
    (``include_profile_memory``); the stores are read either way so a console can
    show what a turn would see once it is switched on."""
    with operator_session_read(params) as (instance, session):
        persona = _inspection_persona(instance, load_agent_runtime_config())
        binding = resolve_persona_profile(persona)
        if binding.readiness != "ready":
            raise OperatorConversationRefused("profile_unavailable")
        with persona_profile_context(binding, runtime_root=paths.store_root()):
            document = _memory_document()
        return {**inspection_identity(params, session.owner),
                "memory": {"on_lane": bool(persona.include_profile_memory), **document}}


def _memory_document() -> dict[str, Any]:
    from tools import write_approval
    from tools.memory_tool import ENTRY_DELIMITER, load_on_disk_store

    store = load_on_disk_store()
    stores = [{"target": target, "enabled": store.target_enabled(target), "entries": list(entries),
               "char_count": len(ENTRY_DELIMITER.join(entries)),
               "char_limit": limit}
              for target, entries, limit in (("memory", store.memory_entries, store.memory_char_limit),
                                             ("user", store.user_entries, store.user_char_limit))]
    pending = [{**{key: record.get(key) for key in _MEMORY_PENDING_KEYS},
                "target": (record.get("payload") or {}).get("target")}
               for record in write_approval.list_pending(write_approval.MEMORY)]
    return {"stores": stores, "write_approval": {
        "enabled": write_approval.write_approval_enabled(write_approval.MEMORY), "pending": pending}}
