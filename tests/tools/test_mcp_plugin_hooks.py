"""on_mcp_session / on_mcp_notification / post_mcp_call hooks and register_completion_formatter."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp.client.auth.oauth2")

from mcp import types

from tools import mcp_tool_loop as _mcp_loop
from tools.mcp_tool import MCPServerTask

_MCP_HOOKS = ("on_mcp_session", "on_mcp_notification", "post_mcp_call")


@pytest.fixture
def seen(monkeypatch):
    """Record every MCP hook dispatched through hermes_cli.plugins.invoke_hook."""
    from hermes_cli import plugins

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(plugins, "has_hook", lambda name: name in _MCP_HOOKS)
    monkeypatch.setattr(plugins, "invoke_hook", lambda name, **kw: calls.append((name, kw)) or [])
    return calls


def test_hook_names_are_registrable():
    from hermes_cli.plugins import VALID_HOOKS

    assert set(_MCP_HOOKS) <= VALID_HOOKS


def test_post_mcp_call_sees_the_raw_result_and_call_kwargs(seen, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from tools import mcp_tool, mcp_tool_handlers
    from tools.mcp_tool_handlers import _make_tool_handler

    raw = types.CallToolResult(content=[types.TextContent(type="text", text="ok")], isError=False)

    async def _racing(server, server_name, tool_name, args):
        return raw

    monkeypatch.setattr(mcp_tool_handlers, "_call_tool_racing_stdio_death", _racing)
    server = MagicMock()
    server.name = "hooksrv"
    ready = threading.Event()
    ready.set()
    server._ready = ready
    server._is_recycled_stdio.return_value = False
    mcp_tool._servers["hooksrv"] = server
    mcp_tool._server_error_counts.pop("hooksrv", None)
    _mcp_loop._ensure_mcp_loop()
    try:
        out = _make_tool_handler("hooksrv", "echo", 10.0)({"text": "hi"}, task_id="task-7")
    finally:
        mcp_tool._servers.pop("hooksrv", None)
    assert "ok" in out
    calls = [kw for name, kw in seen if name == "post_mcp_call"]
    assert len(calls) == 1
    assert calls[0]["result"] is raw
    assert calls[0]["server_name"] == "hooksrv" and calls[0]["tool_name"] == "echo"
    assert calls[0]["arguments"] == {"text": "hi"}
    assert calls[0]["call_kwargs"]["task_id"] == "task-7"


def test_logging_callback_and_message_handler_fire_on_mcp_notification(seen):
    task = MCPServerTask("notesrv")
    params = SimpleNamespace(level="info", data="job done", logger=None)
    asyncio.run(task._make_logging_callback()(params))
    progress = types.ProgressNotification(
        method="notifications/progress",
        params=types.ProgressNotificationParams(progressToken="tok", progress=1.0))
    # mcp 2.x: ServerNotification is a plain union (the payload IS the message); 1.x wraps it.
    message = progress if not callable(types.ServerNotification) else types.ServerNotification(progress)
    asyncio.run(task._make_message_handler()(message))
    notes = [kw for name, kw in seen if name == "on_mcp_notification"]
    assert notes[0] == {"server_name": "notesrv", "method": "notifications/message", "params": params}
    assert notes[1]["method"] == "notifications/progress"
    assert notes[1]["params"] is progress.params


class _Stop(Exception):
    pass


def test_on_mcp_session_phases_bracket_initialize(seen, monkeypatch):
    task = MCPServerTask("sesssrv")
    task._config = {}
    order: list[str] = []

    class _Session:
        async def initialize(self):
            order.append("initialize")
            return "INIT"

    async def _discover():
        raise _Stop

    from hermes_cli import plugins
    monkeypatch.setattr(plugins, "invoke_hook",
                        lambda name, **kw: order.append(kw["phase"]) or seen.append((name, kw)) or [])
    monkeypatch.setattr(task, "_discover_tools", _discover)
    session = _Session()
    with pytest.raises(_Stop):
        asyncio.run(task._serve_session(session, 5))
    assert order == ["created", "initialize", "ready"]
    assert all(kw["session"] is session and kw["server_name"] == "sesssrv" for _, kw in seen)


def test_completion_formatter_renders_its_event_type_only():
    from tools import process_registry_notifications as prn

    prn.register_completion_formatter("x_finished", lambda evt: f"[IMPORTANT: x {evt['id']} finished]")
    try:
        assert prn.format_process_notification({"type": "x_finished", "id": "7"}) == "[IMPORTANT: x 7 finished]"
        stock = prn.format_process_notification({"type": "completion", "session_id": "p1", "command": "true",
                                                 "exit_code": 0, "output": ""})
        assert stock and "p1" in stock
    finally:
        prn._COMPLETION_FORMATTERS.pop("x_finished", None)
