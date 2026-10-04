"""An MCP server's job-finished notification wakes the agent that started the job — once.

Owner ruling 2026-10-03: a QA build is a background task, like a ``terminal`` with
``notify_on_complete``. The launcher QA server's wire (``tool/stagec_qa_mcp_server/lib/
qa_build_notify.dart``): ``notifications/message``, logger ``stagec_qa_mcp_server.qa_build``,
``data.event == "qa_build_finished"``. Fork module: ``tools/mcp_job_wake.py``.
"""

import asyncio
import json
import logging
import queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import mcp_job_wake, mcp_tool
from tools import mcp_tool_handlers as _mcp_handlers
from tools import process_registry as _pr_mod
from tools.approval_context import reset_current_session_key, set_current_session_key
from tools.mcp_tool import MCPServerTask

SERVER = "launcher_qa"
JOB = "qab-20261003-abc123"
SESSION = "persona_chat_wake_test"
READY_TEXT = f"[IMPORTANT: QA build ready, job {JOB} — continue: call launch_or_attach/open_app_tab again.]"


class _Block:
    def __init__(self, text):
        self.text, self.type = text, "text"


class _Result:
    def __init__(self, envelope, is_error=True):
        self.content, self.isError = [_Block(json.dumps(envelope))], is_error
        self.structuredContent, self.meta = None, None


def _rebuilding_envelope(job_id=JOB, status="running"):
    """The launcher's ``qa_build_rebuilding`` failure envelope (``envelope_policy.dart``)."""
    return {"schema": "stagec_mcp_launch_or_attach.safe.v1", "ok": False, "failure_class": "qa_build_rebuilding",
            "build_job": {"job_id": job_id, "status": status, "phase": "building", "this_call": "rebuild_in_flight"}}


def _finished(job_id=JOB, outcome="ready", logger_name=mcp_job_wake.QA_BUILD_LOGGER,
              event=mcp_job_wake.QA_BUILD_FINISHED, **extra):
    """``qaBuildFinishedNotification``'s params, as the SDK hands them to the logging callback."""
    data = {"event": event, "job_id": job_id, "outcome": outcome, "elapsed_ms": 281000, **extra}
    return SimpleNamespace(level="notice" if outcome == "ready" else "error", logger=logger_name, data=data)


def _run_on_loop(factory, timeout=30):
    loop = asyncio.new_event_loop()
    try:
        async def _go():
            for srv in list(mcp_tool._servers.values()):
                if getattr(srv, "_rpc_lock", None) is None:
                    srv._rpc_lock = asyncio.Lock()
            return await factory()
        return loop.run_until_complete(_go())
    finally:
        loop.close()


@pytest.fixture
def registry(monkeypatch):
    """A fresh ProcessRegistry (no state.db replay) bound where the wake looks it up."""
    reg = _pr_mod.ProcessRegistry()
    reg._completions_restored = True
    monkeypatch.setattr(_pr_mod, "process_registry", reg)
    mcp_job_wake.reset_for_tests()
    # The rebuilding envelope is isError, so three calls open the breaker (#10447) and later calls
    # never reach the server; every test starts closed.
    mcp_tool._reset_server_error(SERVER)
    yield reg
    mcp_job_wake.reset_for_tests()
    mcp_tool._reset_server_error(SERVER)


def _call_qa_tool(session, envelope, *, task_id=SESSION):
    """Drive the REAL ``_make_tool_handler`` the way a ``launch_or_attach`` call does."""
    fake_server = SimpleNamespace(session=session, _rpc_lock=None)
    session.call_tool = AsyncMock(return_value=_Result(envelope))
    token = set_current_session_key(SESSION)
    try:
        with patch.dict(mcp_tool._servers, {SERVER: fake_server}), \
                patch("tools.mcp_tool_loop._run_on_mcp_loop", side_effect=_run_on_loop):
            return _mcp_handlers._make_tool_handler(SERVER, "mcp_launcher_qa_launch_or_attach", 30.0)(
                {}, task_id=task_id)
    finally:
        reset_current_session_key(token)


def _notify(params):
    asyncio.run(MCPServerTask(SERVER)._make_logging_callback()(params))


