"""``runtime.default_model.set`` — the serve profile's runtime default pair.

A translation shim over :func:`agent_runtime.runtime_default_model.set_runtime_default_model`,
which owns the validation (upstream ``switch_model``), the write (upstream
``save_config``), the closed refusal set and the event. Validation can fetch a
provider catalog, so the call goes to the worker lane when the transport has one.

Params: ``provider`` and ``model`` (required), ``requested_by`` (optional, a
label carried on the event). Result: ``{contract, ok, changed, profile, provider,
model, api_mode, previous: {provider, model}, warning}``. A refusal is an error
frame whose ``data.reason`` is one of
:data:`~agent_runtime.runtime_default_model.DEFAULT_MODEL_REFUSAL_REASONS`.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.params import _text_param
from agent_runtime.serve_rpc.protocol import (
    DEFERRED,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    RpcContext,
    deferred_reply,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "DEFAULT_MODEL_CONTRACT",
    "_runtime_default_model_set",
]

#: This family's own result-shape number (the ``PROVIDER_CONTRACT`` precedent).
DEFAULT_MODEL_CONTRACT = 1

METHOD_NAME = "runtime.default_model.set"

#: refusal reason -> JSON-RPC error code. Params and a pick upstream rejects are
#: the caller's to fix; a managed, unreadable or shadowed config is a state
#: conflict on this install; a failed save is the handler's.
_REASON_CODES: dict[str, int] = {
    "provider_required": ERR_INVALID_PARAMS,
    "model_required": ERR_INVALID_PARAMS,
    "model_rejected": ERR_INVALID_PARAMS,
    "config_managed": ERR_CONFLICT,
    "config_unreadable": ERR_CONFLICT,
    "shadowed_by_runtime_override": ERR_CONFLICT,
    "config_write_failed": ERR_HANDLER_FAILED,
}


def _answer(rid: Any, provider: str | None, model: str | None, requested_by: str | None) -> dict:
    from agent_runtime.runtime_default_model import DefaultModelRefused, set_runtime_default_model

    try:
        result = set_runtime_default_model(provider=provider, model=model, requested_by=requested_by)
    except DefaultModelRefused as refusal:
        return err(
            rid,
            _REASON_CODES[refusal.reason],
            refusal.message or f"{METHOD_NAME} refused: {refusal.reason}",
            {"reason": refusal.reason, **refusal.data},
        )
    except Exception as exc:  # noqa: BLE001 — class name only, never the message
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"{METHOD_NAME} failed",
            {"reason": "handler_failed", "method": METHOD_NAME, "error_class": type(exc).__name__},
        )
    return ok(rid, {"contract": DEFAULT_MODEL_CONTRACT, **result})


@method(METHOD_NAME, tier=TIER_CONSOLE)
def _runtime_default_model_set(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Set the serve profile's ``model.default`` / ``model.provider``. Params: ``provider``, ``model``; ``requested_by`` optional."""
    provider = _text_param(params, "provider")
    model = _text_param(params, "model")
    requested_by = _text_param(params, "requested_by")
    if provider is None:
        return err(rid, ERR_INVALID_PARAMS, f"{METHOD_NAME} refused: provider_required", {"reason": "provider_required"})
    if model is None:
        return err(rid, ERR_INVALID_PARAMS, f"{METHOD_NAME} refused: model_required", {"reason": "model_required"})
    build = lambda: _answer(rid, provider, model, requested_by)  # noqa: E731
    spawn = None if context is None else context.spawn_reply
    if spawn is not None and spawn(deferred_reply(rid, METHOD_NAME, build)):
        return DEFERRED
    return build()
