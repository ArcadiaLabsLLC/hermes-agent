"""The native conversation turn's permission mode, bound per turn in the worker (design D2.07).

The SERVE resolves what a conversation turn may do (``tool_permissions.
permission_options_for_subject``, the operator lane's resolver) and, before
``prompt.submit``, tells the worker the MODE for that turn's execution id through
:data:`METHOD`. The worker derives the block itself
(``extra_blocked_tools_for_permission_mode``), because that table reads the Launcher
catalog registered in the process it runs in, and binds it for the turn through the
existing ``worker_app_functions.bind`` / ``reset`` seam.

Owner ruling 2026-10-15: read-only unless allowed. A turn the serve did not admit (no
execution id) or whose mode never arrived (or arrived for another execution) binds the
``read_only`` block and logs ``permission_bind_missing``; a turn with something to block refuses to run when
the eternia-harness doors (the ``llm_request`` middleware and the ``pre_tool_call``
hook) are not installed, rather than running unfiltered.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

__layer__ = "lanes"
__all__ = ["METHOD", "TurnPermission", "bind", "declare_contracts", "register", "remember", "reset"]

logger = logging.getLogger(__name__)

METHOD = "eternia.permission.bind"

#: A mode handed over and never claimed by its turn (the submit failed) must not grow
#: without bound; the oldest are dropped first.
_PENDING_CAP = 256

_lock = threading.Lock()
_pending: dict[str, str] = {}


@dataclass(frozen=True)
class TurnPermission:
    execution_id: str
    mode: str
    missing: bool = False


def declare_contracts() -> None:
    from tui_gateway.contracts import registry
    from tui_gateway.contracts.base import Result
    from tui_gateway.contracts.common import SessionParams

    if METHOD in registry.METHODS:
        return

    class PermissionBindParams(SessionParams):
        execution_id: str
        permission_mode: str

    class PermissionBindResult(Result):
        bound: bool

    registry.method(METHOD, params=PermissionBindParams, result=PermissionBindResult)


def _handle(rid, params):
    execution_id = str(params.get("execution_id") or "").strip()
    mode = str(params.get("permission_mode") or "").strip()
    if not execution_id or not mode:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": 4000, "message": "execution_id and permission_mode are required."}}
    remember(execution_id, mode)
    return {"jsonrpc": "2.0", "id": rid, "result": {"bound": True}}


def register(server) -> None:
    """Installed with the other fork methods at gateway import (``gateway_extensions``)."""
    from agent_runtime.gateway.contract_seam import pydantic_contracts_enabled

    if pydantic_contracts_enabled():
        declare_contracts()
    server.register_method(METHOD, _handle)


def remember(execution_id: str, mode: str) -> None:
    with _lock:
        _pending.pop(execution_id, None)
        _pending[execution_id] = mode
        while len(_pending) > _PENDING_CAP:
            _pending.pop(next(iter(_pending)))


def _take(execution_id: str) -> str | None:
    with _lock:
        return _pending.pop(execution_id, None)


def _doors_installed() -> bool:
    from hermes_cli.plugins import has_hook, has_middleware

    return bool(has_middleware("llm_request")) and bool(has_hook("pre_tool_call"))


def turn_permission(session: dict) -> TurnPermission:
    """This turn's mode. A turn the serve did not admit (no execution id) or whose mode
    never arrived is ``read_only`` and logged — read-only unless allowed."""

    from agent_runtime.permission_modes import PERMISSION_MODE_READ_ONLY

    execution = (session or {}).get("native_execution") or {}
    execution_id = str(execution.get("id") or "").strip()
    if not execution_id:
        logger.warning("permission_bind_missing execution_id=- reason=not_admitted mode=%s", PERMISSION_MODE_READ_ONLY)
        return TurnPermission("", PERMISSION_MODE_READ_ONLY, missing=True)
    mode = _take(execution_id)
    if mode is None:
        logger.warning("permission_bind_missing execution_id=%s mode=%s", execution_id, PERMISSION_MODE_READ_ONLY)
        return TurnPermission(execution_id, PERMISSION_MODE_READ_ONLY, missing=True)
    return TurnPermission(execution_id, mode)


def bind(sid, session):
    """Bind this turn's block for its session ids; a token for :func:`reset`, or ``None``."""

    from agent_runtime.tool_blocks import bind_tool_block
    from agent_runtime.tool_permissions import extra_blocked_tools_for_permission_mode

    from .worker_app_functions import enabled

    if not enabled(session):
        return None  # a direct TUI session is never touched
    permission = turn_permission(session)
    block = extra_blocked_tools_for_permission_mode(permission.mode)
    if block and not _doors_installed():
        raise RuntimeError("tool-block doors are not installed")
    return bind_tool_block(block, session_ids=(sid, (session or {}).get("session_key")))


def reset(token) -> None:
    from agent_runtime.tool_blocks import reset_tool_block

    if token is not None:
        reset_tool_block(token)
