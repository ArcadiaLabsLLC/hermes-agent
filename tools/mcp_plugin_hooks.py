"""Plugin hooks on an MCP client session (dispatched through ``hermes_cli.plugins.invoke_hook``).

- ``on_mcp_session(server_name, session, phase)``: ``"created"`` — the SDK ``ClientSession`` exists
  and nothing has been sent (a plugin may shape the capability ad or wrap a method); ``"ready"`` —
  ``initialize`` answered, tools not yet listed.
- ``on_mcp_notification(server_name, method, params)``: every ``ServerNotification`` the
  ``message_handler`` sees (after the mcp-2.0 ``.root`` unwrap) and every ``notifications/message``
  the ``logging_callback`` sees (the SDK routes those separately).
- ``post_mcp_call(server_name, tool_name, arguments, result, call_kwargs)``: the raw
  ``CallToolResult`` before rendering/capping, with the registry kwargs the handler was called with.

All three run inline on the MCP event loop: a callback must return fast and never block or await.
``invoke_hook`` isolates a raising callback from the caller. Nothing registered costs one
``has_hook`` dict lookup per site.
"""
from __future__ import annotations

from typing import Any


def emit_mcp_hook(hook_name: str, **kwargs: Any) -> None:
    """Fire one MCP observer hook when a plugin registered it; return values are ignored."""
    from hermes_cli.plugins import has_hook, invoke_hook

    if has_hook(hook_name):
        invoke_hook(hook_name, **kwargs)
