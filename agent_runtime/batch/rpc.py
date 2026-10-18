"""``runtime.batch.plan | start | status | stop | land | approve`` — the dispatcher's console methods.

Dispatcher plan §3 (B2). Console tier, registered like ``work/rpc.py::register`` and deferred through
``spawn_reply`` (every call reads or writes git). Scope is the Work scope: ``install_id`` plus the
opaque ``owner`` (``work.model.WorkScope``). A refusal is error 4090 ``{"reason", "detail"}`` with a
``work_store.reasons.Reason`` word. Every reply carries ``version`` and ``install_id``.

Params beyond scope: ``plan`` none; ``start`` ``batch_id`` (the plan's id) and ``personas?``
(``{lane_id: instance_id}``, the operator's answer to ``asks``); ``status`` ``batch_id?``; ``stop``
``batch_id``, ``lane?`` (omitted: abort the batch); ``land`` ``batch_id``, ``persona?``; ``approve``
``batch_id``. The dispatcher is the serve session's (``RpcContext.batch_dispatcher``); with no serve
session behind the call every method refuses ``door_unbound``. These calls are the operator's: a scheduler fire reaches ``start`` / ``plan`` through
``BatchDispatcher`` with ``scheduled=True`` (the ``batch_automation`` gate), never through here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE, authorize_call
from agent_runtime.serve_rpc.protocol import defer_or_refuse, err, ok
from agent_runtime.work_store.reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = ["OPERATIONS", "VERSION", "execute", "register"]

VERSION = 1


def _batch_id(params: Mapping[str, Any]) -> str:
    from agent_runtime.work.model import text

    return text(params.get("batch_id"), maximum=64)


def _personas(params: Mapping[str, Any]) -> dict[str, str]:
    from agent_runtime.work.model import text

    raw = params.get("personas") or {}
    if not isinstance(raw, dict):
        raise WorkRefused(Reason.INVALID, "personas is {lane_id: instance_id}")
    return {text(lane, maximum=16): text(who, maximum=256) for lane, who in raw.items()}


def _optional(params: Mapping[str, Any], key: str) -> str | None:
    from agent_runtime.work.model import text

    return None if params.get(key) is None else text(params[key], maximum=256)


#: operation → what it runs on the dispatcher for one workspace; the result's wire.
_OPS: dict[str, Callable[[Any, str, Mapping[str, Any]], dict[str, Any]]] = {
    "plan": lambda d, ws, p: {"plan": d.plan(ws).wire()},
    "start": lambda d, ws, p: {"batch": d.start(ws, _batch_id(p), personas=_personas(p)).wire()},
    "status": lambda d, ws, p: d.status(ws, _optional(p, "batch_id")),
    "stop": lambda d, ws, p: {"batch": d.stop(ws, _batch_id(p), _optional(p, "lane")).wire()},
    "land": lambda d, ws, p: {"batch": d.land(ws, _batch_id(p), persona=_optional(p, "persona")).wire()},
    "approve": lambda d, ws, p: {"batch": d.approve(ws, _batch_id(p)).wire()},
}
OPERATIONS = tuple(_OPS)


def execute(operation: str, params: Mapping[str, Any], caller: Any, *, dispatcher: Any = None) -> dict[str, Any]:
    """Authorize, resolve the workspace from ``owner``, run ``operation``; the reply body."""

    from agent_runtime.gateway_identity import read_install_identity
    from agent_runtime.paths import store_root
    from agent_runtime.work.model import WorkScope, text
    from agent_runtime.work.service import git_shipped, workspace_ids

    if not authorize_call(TIER_CONSOLE, caller, method="runtime.batch." + operation).ok:
        raise WorkRefused(Reason.DENIED)
    install = read_install_identity(store_root()).install_id
    if not install:
        raise WorkRefused(Reason.UNAVAILABLE)
    if text(params.get("install_id")) != install:
        raise WorkRefused(Reason.OWNER_CHANGED)
    if not git_shipped():
        raise WorkRefused(Reason.GIT_UNAVAILABLE, "git is switched off in this bundle")
    owner = text(params.get("owner"))
    scope = next((WorkScope(install, ws) for ws in workspace_ids() if WorkScope(install, ws).owner == owner), None)
    if scope is None:
        raise WorkRefused(Reason.OWNER_CHANGED)
    if dispatcher is None:
        raise WorkRefused(Reason.DOOR_UNBOUND, "no serve session holds a batch dispatcher")
    body = _OPS[operation](dispatcher, scope.workspace_id, params)
    return {"version": VERSION, "install_id": install, "owner": scope.owner, **body}


def _batch_reply(rid: Any, operation: str, params: Mapping[str, Any], context: Any) -> dict[str, Any]:
    door = context.batch_dispatcher
    try:
        return ok(rid, execute(operation, params, context.caller, dispatcher=door() if door else None))
    except WorkRefused as refusal:
        return err(rid, 4090, "This batch request could not be accepted.",
                   {"reason": refusal.reason.value, "detail": refusal.detail})
    except (KeyError, TypeError, ValueError):
        return err(rid, -32602, "Invalid batch request.", {"reason": Reason.INVALID.value})
    except Exception:
        return err(rid, -32000, "The batch outcome could not be verified.", {"reason": Reason.UNKNOWN.value})


def _batch_method(operation: str) -> Callable[[Any, dict, Any], dict]:
    def handle(rid: Any, params: dict, context: Any) -> dict:
        return defer_or_refuse(rid, "runtime.batch." + operation, context,
                               lambda: _batch_reply(rid, operation, dict(params or {}), context))
    return handle


def register(method: Callable[..., Any]) -> None:
    for operation in OPERATIONS:
        method("runtime.batch." + operation, tier=TIER_CONSOLE)(_batch_method(operation))
