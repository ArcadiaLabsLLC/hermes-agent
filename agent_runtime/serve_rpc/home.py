"""Home's ready next chat: ``runtime.home.next_chat.ensure`` and ``runtime.home.next_chat.get``.

Shims over :mod:`agent_runtime.home_next_chat` (row RT-HOME-KEEPS-ONE-HIDDEN-CHAT-READY-FOR-THE-PICKED-AGENT).
The ensure binds the calling connection's launcher link, as the open-chat method does, so the
ready chat's prewarm builds the tool contract its first turn will build.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["_runtime_home_next_chat_ensure", "_runtime_home_next_chat_get"]

#: The keys each verb honours (published in the manifest's ``params`` block).
ENSURE_PARAMS = ("persona_id", "persona_instance_id", "client_scope", "install_id", "requested_by")
GET_PARAMS = ("client_scope", "install_id")


@method("runtime.home.next_chat.ensure", tier=TIER_CONSOLE)
def _runtime_home_next_chat_ensure(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Assign (or re-point) the account's one ready chat to ``persona_id``; idempotent."""

    from agent_runtime.home_next_chat import HomeNextChatRefused, ensure_ready_chat
    from agent_runtime.launcher_app_functions import bind_launcher_link, launcher_link_of, reset_launcher_link

    link = launcher_link_of(context.launcher_request if context is not None else None)
    token = bind_launcher_link(link)
    try:
        return ok(rid, ensure_ready_chat(dict(params or {}), caller=context.caller if context is not None else None,
                                         launcher_link=link))
    except HomeNextChatRefused as exc:
        return err(rid, ERR_INVALID_PARAMS, "Home's ready chat was refused.", {"reason": str(exc)})
    finally:
        reset_launcher_link(token)


@method("runtime.home.next_chat.get", tier=TIER_CONSOLE)
def _runtime_home_next_chat_get(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The account's ready chat, or ``{"session_id": null}``; never mints."""

    from agent_runtime.home_next_chat import HomeNextChatRefused, ready_chat

    try:
        return ok(rid, ready_chat(dict(params or {})))
    except HomeNextChatRefused as exc:
        return err(rid, ERR_INVALID_PARAMS, "Home's ready chat was refused.", {"reason": str(exc)})
