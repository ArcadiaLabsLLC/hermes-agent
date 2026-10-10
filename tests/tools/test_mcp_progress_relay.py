"""The MCP client asks for progress, folds each report into the call's record, and
lets a call that keeps reporting outlive its base timeout (reset-on-progress).

Driven through a REAL ``mcp.ClientSession`` over the SDK's in-memory streams
against a scripted JSON-RPC server, so the token on the wire and the typed
notification reaching ``message_handler`` (with its ``_meta``) are the SDK's,
not a double's.
"""

from __future__ import annotations

import re
import threading

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, types  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402
from mcp.shared.message import SessionMessage  # noqa: E402

from tools import mcp_progress_relay as relay  # noqa: E402

QA_META = {"stagec_qa_build": {"phase": "compiling", "commit": "87c550098", "expected_ms": 330000}}


@pytest.fixture(autouse=True)
def _clean_relay():
    yield
    with relay._lock:
        relay._by_args.clear()
        relay._by_token.clear()
        relay._adopted.clear()


def _reply(request_id, result):
    return SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result))


async def _scripted_server(read, write, seen, *, reports: int, every: float, then: float):
    """Answer the handshake; on ``tools/call`` send ``reports`` progress notifications
    ``every`` seconds apart (only when the client sent a token), wait ``then``, answer."""

    async for item in read:
        if isinstance(item, Exception):
            continue
        message = item.message.model_dump(by_alias=True, exclude_none=True)
        seen.append(message)
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            await write.send(_reply(request_id, {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}}, "serverInfo": {"name": "scripted", "version": "0"}}))
        elif method == "tools/list":
            await write.send(_reply(request_id, {"tools": []}))
        elif method == "tools/call":
            token = (message["params"].get("_meta") or {}).get("progressToken")
            for index in range(reports if token is not None else 0):
                await write.send(SessionMessage(types.JSONRPCNotification(
                    jsonrpc="2.0", method="notifications/progress",
                    params={"progressToken": token, "progress": 12.5 + index,
                            "message": "Rebuilding the QA Launcher copy: compiling", "_meta": QA_META})))
                await anyio.sleep(every)
            await anyio.sleep(then)
            await write.send(_reply(request_id, {"content": [{"type": "text", "text": "built"}]}))
        elif request_id is not None and method:
            await write.send(_reply(request_id, {}))


async def _call(args, *, server=None, dispatched=True, reports=1, every=0.0, then=0.05):
    """One ``tools/call`` through an instrumented real session; returns (result, wire calls, snapshot)."""

    seen: list[dict] = []
    seen_by_handler: list = []

    async def downstream(message):
        seen_by_handler.append(message)

    record = relay.enter_dispatch(args, "mcp-qa") if dispatched else None
    try:
        async with create_client_server_memory_streams() as (client, srv):
            async with anyio.create_task_group() as group:
                group.start_soon(lambda: _scripted_server(srv[0], srv[1], seen, reports=reports, every=every, then=then))
                handler = relay.tee_message_handler(downstream)
                async with ClientSession(client[0], client[1], message_handler=handler) as session:
                    await session.initialize()
                    assert relay.instrument_session(session, "qa", server) is True
                    try:
                        result = await session.call_tool("open_app_tab", arguments=args)
                    except TimeoutError as exc:  # returned, so no task group wraps it
                        result = exc
                    finally:
                        group.cancel_scope.cancel()
        snapshot = relay.snapshot_by_tid().get(threading.get_ident())
    finally:
        relay.exit_dispatch(record)
    calls = [m for m in seen if m.get("method") == "tools/call"]
    return result, calls, snapshot, seen_by_handler


class _Server:
    """The two attributes the adoption reads off an ``MCPServerTask``."""

    def __init__(self, tool_timeout, config=None):
        self.tool_timeout = tool_timeout
        self._config = config or {}


