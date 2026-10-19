"""``runtime.messaging.*`` — the messaging stores' verbs (p10-messaging §3 M1).

``status`` is ``read``; every write is ``console``; ``credential.set|clear`` are also in
``call_authorization.LOCAL_CONSOLE_METHODS`` — a bot token is written only from this machine's own
console, never by a paired device. Each verb is one row of :data:`OPS`; the bridge (M3) calls the same
service functions through :func:`execute`, so a platform-side ``/persona`` writes the binding the
launcher's verb writes. Answered inline: every op is one small file read or write.

The token never leaves: ``credential.set`` answers ``{"credential": "present"}``, ``status`` the same
word, the receipts carry the platform alone, and a crash answers a fixed sentence, never ``str(exc)``.
Refusals: ``invalid_request`` / ``unknown_platform`` / ``token_invalid`` (-32602), ``unknown_instance``
(4001), anything else ``messaging_unavailable`` (-32000), each with ``data.reason``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from ..call_authorization import TIER_CONSOLE, TIER_READ
from ..harness_settings import harness_setting
from ..serve_rpc.protocol import ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from ..work_store.receipts import emit
from . import credentials
from .bindings import Binding, BindingStore, chat_key, field_text
from .models import MessagingRefused, Platform, Reason, platform_of
from .operators import Operator, OperatorStore

__layer__ = "lanes"
__all__ = ["METHOD_PREFIX", "OPS", "TIERS", "execute", "register", "status"]

METHOD_PREFIX = "runtime.messaging."

REFUSAL_CODES: dict[Reason, int] = {
    Reason.INVALID: ERR_INVALID_PARAMS,
    Reason.UNKNOWN_PLATFORM: ERR_INVALID_PARAMS,
    Reason.TOKEN_INVALID: ERR_INVALID_PARAMS,
    Reason.UNKNOWN_INSTANCE: ERR_NOT_FOUND,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _instance_exists(instance_id: str) -> bool:
    try:
        from ..persona_assignments.store import PersonaInstanceStore

        return PersonaInstanceStore().get(instance_id) is not None
    except Exception:
        return False


def _optional_platform(params: Mapping[str, Any]) -> Platform | None:
    return platform_of(params["platform"]) if params.get("platform") else None


def status(_params: Mapping[str, Any], _by: str) -> dict[str, Any]:
    bindings, operators = BindingStore().list(), OperatorStore().list()
    return {
        "enabled": harness_setting("messaging_enabled", False) is True,
        "default_persona": harness_setting("messaging_default_persona", None) or None,
        "platforms": {
            platform.value: {
                "credential": credentials.credential_state(platform),
                "bindings": sum(1 for b in bindings if b.platform is platform),
                "operators": sum(1 for o in operators if o.platform is platform),
            }
            for platform in Platform
        },
    }


def _binding_set(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    chat_id, thread_id = chat_key(params.get("chat_id"), params.get("thread_id"))
    instance_id = field_text(params.get("persona_instance_id"), "persona_instance_id")
    if not _instance_exists(instance_id):
        raise MessagingRefused(Reason.UNKNOWN_INSTANCE, "persona_instance_id")
    binding = BindingStore().set(Binding(platform, chat_id, thread_id, instance_id, by, _now()))
    emit("messaging.binding.set", platform=platform.value, chat_id=chat_id, thread_id=thread_id,
         persona_instance_id=instance_id, by=by)
    return {"binding": binding.wire()}


def _binding_clear(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    chat_id, thread_id = chat_key(params.get("chat_id"), params.get("thread_id"))
    cleared = BindingStore().clear(platform, chat_id, thread_id)
    emit("messaging.binding.cleared", platform=platform.value, chat_id=chat_id, thread_id=thread_id,
         cleared=cleared, by=by)
    return {"cleared": cleared}


def _binding_list(params: Mapping[str, Any], _by: str) -> dict[str, Any]:
    return {"bindings": [b.wire() for b in BindingStore().list(_optional_platform(params))]}


def _operator_allow(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    user_id = field_text(params.get("user_id"), "user_id")
    display = field_text(params.get("display"), "display", required=False) or ""
    operator = OperatorStore().allow(Operator(platform, user_id, display, by, _now()))
    emit("messaging.operator.allowed", platform=platform.value, user_id=user_id, by=by)
    return {"operator": operator.wire()}


def _operator_revoke(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    user_id = field_text(params.get("user_id"), "user_id")
    revoked = OperatorStore().revoke(platform, user_id)
    emit("messaging.operator.revoked", platform=platform.value, user_id=user_id, revoked=revoked, by=by)
    return {"revoked": revoked}


def _operator_list(params: Mapping[str, Any], _by: str) -> dict[str, Any]:
    return {"operators": [o.wire() for o in OperatorStore().list(_optional_platform(params))]}


def _credential_set(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    credentials.set_token(platform, params.get("token"))
    emit("messaging.credential.set", platform=platform.value, by=by)
    return {"platform": platform.value, "credential": credentials.credential_state(platform)}


def _credential_clear(params: Mapping[str, Any], by: str) -> dict[str, Any]:
    platform = platform_of(params.get("platform"))
    cleared = credentials.clear_token(platform)
    emit("messaging.credential.cleared", platform=platform.value, cleared=cleared, by=by)
    return {"platform": platform.value, "cleared": cleared, "credential": credentials.credential_state(platform)}


#: op -> (tier, service function). The one routing table: the registration, the tiers and the bridge read it.
OPS: dict[str, tuple[str, Callable[[Mapping[str, Any], str], dict[str, Any]]]] = {
    "status": (TIER_READ, status),
    "binding.set": (TIER_CONSOLE, _binding_set),
    "binding.clear": (TIER_CONSOLE, _binding_clear),
    "binding.list": (TIER_CONSOLE, _binding_list),
    "operator.allow": (TIER_CONSOLE, _operator_allow),
    "operator.revoke": (TIER_CONSOLE, _operator_revoke),
    "operator.list": (TIER_CONSOLE, _operator_list),
    "credential.set": (TIER_CONSOLE, _credential_set),
    "credential.clear": (TIER_CONSOLE, _credential_clear),
}

TIERS: dict[str, str] = {METHOD_PREFIX + op: tier for op, (tier, _fn) in OPS.items()}


def execute(op: str, params: Mapping[str, Any] | None, *, by: str) -> dict[str, Any]:
    """Run one op. Raises :class:`MessagingRefused`; the RPC handler and the bridge both call this."""
    row = OPS.get(op)
    if row is None:
        raise MessagingRefused(Reason.INVALID, "op")
    return row[1](dict(params or {}), by)


def _reply(rid: Any, op: str, params: Any, by: str) -> dict:
    try:
        return ok(rid, execute(op, params if isinstance(params, Mapping) else {}, by=by))
    except MessagingRefused as refusal:
        return err(rid, REFUSAL_CODES.get(refusal.reason, ERR_HANDLER_FAILED), "This messaging request could not be accepted.",
                   {"reason": refusal.reason.value, "detail": refusal.detail})
    except Exception:
        return err(rid, ERR_HANDLER_FAILED, "The messaging settings could not be read or written.",
                   {"reason": Reason.UNAVAILABLE.value})


def _handler(op: str):
    def handle(rid, params, context=None):
        caller = getattr(context, "caller", None)
        return _reply(rid, op, params, f"rpc:{getattr(caller, 'kind', 'unknown')}")
    return handle


def register(method) -> None:
    for op, (tier, _fn) in OPS.items():
        method(METHOD_PREFIX + op, tier=tier)(_handler(op))
