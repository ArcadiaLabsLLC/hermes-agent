"""Model controls on the existing instance and chat-session stores."""
from __future__ import annotations

from contextlib import closing, contextmanager
from types import SimpleNamespace

from . import chat_session_scope, paths
from .chat_turn_reservations import unsettled_chat_receipts
from .config import load_agent_runtime_config
from .conversation_owner import require_session_owner
from .mission_chat_turns.reads import mission_chat_turn_records
from .mission_chat_turns.states import INFLIGHT_TURN_STATES, SETTLING_TURN_STATES
from .operator_conversation import OperatorConversationRefused
from .operator_session_inspection import (
    _inspection_persona, inspect_operator_settings, operator_session_read,
)
from .persona_assignments import PersonaInstanceStore
from .persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from .persona_chat_continuity.lease import PersonaChatBusyError, persona_chat_root_lease
from .persona_chat_session import _persist_chat_model_override
from .profile_context import persona_profile_scope, resolve_persona_profile
from .session_model_catalog import choices, facts, model_key

__layer__ = "lanes"


@contextmanager
def _model_profile(instance):
    persona = _inspection_persona(instance, load_agent_runtime_config())
    binding = resolve_persona_profile(persona)
    if binding.readiness != "ready":
        raise OperatorConversationRefused("profile_unavailable")
    with persona_profile_scope(binding, runtime_root=paths.store_root()):
        yield


def operator_model_inventory(instance) -> dict:
    from hermes_cli.inventory import build_model_options_payload, load_picker_context

    with _model_profile(instance):
        return build_model_options_payload(load_picker_context())


def _selected_model(instance, choice: str) -> tuple[str, str, str]:
    from hermes_cli.inventory import build_model_options_payload, load_picker_context
    from hermes_cli.model_switch import switch_model

    with _model_profile(instance):
        context = load_picker_context()
        selection = choices(build_model_options_payload(context)).get(choice)
        if selection is None:
            raise OperatorConversationRefused("model_unavailable")
        provider, model = selection
        result = switch_model(model, context.current_provider, context.current_model,
            current_base_url=context.current_base_url, explicit_provider=provider,
            user_providers=context.user_providers, custom_providers=context.custom_providers)
        if not result.success:
            raise OperatorConversationRefused("model_unavailable")
        return result.target_provider, result.new_model, result.api_mode


def operator_model_facts(params: dict) -> dict:
    from hermes_cli.config import is_managed

    with operator_session_read(params) as (instance, _):
        inventory = operator_model_inventory(instance)
    settings = inspect_operator_settings(params)
    model = settings["model"]
    provider, name = model["agent_provider"], model["agent_model"]
    projected = facts(params["session_id"], {"info": {
        "provider": model["effective_provider"], "model": model["effective_model"],
    }}, inventory)
    return {**settings, "facts": {
        **projected, "default_model_id": model_key(provider, name) if provider and name else None,
        "can_save_model_default": not is_managed(),
        "default_affects_inherited_sessions": True,
    }}


def _require_idle(session_id: str) -> None:
    protected = INFLIGHT_TURN_STATES | SETTLING_TURN_STATES
    if (any(turn["state"] in protected for turn in mission_chat_turn_records(session_id=session_id))
            or unsettled_chat_receipts(session_id)
            or PersonaChatClarifyTicketStore().open_ticket_for_session(session_id)):
        raise OperatorConversationRefused("conversation_busy")


def select_operator_model(params: dict) -> dict:
    scope, choice = params.get("scope"), params.get("model_id")
    if scope not in ("conversation", "agent_default") or not isinstance(choice, str):
        raise OperatorConversationRefused("invalid_model_selection")
    with operator_session_read(params) as (instance, _):
        _require_idle(params["session_id"])
        selection = _selected_model(instance, choice)
    try:
        with persona_chat_root_lease(params["session_id"], observer_kind="model_selection"):
            _require_idle(params["session_id"])
            _write_model(params, selection, save_default=scope == "agent_default")
    except PersonaChatBusyError as exc:
        raise OperatorConversationRefused("conversation_busy") from exc
    return operator_model_facts(params)


def _write_model(params: dict, selection: tuple[str, str, str], *, save_default: bool) -> None:
    from hermes_cli.config import is_managed
    from hermes_cli.harness_parts.persona.chat_request import _requested_chat_model_override

    if save_default and is_managed():
        raise OperatorConversationRefused("managed_model_default")
    provider, model, api_mode = selection
    with operator_session_read(params) as (instance, session):
        scope = session.scope
    db = chat_session_scope.open_chat_session_db(scope, access=chat_session_scope.SessionDbAccess.WRITE)
    if db is None:
        raise OperatorConversationRefused("session_db_unavailable")
    with closing(db):
        require_session_owner(db.get_session(params["session_id"]), params.get("client_scope"))
        if save_default:
            PersonaInstanceStore().update_profile(instance.id, provider=provider,
                model=model, api_mode=api_mode, requested_by="operator")
        override = _requested_chat_model_override(SimpleNamespace(
            provider=None if save_default else provider, model=None if save_default else model,
            use_agent_default=save_default))
        _persist_chat_model_override(session_db=db, session_id=params["session_id"], override=override)
