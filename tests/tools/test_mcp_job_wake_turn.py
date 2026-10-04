"""A QA build is a background task: the client declares it can be woken, the agent's turn ends after
"build started", and the finished build starts exactly one NEW turn on the chat that started it.

Owner ruling 2026-10-03. Two halves, each through the real seam:

* the declaration — a REAL ``mcp.ClientSession`` over the SDK's in-memory streams, negotiated by
  ``MCPServerTask._negotiate_session`` against a scripted server that records the ``initialize``
  params and ignores the capability (so "a server that does not know the key still handshakes" is
  checked by the same run);
* the wake turn — the real tool handler binds the job, the real logging callback queues the wake,
  and the real serve drain (``BackgroundDrain``) decides idle -> forge a new turn, busy -> steer.
"""

from __future__ import annotations

import asyncio

import anyio
import pytest

pytest.importorskip("mcp")

from unittest.mock import MagicMock  # noqa: E402

from mcp import ClientSession, types  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402
from mcp.shared.message import SessionMessage  # noqa: E402

from agent_runtime import dispatch_delivery  # noqa: E402
from agent_runtime.dispatch_delivery.completions import BackgroundDrain  # noqa: E402
from tests.tools.test_mcp_job_wake import (  # noqa: E402,F401 — `registry` is the shared fixture
    JOB, READY_TEXT, SESSION, _Result, _call_qa_tool, _finished, _notify, _rebuilding_envelope, registry)
from tools import mcp_job_wake, mcp_tool  # noqa: E402
from tools.mcp_tool import MCPServerTask  # noqa: E402

OWNER = ("launcher_dev", "personainst_launcher_dev_1")
WAKE_CAP = {"eternia.job_wake": {"version": 1}}


# ---------------------------------------------------------------- the declaration


async def _record_initialize(read, write, seen: list) -> None:
    async for item in read:
        if isinstance(item, Exception):
            continue
        message = item.message.model_dump(by_alias=True, exclude_none=True)
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            seen.append(message["params"])
            await write.send(SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=request_id, result={
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}}, "serverInfo": {"name": "ignores-experimental", "version": "0"}})))
        elif request_id is not None and method:
            await write.send(SessionMessage(types.JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})))


def _negotiated_initialize_params() -> tuple[dict, object]:
    """Negotiate through the REAL client path; return the initialize params the server saw."""
    seen: list[dict] = []

    async def _go():
        task = MCPServerTask("launcher_qa")
        async with create_client_server_memory_streams() as (client, srv):
            async with anyio.create_task_group() as group:
                group.start_soon(lambda: _record_initialize(srv[0], srv[1], seen))
                async with ClientSession(client[0], client[1]) as session:
                    result = await task._negotiate_session(session, 5.0)
                group.cancel_scope.cancel()
        return result

    result = asyncio.run(_go())
    return seen[0], result


def test_initialize_declares_job_wake_when_the_wake_route_is_installed(monkeypatch):
    monkeypatch.setattr(mcp_tool, "_MCP_LOGGING_CALLBACK_SUPPORTED", True)
    params, result = _negotiated_initialize_params()
    assert params["capabilities"].get("experimental") == WAKE_CAP
    # The scripted server knows nothing of the key, and the handshake still completes.
    assert result.server_info.name == "ignores-experimental"


def test_positive_control_no_wake_route_no_declaration(monkeypatch):
    monkeypatch.setattr(mcp_tool, "_MCP_LOGGING_CALLBACK_SUPPORTED", False)
    params, _result = _negotiated_initialize_params()
    assert "experimental" not in params["capabilities"]


def test_a_session_without_the_sdk_builder_is_left_alone():
    assert mcp_job_wake.advertise_job_wake(MagicMock(spec=[])) is False


# ---------------------------------------------------------------- the wake turn


class _Chat:
    """The chat that started the build: busy while its turn runs, idle once it ends."""

    def __init__(self):
        self.idle = False
        self.forged: list[dict] = []

    def forge(self, **kwargs):
        self.forged.append(kwargs)
        return True, {"ok": True, "reply": "relaunching"}

    def drain(self, registry):
        policy = dispatch_delivery.DrainPolicy(
            sender_persona=lambda root: OWNER if root == SESSION else None,
            sender_is_idle=lambda root: self.idle)
        return BackgroundDrain(registry, self.forge, policy).run()


@pytest.fixture
def chat(monkeypatch, tmp_path):
    import agent_runtime.paths as runtime_paths
    monkeypatch.setattr(runtime_paths, "store_root", lambda: tmp_path / "runtime")
    return _Chat()


def test_build_started_turn_ends_then_the_finish_starts_exactly_one_new_turn(registry, chat):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())  # the tool result names build_job.job_id
    chat.idle = True                                     # ... and the agent's turn ends there
    assert chat.drain(registry)["considered"] == 0       # nothing to wake it for yet
    _notify(_finished())                                 # qa_build_finished arrives
    tally = chat.drain(registry)
    assert tally["delivered"] == 1
    [turn] = chat.forged
    assert (turn["root_session_id"], turn["persona_id"], turn["persona_instance_id"]) == (SESSION, *OWNER)
    assert turn["message"] == READY_TEXT
    chat.drain(registry)
    assert len(chat.forged) == 1                         # exactly one: the next pass forges nothing
    assert registry.completion_queue.empty()


def test_an_unrouted_job_finishing_starts_no_turn(registry, chat):
    chat.idle = True
    _notify(_finished(job_id="qb-20261003T205309-0nobody"))
    assert chat.drain(registry)["considered"] == 0
    assert chat.forged == []


def test_a_busy_chat_gets_the_wake_pushed_into_its_turn_not_a_new_one(registry, chat, monkeypatch):
    steered: list[dict] = []

    def _accept(**kwargs):
        steered.append(kwargs)
        return {"ok": True, "execution_state": "accepted"}

    import agent_runtime.mission_chat_steer as steer_mod
    monkeypatch.setattr(steer_mod, "submit_mission_chat_steer", _accept)
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    _notify(_finished())                                 # the build finishes while the turn still runs
    assert chat.drain(registry)["steered"] == 1
    assert chat.forged == []
    assert [s["message"] for s in steered] == [READY_TEXT]


def test_two_builds_on_one_long_named_server_are_two_turns(registry, chat):
    """The serve drain keys a forged turn by 40 chars of the event identity; two wakes must not share it."""
    server = "launcher_qa_isolated_build"
    jobs = ("qb-20261003T205309-abc123", "qb-20261003T211501-def456")
    for job in jobs:
        mcp_job_wake.observe_call_result(server, _Result({"build_job": {"job_id": job, "status": "running"}}),
                                         {"session_key": SESSION, "task_id": SESSION})
        assert mcp_job_wake.on_log_notification(server, _finished(job_id=job))
    chat.idle = True
    assert chat.drain(registry)["delivered"] == 2
    ids = [turn["client_message_id"] for turn in chat.forged]
    assert len(set(ids)) == 2, ids