def _drained(reg):
    return reg.drain_notifications(session_key=SESSION)


def test_positive_control_routed_job_wakes_its_session_once(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    _notify(_finished())
    pairs = _drained(registry)
    assert [text for _evt, text in pairs] == [READY_TEXT]
    evt = pairs[0][0]
    assert (evt["type"], evt["session_key"], evt["task_id"], evt["job_id"]) == (
        "mcp_job_finished", SESSION, SESSION, JOB)


def test_failed_build_wake_carries_the_failure_tail(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    _notify(_finished(outcome="failed", failure_tail="error: lib/x.dart:12: Undefined name 'y'"))
    [(_evt, text)] = _drained(registry)
    assert text.startswith(f"[IMPORTANT: QA build failed, job {JOB} — ")
    assert "Failure tail:\nerror: lib/x.dart:12: Undefined name 'y'" in text


def test_a_foreign_session_cannot_drain_the_wake(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    _notify(_finished())
    assert registry.drain_notifications(session_key="persona_chat_someone_else") == []
    assert len(_drained(registry)) == 1


def test_unknown_job_is_logged_and_dropped(registry, caplog):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    with caplog.at_level(logging.INFO, logger="tools.mcp_tool"):
        _notify(_finished(job_id="qab-nobody-routed-this"))
    assert registry.completion_queue.empty()
    assert any("qab-nobody-routed-this" in r.getMessage() and "not waking" in r.getMessage() for r in caplog.records)


def test_a_result_naming_a_finished_job_routes_nothing(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope(status="ready"))
    _notify(_finished())
    assert registry.completion_queue.empty()


def test_non_job_notifications_stay_log_only(registry, caplog):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    with caplog.at_level(logging.INFO, logger="tools.mcp_tool"):
        # The self-heal notice: another logger, no job event.
        _notify(SimpleNamespace(level="notice", logger="stagec_qa_mcp_server.self_heal",
                                data={"message": "server rebuilt", "job_id": JOB}))
        # The QA logger, a routed job, but not a FINISHED event.
        _notify(_finished(event="qa_build_progress"))
    assert registry.completion_queue.empty()
    assert any("server rebuilt" in r.getMessage() for r in caplog.records)  # still logged
    _notify(_finished())  # the route survived both: the real finish still wakes
    assert [text for _evt, text in _drained(registry)] == [READY_TEXT]


def test_a_duplicate_notification_never_wakes_twice(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope())
    _notify(_finished())
    _notify(_finished())
    assert len(_drained(registry)) == 1
    assert registry.completion_queue.empty()


def test_the_starting_caller_keeps_the_route(registry):
    _call_qa_tool(MagicMock(), _rebuilding_envelope(), task_id=SESSION)
    _call_qa_tool(MagicMock(), _rebuilding_envelope(), task_id="persona_chat_second_asker")
    _notify(_finished())
    [(evt, _text)] = _drained(registry)
    assert evt["task_id"] == SESSION


def test_serve_lane_steers_and_orphans_the_wake_like_a_terminal_completion():
    from agent_runtime.dispatch_delivery import completions
    assert "mcp_job_finished" in completions._PROCESS_LIKE_EVENTS
    evt = {"type": "mcp_job_finished", "session_key": "persona_chat_gone"}
    assert completions._orphaned_persona_root(evt, lambda _root: None) == "persona_chat_gone"


def test_generic_job_shape_is_covered(registry):
    reg_queue = registry.completion_queue
    mcp_job_wake.observe_call_result("other_srv", _Result({"job": {"job_id": "j-1"}}, is_error=False),
                                     {"session_key": SESSION, "task_id": SESSION})
    assert mcp_job_wake.on_log_notification(
        "other_srv", SimpleNamespace(logger="other", data={"event": "export_finished", "job_id": "j-1",
                                                           "outcome": "done", "message": "export.zip written"}))
    evt = reg_queue.get_nowait()
    assert isinstance(reg_queue, queue.Queue)
    assert mcp_job_wake.format_job_finished(evt) == (
        "[IMPORTANT: MCP server other_srv job j-1 finished (done).\nexport.zip written]")