def test_a_dispatched_call_sends_a_token_and_the_report_lands_on_its_record():
    args = {"tab": "library"}
    result, [call], progress, downstream = anyio.run(_call, args)

    assert result.content[0].text == "built"
    token = call["params"]["_meta"]["progressToken"]
    assert isinstance(token, str) and token.startswith("hermes-progress-")
    assert progress.reported is True and progress.updates == 1
    assert progress.progress == 12.5 and progress.total is None
    assert progress.message == "Rebuilding the QA Launcher copy: compiling"
    assert progress.phase == "compiling"
    assert progress.expected_ms == 330000
    assert isinstance(progress.seconds_since_update, float)
    # The tee never swallows: the wrapped handler still saw the notification.
    assert any(getattr(m, "method", None) == "notifications/progress" for m in downstream)


def test_positive_control_an_undispatched_call_asks_for_nothing():
    """Same bytes, no dispatch owning the args: no token on the wire, no record."""

    result, [call], progress, _ = anyio.run(lambda: _call({"tab": "library"}, dispatched=False))

    assert result.content[0].text == "built"
    assert "progressToken" not in (call["params"].get("_meta") or {})
    assert progress is None


def test_a_stated_expected_ms_at_the_top_level_of_meta_is_read():
    record = relay.enter_dispatch({"a": 1}, "mcp-qa")
    try:
        token = relay._begin_attempt("qa", "t", record.args)
        note = types.ProgressNotification(params=types.ProgressNotificationParams(
            progress_token=token, progress=1.0, _meta={"expected_ms": 9000, "phase": "linking"}))
        assert relay.observe_notification(note) is True
        [view] = relay.snapshot_by_tid().values()
        assert (view.expected_ms, view.phase) == (9000, "linking")
        # A report for a token nobody owns is dropped.
        stale = types.ProgressNotification(params=types.ProgressNotificationParams(progress_token="nope", progress=2.0))
        assert relay.observe_notification(stale) is False
    finally:
        relay.exit_dispatch(record)
    assert relay.snapshot_by_tid() == {}


def test_a_call_reporting_progress_outlives_its_base_timeout():
    """Base 1.0 s; the server reports every 0.1 s for ~1.5 s, then answers. Without
    reset-on-progress the call dies at 1.0 s. Each report lands 0.9 s inside the base, so a
    loaded scheduler has ten report periods of slack (a 0.3 s base with 0.2 s of slack died
    once under the 2026-10-02 landing gate's load)."""

    server = _Server(1.0, {"max_total_timeout": 5})
    result, _calls, progress, _ = anyio.run(
        lambda: _call({"tab": "library"}, server=server, reports=15, every=0.1, then=0.05))

    assert result.content[0].text == "built"
    assert progress.updates == 15
    # The outer deadline every handler registered from here waits on is the cap.
    assert server.tool_timeout == 5


def test_positive_control_a_silent_call_still_times_out_at_the_base():
    server = _Server(0.3, {"max_total_timeout": 5})
    result, _calls, progress, _ = anyio.run(lambda: _call({"tab": "library"}, server=server, reports=0, then=0.8))

    assert isinstance(result, TimeoutError)
    assert re.search(r"reported no progress for 0\.3s.*up to 5\.0s", str(result))
    assert progress.reported is False


def test_adoption_is_idempotent_across_reconnects_and_zero_turns_it_off():
    server = _Server(260, {})
    assert relay.adopt_progress_timeout(server, "launcher_qa") == (260, relay.DEFAULT_MAX_TOTAL_TIMEOUT_S)
    # A reconnect re-serves the session with tool_timeout already at the cap: the base survives.
    assert relay.adopt_progress_timeout(server, "launcher_qa") == (260, relay.DEFAULT_MAX_TOTAL_TIMEOUT_S)
    assert server.tool_timeout == relay.DEFAULT_MAX_TOTAL_TIMEOUT_S

    off = _Server(260, {"max_total_timeout": 0})
    assert relay.adopt_progress_timeout(off, "off") is None
    assert off.tool_timeout == 260
