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
from .profile_context import persona_profile_scope, resolve_persona_profile

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


def inspect_operator_skills(params: dict[str, Any]) -> dict[str, Any]:
    operation = params.get("operation")
    if operation not in ("list", "detail", "history"):
        raise OperatorConversationRefused("invalid_skill_operation")
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
    with persona_profile_scope(binding, runtime_root=paths.store_root()):
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
