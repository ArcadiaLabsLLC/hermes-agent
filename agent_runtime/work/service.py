"""Resolve the current runtime's work authority on each call."""
from __future__ import annotations

from agent_runtime.call_authorization import (
    CALLER_LOCAL_CONSOLE, CALLER_STDIO_OWNER, TIER_CONSOLE, authorize_call,
)
from agent_runtime.gateway_identity import read_install_identity
from agent_runtime.paths import store_root

from .model import Reason, WorkRefused, fingerprint, text

__layer__ = "lanes"


def execute(operation, params, caller):
    if not authorize_call(TIER_CONSOLE, caller, method="runtime.work." + operation).ok:
        raise WorkRefused(Reason.DENIED)
    install = read_install_identity(store_root()).install_id
    if not install:
        raise WorkRefused(Reason.UNAVAILABLE)
    if operation == "capabilities":
        return _work_capabilities(install)
    return _scoped_work_request(operation, params, caller, install)


def _work_capabilities(install):
    from . import native
    return {"version": 1, "install_id": install, "execution_identity_guard": True, "chat_scopes": True,
                "owners": [scope.wire(f"{label} · {scope.profile}") for scope, label in native.scopes(install)],
                "limitations": ["Tasks wait in Eternia Harness until its native dispatcher is running.",
                                "Stop, redirect and retry are unavailable on this connection."]}


def _scoped_work_request(operation, params, caller, install):
    from . import native
    if text(params.get("install_id")) != install:
        raise WorkRefused(Reason.OWNER_CHANGED)
    from .context import resolve
    context = (resolve(params["conversation"], params.get("client_scope"), caller, install)
               if "conversation" in params else None)
    if operation == "context":
        if context is None:
            raise WorkRefused(Reason.INVALID)
        return {"version": 1, "install_id": install, **context.wire()}
    owner = text(params.get("owner"))
    scope = next((scope for scope, _ in native.scopes(install) if scope.owner == owner), None)
    if scope is None:
        raise WorkRefused(Reason.OWNER_CHANGED)
    if operation == "start":
        if context is not None and not context.can_start:
            raise WorkRefused(Reason.UNAVAILABLE)
        actor = fingerprint(["installation-owner"] if caller.kind in (CALLER_STDIO_OWNER, CALLER_LOCAL_CONSOLE)
                            else [caller.kind, caller.device_id])
        result = native.start(scope, params, actor, context=context)
    else:
        result = {"list": native.list_work, "inspect": native.inspect}[operation](scope, params, context=context)
    return {"version": 1, "install_id": install, "owner": scope.owner, **result}
