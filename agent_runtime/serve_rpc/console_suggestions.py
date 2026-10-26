"""Authenticated Console suggestion settings and exact-conversation methods."""
from functools import partial

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.console_suggestions.service import CHAT_PREFIX, SETTINGS_PREFIX, IDENTITY_KEYS
from agent_runtime.console_suggestions.settings import SuggestionRefused, suggestion_home
from agent_runtime.operator_conversation import OperatorConversationRefused
from .protocol import err, ok, defer_or_inline
from .registry import method

__layer__ = "lanes"


def _suggestion_answer(operation, rid, params, context):
    if context is None or context.console_suggestions is None:
        return err(rid, 4090, "Suggestions unavailable", {"reason": "service_unavailable"})
    try:
        service = context.console_suggestions()
        with suggestion_home(service.home):
            from agent_runtime import paths
            from agent_runtime.gateway_identity import read_install_identity

            if not operation.endswith("unsubscribe") and params.get("install_id") != read_install_identity(paths.store_root()).install_id:
                raise SuggestionRefused("installation_changed")
            result = _OPERATIONS[operation](service, context, params)
        return ok(rid, {**{key: value for key, value in result.items() if key != "attempt_key"},
                        **({"install_id": params["install_id"]} if "install_id" in params else {})})
    except (SuggestionRefused, OperatorConversationRefused) as exc:
        invalid = exc.reason.startswith("invalid_") or exc.reason in {"changes_required", "conversation_identity_required"}
        return err(rid, -32602 if invalid else 4090, "Suggestion request refused", {"reason": exc.reason})
    except Exception as exc:  # health: allow BLE001 -- RPC boundary returns a typed sanitized failure, never config or provider exception text
        return err(rid, -32000, "Suggestion request unavailable", {"reason": "service_unavailable", "error_class": type(exc).__name__})


def _subject(params):
    if any(not isinstance(params.get(key), str) or not params[key].strip()
           for key in ("install_id", "persona_id", "persona_instance_id", "session_id", "client_scope")):
        raise SuggestionRefused("conversation_identity_required")
    return {key: params.get(key) for key in IDENTITY_KEYS}


_OPERATIONS = {
    "settings.get": lambda service, context, params: service.settings_read(),
    "settings.set": lambda service, context, params: service.settings_write(params),
    "settings.subscribe": lambda service, context, params: service.subscribe(context),
    "settings.unsubscribe": lambda service, context, params: service.unsubscribe(context, params.get("subscription_id")),
    "chat.read": lambda service, context, params: service.read(_subject(params)),
    "chat.subscribe": lambda service, context, params: service.subscribe(context, _subject(params)),
    "chat.unsubscribe": lambda service, context, params: service.unsubscribe(context, params.get("subscription_id")),
    "chat.dismiss": lambda service, context, params: service.dismiss(_subject(params), params),
}


def _dispatch(operation, rid, params, context=None):
    prefix, verb = operation.split(".")
    name = (SETTINGS_PREFIX if prefix == "settings" else CHAT_PREFIX) + "." + verb
    return defer_or_inline(rid, name, context, partial(_suggestion_answer, operation, rid, params, context))


for _operation in _OPERATIONS:
    _prefix, _verb = _operation.split(".")
    method((SETTINGS_PREFIX if _prefix == "settings" else CHAT_PREFIX) + "." + _verb, tier=TIER_CONSOLE)(
        partial(_dispatch, _operation))
