"""The one reader of ``_METHODS``: frame detection, request normalisation and
:func:`handle_request`, which authorizes a caller against the method's tier and
runs the handler.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import authorize_call
from agent_runtime.execution_identity import execution_identity

from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    JSONRPC_VERSION,
    RpcContext,
    err,
)
from agent_runtime.serve_rpc.registry import (
    _METHODS,
    _ensure_discussion_methods,
    _ensure_local_llama_methods,
    _ensure_conversation_methods,
    method_names,
    method_tier,
)

__layer__ = "lanes"

__all__ = [
    "_normalize_request",
    "handle_request",
    "is_rpc_frame",
]


def is_rpc_frame(message: Any) -> bool:
    """Does this frame belong to the METHOD lane rather than the argv lane?

    Deliberately generous on the way IN and strict once inside: a frame naming
    ``jsonrpc`` or ``method`` is claimed here even when malformed, so the
    caller gets a typed JSON-RPC error instead of the argv lane's
    ``invalid_request`` complaining about a missing ``argv``. The argv lane has
    never sent either key, so nothing is taken from it.
    """

    return isinstance(message, dict) and ("jsonrpc" in message or "method" in message)


def _normalize_request(req: Any) -> tuple[Any, str, dict] | dict:
    """Validate a JSON-RPC request enough for safe local dispatch.

    Copied from ``tui_gateway/server.py:1672`` with one addition: the
    ``jsonrpc`` member is CHECKED. Upstream can skip it because its transport
    carries nothing else; here the same line could have been an argv request,
    so the version member is what makes the routing decision auditable rather
    than assumed.
    """

    if not isinstance(req, dict):
        return err(None, ERR_INVALID_REQUEST, "invalid request: expected an object")

    rid = req.get("id")
    version = req.get("jsonrpc")
    if version != JSONRPC_VERSION:
        return err(
            rid,
            ERR_INVALID_REQUEST,
            f'invalid request: jsonrpc must be "{JSONRPC_VERSION}"',
            {"reason": "bad_jsonrpc_version", "jsonrpc": version},
        )

    name = req.get("method")
    if not isinstance(name, str) or not name:
        return err(
            rid,
            ERR_INVALID_REQUEST,
            "invalid request: method must be a non-empty string",
            {"reason": "bad_method"},
        )

    params = req.get("params", {})
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: expected an object",
            {"reason": "params_not_an_object"},
        )

    return rid, name, params


def handle_request(req: Any, context: RpcContext | None = None) -> dict:
    """Answer one JSON-RPC request. Always returns a frame — never raises.

    A handler that raises becomes ``-32000`` rather than escaping into the
    serve reader loop: this lane shares a thread with the transport dispatcher,
    and a read method is not permitted to take a durable service down.

    ``context`` is optional and defaults to an EMPTY one rather than to
    ``None``, so a handler can always ask ``context.emit is None`` instead of
    guarding the argument itself. A caller that omits it (every test, and the
    argv lane's own probes) gets a caller with no push channel, which is the
    truth about it.

    **The authorization gate is here, and it is here rather than in
    :func:`method`'s wrapper on purpose** (Stage A3). This is the single point
    every frame on both transports passes through, so a method cannot be
    registered around it: the tier declaration rides the decorator, the decision
    runs here, and there is no per-method opt-out to forget. It also leaves the
    handlers callable directly — which every unit test in this repo does — so
    landing the gate did not rewrite the suites that exercise the functions
    below.

    Ordering matters and is deliberate: an UNKNOWN method is answered
    ``-32601`` before the gate runs. A refusal that told a caller which names
    exist would be leaking the surface to someone who may not use it; a
    ``method_not_found`` tells them nothing they could not learn from a manifest
    they were already sent. And a caller refused for scope must not be able to
    probe the registry by watching which name changes the error code — which it
    cannot, because the gate's refusal names only the tier it wanted.
    """

    context = context or RpcContext()
    normalized = _normalize_request(req)
    if isinstance(normalized, dict):
        return normalized

    _ensure_local_llama_methods()
    _ensure_discussion_methods()
    _ensure_conversation_methods()
    rid, name, params = normalized
    fn = _METHODS.get(name)
    if fn is None:
        return err(
            rid,
            ERR_METHOD_NOT_FOUND,
            f"unknown method: {name}",
            {"reason": "unknown_method", "methods": method_names()},
        )
    # The NAME travels beside the tier because gateway Stage 6's caller kind is
    # answered by an allowlist rather than by a tier word (``PEER_METHOD_ALLOWLIST``).
    # Passed unconditionally rather than only for peers: a gate that received
    # the method sometimes would be a gate whose answer depended on which arm
    # the caller happened to reach, which is the shape this module exists to
    # retire.
    decision = authorize_call(method_tier(name), context.caller, method=name)
    if not decision.ok:
        # ``detail`` when the policy supplied one, the tier sentence otherwise.
        # The dispatcher still does not KNOW any policy — it renders whichever
        # sentence the decision carried — and the fallback is unchanged, so no
        # existing refusal's wording moves. WS4 is the one arm that sets it,
        # because "requires the console tier" is false for a caller that holds
        # console and is refused on its KIND.
        return err(
            rid,
            ERR_HANDLER_FAILED,
            decision.detail or f"{name} requires the {decision.tier} tier",
            decision.refusal_data(),
        )
    try:
        if "execution_id" in req and req["execution_id"] != execution_identity()["execution_id"]:
            return err(rid, 4090, "The connected service belongs to another Hermes installation.",
                       {"reason": "execution_identity_mismatch"})
        return fn(rid, params, context)
    except Exception as exc:  # noqa: BLE001 - the boundary is the point
        return err(
            rid,
            ERR_HANDLER_FAILED,
            f"handler error: {exc}",
            {"reason": "handler_failed", "method": name},
        )
