"""Model controls on the existing instance and chat-session stores."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import UTC, datetime
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
from .persona_chat_session import (
    _chat_model_override_from_config, _persist_chat_model_override, _session_model_config,
    log_model_selection, reasoning_effort_label,
)
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
    effort = {"reasoning_effort": model["effective_reasoning_effort"],
              "reasoning_effort_source": model["reasoning_effort_source"],
              "reasoning_capabilities": model["reasoning_capabilities"]}
    provider, name = model["agent_provider"], model["agent_model"]
    projected = facts(params["session_id"], {"info": {
        "provider": model["effective_provider"], "model": model["effective_model"],
    }}, inventory)
    return {**settings, "facts": {
        **projected, "default_model_id": model_key(provider, name) if provider and name else None,
        "can_save_model_default": not is_managed(),
        "default_affects_inherited_sessions": True,
        "can_reset_model_override": True,
        "model_is_default": model["model_is_default"], **effort,
    }}


def operator_selected_model_facts(params: dict) -> dict:
    """Current and inherited selection facts without a provider inventory walk."""
    from hermes_cli.config import is_managed
    settings = inspect_operator_settings(params)
    model = settings["model"]
    provider, name = model["effective_provider"], model["effective_model"]
    default_provider, default_name = model["agent_provider"], model["agent_model"]
    return {**settings, "facts": {
        "session_id": params["session_id"],
        "current_model_id": model_key(provider, name) if provider and name else None,
        "default_model_id": model_key(default_provider, default_name)
                            if default_provider and default_name else None,
        "can_save_model_default": not is_managed(),
        "default_affects_inherited_sessions": True,
        "can_reset_model_override": True,
        "model_is_default": model["model_is_default"],
        "reasoning_effort": model["effective_reasoning_effort"],
        "reasoning_effort_source": model["reasoning_effort_source"],
        "reasoning_capabilities": model["reasoning_capabilities"],
    }}


def _require_idle(session_id: str) -> None:
    protected = INFLIGHT_TURN_STATES | SETTLING_TURN_STATES
    if (any(turn["state"] in protected for turn in mission_chat_turn_records(session_id=session_id))
            or unsettled_chat_receipts(session_id)
            or PersonaChatClarifyTicketStore().open_ticket_for_session(session_id)):
        raise OperatorConversationRefused("conversation_busy")


#: Where each scope's choice lands: the chat's SessionDB row, or the instance
#: store with this chat's override cleared so the new default is what it runs.
_SAVED = {"conversation": "session_override",
          "agent_default": "persona_instance_store+session_override_cleared"}


def _receipt_choice(params: dict) -> str | None:
    model_id = params.get("model_id") if isinstance(params.get("model_id"), str) else None
    effort = params.get("reasoning_effort")
    if not isinstance(effort, str):
        return model_id
    return f"{model_id or '-'},effort={effort or 'inherit'}"


def select_operator_model(params: dict) -> dict:
    receipt = dict(verb="runtime.operator.conversation.model.select",
                   target=params.get("session_id"), scope=str(params.get("scope") or "-"),
                   chosen=_receipt_choice(params))
    try:
        facts = _select_operator_model(params)
    except Exception as exc:
        reason = getattr(exc, "reason", None) or type(exc).__name__
        log_model_selection(**receipt, outcome=f"refused:{reason}", saved=None)
        raise
    saved = "session_override_cleared" if params.get("use_agent_default") is True else _SAVED[params["scope"]]
    log_model_selection(**receipt, outcome="applied", saved=saved)
    return facts


def _chat_effort_request(params: dict) -> str | None:
    """The chat-tier effort a selection carries: a level, ``""`` (inherit), or ``None`` (absent).

    One chat can run quick and another deep without moving their agent default, so an effort
    is a CONVERSATION choice only, and it travels alone (``model_id`` absent): the levels it is
    checked against are the chat's current model's (``reasoning_capabilities``)."""
    if "reasoning_effort" not in params:
        return None
    effort = params["reasoning_effort"]
    if (not isinstance(effort, str) or params.get("scope") != "conversation"
            or params.get("model_id") is not None or params.get("use_agent_default", False) is not False):
        raise OperatorConversationRefused("invalid_model_selection")
    return effort.strip().lower()


def _check_chat_effort(params: dict, effort: str) -> None:
    if not effort:
        return
    capabilities = inspect_operator_settings(params)["model"]["reasoning_capabilities"]
    if capabilities.get("state") == "unsupported":
        raise OperatorConversationRefused("reasoning_unsupported")
    levels = capabilities.get("levels")
    if capabilities.get("state") == "supported" and levels:
        allowed = set(levels)
    else:
        from hermes_constants import VALID_REASONING_EFFORTS
        allowed = {"none", *VALID_REASONING_EFFORTS}
    if effort not in allowed:
        raise OperatorConversationRefused("invalid_reasoning_effort")


def _select_operator_model(params: dict) -> dict:
    effort = _chat_effort_request(params)
    if effort is not None:
        return _select_chat_effort(params, effort)
    scope, choice = params.get("scope"), params.get("model_id")
    inherit = params.get("use_agent_default", False)
    if type(inherit) is not bool or scope not in ("conversation", "agent_default"):
        raise OperatorConversationRefused("invalid_model_selection")
    if inherit and (scope != "conversation" or choice is not None):
        raise OperatorConversationRefused("invalid_model_selection")
    if not inherit and not isinstance(choice, str):
        raise OperatorConversationRefused("invalid_model_selection")
    with operator_session_read(params) as (instance, _):
        _require_idle(params["session_id"])
        selection = None if inherit else _selected_model(instance, choice)
    try:
        with persona_chat_root_lease(params["session_id"], observer_kind="model_selection"):
            _require_idle(params["session_id"])
            _write_model(params, selection, save_default=scope == "agent_default", use_agent_default=inherit)
    except PersonaChatBusyError as exc:
        raise OperatorConversationRefused("conversation_busy") from exc
    return operator_model_facts(params)


def _select_chat_effort(params: dict, effort: str) -> dict:
    with operator_session_read(params):
        _require_idle(params["session_id"])
    _check_chat_effort(params, effort)
    try:
        with persona_chat_root_lease(params["session_id"], observer_kind="model_selection"):
            _require_idle(params["session_id"])
            with _owned_session_db(params) as db:
                _persist_chat_model_override(session_db=db, session_id=params["session_id"],
                                             override=_with_chat_effort(db, params["session_id"], effort or None))
    except PersonaChatBusyError as exc:
        raise OperatorConversationRefused("conversation_busy") from exc
    return operator_model_facts(params)


def _with_chat_effort(db, session_id: str, effort: str | None, base: dict | None = None) -> dict:
    """The chat override with *effort* as its effort tier; *base* (default: the stored override)
    keeps its model tier. A result naming nothing clears the override."""
    if base is None:
        base = _chat_model_override_from_config(_session_model_config(db, session_id)) or {}
    if not (base.get("provider") or base.get("model") or effort):
        return {"schema_version": 1, "clear": True}
    return {"schema_version": 1, "provider": base.get("provider"), "model": base.get("model"),
            "reasoning_effort": effort, "source": "operator", "scope": "mission_control_chat_session",
            "updated_at": datetime.now(UTC).isoformat()}


@contextmanager
def _owned_session_db(params: dict):
    with operator_session_read(params) as (_, session):
        scope = session.scope
    db = chat_session_scope.open_chat_session_db(scope, access=chat_session_scope.SessionDbAccess.WRITE)
    if db is None:
        raise OperatorConversationRefused("session_db_unavailable")
    with closing(db):
        require_session_owner(db.get_session(params["session_id"]), params.get("client_scope"))
        yield db


def _write_model(params: dict, selection: tuple[str, str, str] | None, *, save_default: bool,
                 use_agent_default: bool = False) -> None:
    from hermes_cli.config import is_managed
    from hermes_cli.harness_parts.persona.chat_request import _requested_chat_model_override

    if save_default and is_managed():
        raise OperatorConversationRefused("managed_model_default")
    provider, model, api_mode = selection if selection is not None else (None, None, None)
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
        inherit = save_default or use_agent_default
        override = _requested_chat_model_override(SimpleNamespace(
            provider=None if inherit else provider, model=None if inherit else model,
            use_agent_default=inherit))
        if save_default:
            # Saving the agent default clears this chat's MODEL tier; its own effort stays
            # (a chat model pick keeps it in _persist_chat_model_override; only "use the agent
            # default" resets both).
            kept = _chat_model_override_from_config(_session_model_config(db, params["session_id"])) or {}
            if kept.get("reasoning_effort"):
                override = _with_chat_effort(db, params["session_id"], kept["reasoning_effort"], base={})
        _persist_chat_model_override(session_db=db, session_id=params["session_id"], override=override)
