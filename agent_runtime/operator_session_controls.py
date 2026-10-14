"""Exact-owner reads and writes for a conversation's native execution settings."""
from __future__ import annotations

from . import paths
from .config import load_agent_runtime_config
from .operator_conversation import OperatorConversationRefused
from .operator_session_inspection import (
    inspection_identity, inspect_operator_settings, operator_session_read, _inspection_persona,
)
from .operator_session_models import _require_idle
from .persona_chat_continuity.lease import PersonaChatBusyError, persona_chat_root_lease
from .profile_context import persona_profile_scope, resolve_persona_profile
from .session_control_store import SessionControlStore
from .session_controls import pending_session_approvals, resolved_session_controls

__layer__ = "lanes"


def operator_control_facts(params: dict) -> dict:
    selection = inspect_operator_settings(params)["model"]
    with operator_session_read(params) as (instance, session):
        persona = _inspection_persona(instance, load_agent_runtime_config())
        binding = resolve_persona_profile(persona)
        if binding.readiness != "ready":
            raise OperatorConversationRefused("profile_unavailable")
        with persona_profile_scope(binding, runtime_root=paths.store_root()):
            from hermes_cli.config import load_config_readonly
            config_model = load_config_readonly().get("model") or {}
            base_url = getattr(instance, "base_url", None) or (config_model.get("base_url") if isinstance(config_model, dict) else None)
            controls = resolved_session_controls(params["session_id"],
                provider=selection["effective_provider"], model=selection["effective_model"], base_url=base_url,
                api_mode=selection["reasoning_capabilities"].get("api_mode"))
        return {**inspection_identity(params, session.owner), "controls": controls}


def set_operator_control(params: dict) -> dict:
    required = ("setting", "value", "expected_provider", "expected_model")
    if any(key not in params for key in required):
        raise OperatorConversationRefused("invalid_setting")
    key, value = params.get("setting"), params.get("value")
    if key not in ("approval_mode", "service_tier") or (value is not None and not isinstance(value, str)):
        raise OperatorConversationRefused("invalid_setting")
    # Validate the full owner before creating a lease or touching a settings path.
    with operator_session_read(params):
        pass
    try:
        with persona_chat_root_lease(params["session_id"], observer_kind="session_settings"):
            _require_idle(params["session_id"])
            facts = operator_control_facts(params)
            controls = facts["controls"]
            if (params.get("expected_provider"), params.get("expected_model")) != (controls["provider"], controls["model"]):
                raise OperatorConversationRefused("model_changed")
            section = controls["approval" if key == "approval_mode" else "speed"]
            if not section["writable"]:
                raise OperatorConversationRefused("setting_managed")
            if value is not None and value not in {row["id"] for row in section["options"]}:
                raise OperatorConversationRefused("setting_unavailable")
            SessionControlStore().update(params["session_id"], key, value)
    except PersonaChatBusyError as exc:
        raise OperatorConversationRefused("conversation_busy") from exc
    return operator_control_facts(params)


def operator_approval_facts(params: dict) -> dict:
    # This fast read never takes the runner's profile/workdir lock while it waits.
    with operator_session_read(params) as (instance, session):
        persona = _inspection_persona(instance, load_agent_runtime_config())
        binding = resolve_persona_profile(persona)
        with persona_profile_scope(binding, runtime_root=paths.store_root()):
            approvals = pending_session_approvals(params["session_id"])
        return {**inspection_identity(params, session.owner),
                "approvals": approvals}


def respond_operator_approval(params: dict) -> dict:
    from tools.approval import resolve_gateway_approval

    request_id, choice = params.get("approval_id"), params.get("choice")
    if not isinstance(request_id, str) or not request_id or choice not in ("once", "deny"):
        raise OperatorConversationRefused("invalid_approval_response")
    with operator_session_read(params) as (_, session):
        if resolve_gateway_approval(params["session_id"], choice, request_id=request_id) != 1:
            raise OperatorConversationRefused("approval_expired")
        return {**inspection_identity(params, session.owner), "approval_id": request_id,
                "choice": choice, "accepted": True}
