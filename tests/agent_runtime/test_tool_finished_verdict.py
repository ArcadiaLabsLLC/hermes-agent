"""RW5/RW3 — the ``run.tool.*`` lane tells the truth about how a tool call ended.

Live receipts, 2026-10-01 (``events.81417412.jsonl`` lines 17529-17530): the
same 160 s ``flutter build windows`` produced a ``run.progress`` event saying
``failed in 160297ms`` and a ``run.tool.finished`` event saying ``passed``, no
exit code, no output, no duration. The chat stream and the conversation's
``tool_call`` rows fold ONLY the second, so the operator's card for a failed
build was green and blank. Upstream hands ``tool_complete_callback`` the tool's
RESULT STRING; these pin that the verdict is read from the decoded envelope,
that a Hermes deadline is a distinct ``timed_out`` outcome, and that the
started event names the deadline the call will run under.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.profile_runner.progress import (
    ToolFinishJoin,
    _progress_adapter,
    _progress_payload_from_callback,
)


def _finished(tool, result, call_id="call_9", invocation=None):
    return _progress_payload_from_callback(
        "run.tool.finished", (call_id, tool, invocation or {"command": "flutter build windows"}, result), {}
    )


def _started(tool, invocation, call_id="call_9"):
    return _progress_payload_from_callback("run.tool.started", (call_id, tool, invocation), {})


def test_a_failed_build_result_string_is_failed_with_exit_code_and_output():
    payload = _finished("terminal", json.dumps(
        {"output": "Building...\nERROR: WebView2Loader.dll is locked", "exit_code": 1, "error": None}
    ))

    assert payload["status"] == "failed"
    assert payload["outcome"] == "failed"
    assert payload["exit_code"] == 1
    assert "WebView2Loader.dll" in payload["output"]
    assert payload["tool_call_id"] == "call_9"
    assert "timed_out" not in payload


def test_a_passing_result_string_stays_passed():
    """Positive control: the decode must not turn every terminal call red."""

    payload = _finished("terminal", json.dumps({"output": "ok", "exit_code": 0, "error": None}))

    assert payload["status"] == "passed"
    assert payload["outcome"] == "passed"
    assert payload["exit_code"] == 0


def test_a_hermes_deadline_is_a_timed_out_outcome():
    payload = _finished("terminal", json.dumps(
        {"output": "Building...\n[Command timed out after 180s]", "exit_code": 124, "error": None, "timed_out": True}
    ))

    assert payload["status"] == "failed"
    assert payload["outcome"] == "timed_out"
    assert payload["timed_out"] is True
    assert payload["exit_code"] == 124


def test_a_command_that_exits_124_itself_is_not_a_timeout():
    payload = _finished("terminal", json.dumps({"output": "", "exit_code": 124, "error": None}))

    assert payload["outcome"] == "failed"
    assert "timed_out" not in payload


def test_an_mcp_error_envelope_string_is_failed():
    """The ``open_app_tab`` → ``launch_stale_stagec_copy`` call of the same turn
    was ALSO recorded ``passed`` on this lane."""

    payload = _finished("mcp__launcher_qa__mcp_launcher_qa_open_app_tab", json.dumps(
        {"error": "{\"ok\":false,\"failure_class\":\"launch_stale_stagec_copy\"}"}
    ), invocation={"tab": "news"})

    assert payload["status"] == "failed"


@pytest.fixture
def terminal_module():
    import tools.terminal_tool as terminal

    return terminal


def test_the_started_event_names_the_foreground_deadline(terminal_module):
    default = int(terminal_module._get_env_config()["timeout"])
    cap = int(terminal_module.FOREGROUND_MAX_TIMEOUT)

    assert _started("terminal", {"command": "flutter build windows"})["timeout_seconds"] == default
    assert _started("terminal", {"command": "x", "timeout": cap})["timeout_seconds"] == cap
    # Over the cap the tool promotes the call to a background process, and a
    # background call has no foreground deadline at all.
    assert "timeout_seconds" not in _started("terminal", {"command": "x", "timeout": cap + 1})
    assert "timeout_seconds" not in _started("terminal", {"command": "x", "background": True})
    assert "timeout_seconds" not in _started("read_file", {"path": "x"})
    assert _started("terminal", {"command": "x"})["tool_call_id"] == "call_9"


def test_the_terminal_result_carries_hermes_timeout_flag():
    from tools.terminal_tool_result import finalize_foreground_result

    def finalize(result):
        return json.loads(finalize_foreground_result(
            command="sleep 999", result=result, env=SimpleNamespace(cwd=None), env_type="local",
            effective_task_id="t", task_id="t", session_id="s", session_key="k", workdir=None,
            command_cwd=None, approval_note=None,
        ))

    timed = finalize({"output": "[Command timed out after 180s]", "returncode": 124, "hermes_timed_out": True})
    own = finalize({"output": "", "returncode": 124})

    assert timed["timed_out"] is True
    assert "timed_out" not in own


# --------------------------------------------------------------------------- #
# One finished call, ONE published event (w3-turn, 2026-10-01)                 #
# --------------------------------------------------------------------------- #


def _upstream_pair(events, *, duration, is_error, result, tool="terminal", call_id="call_1"):
    """Fire the two callbacks exactly as ``agent.tool_executor`` does for one
    committed call: ``tool.completed`` on the progress callback, then
    ``tool_complete_callback`` -- one thread, back to back, sharing one join."""

    join = ToolFinishJoin()
    progress = _progress_adapter(events.append, "run.progress", join=join)
    complete = _progress_adapter(events.append, "run.tool.finished", join=join)
    progress("tool.completed", tool, None, None, duration=duration, is_error=is_error, result=result)
    complete(call_id, tool, {"command": "flutter build windows"}, result)


def test_one_finished_call_publishes_one_event_carrying_duration_and_verdict():
    """The 2026-10-01 pair: the executor said failed in 160297 ms, the result
    envelope read as passed. One event now, and it says failed with the time.

    *Killing mutations:* publish ``tool.completed`` again (drop the adapter's
    early ``return None``) -> two events; drop ``join.claim`` -> no
    ``duration_ms`` and ``passed``.
    """

    events = []
    _upstream_pair(events, duration=160.297, is_error=True, result=json.dumps({"output": "locked"}))

    assert [event["type"] for event in events] == ["run.tool.finished"]
    finished = events[0]
    assert finished["status"] == "failed"
    assert finished["duration_ms"] == 160297
    assert finished["tool_call_id"] == "call_1"
    assert finished["summary"] == "Finished tool terminal: failed in 160297ms"


def test_the_envelope_still_fails_a_call_the_executor_passed():
    """Either verdict fails the call -- the one event cannot be outvoted.
    Positive control beside it: both passing stays passed."""

    failed, passed = [], []
    _upstream_pair(failed, duration=1.0, is_error=False, result=json.dumps({"output": "", "exit_code": 2}))
    _upstream_pair(passed, duration=1.0, is_error=False, result=json.dumps({"output": "ok", "exit_code": 0}))

    assert [event["status"] for event in failed] == ["failed"]
    assert [event["status"] for event in passed] == ["passed"]
    assert passed[0]["duration_ms"] == 1000


def test_a_held_half_is_never_claimed_from_another_thread():
    """Keyed on the thread: a parallel call of the same tool on another thread
    cannot take this call's duration or verdict. Positive control: the holding
    thread claims it."""

    import threading

    join = ToolFinishJoin()
    worker = threading.Thread(target=join.hold, args=("terminal", {"duration": 2.0, "is_error": True}))
    worker.start()
    worker.join()
    assert join.claim("terminal") == {}

    join.hold("terminal", {"duration": 3.0, "is_error": False, "result": "ignored"})
    assert join.claim("terminal") == {"duration": 3.0, "is_error": False}
    assert join.claim("terminal") == {}


class _ToolCallingAgent:
    """Drives the runner's bound callbacks in upstream's order, then replies."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.session_id = kwargs.get("session_id") or "session_fake"

    def run_conversation(self, user_message, system_message=None, task_id=None):
        self.kwargs["tool_start_callback"]("call_7", "terminal", {"command": "flutter build windows"})
        self.kwargs["tool_progress_callback"](
            "tool.completed", "terminal", None, None, duration=4.5, is_error=True, result="{}")
        self.kwargs["tool_complete_callback"]("call_7", "terminal", {"command": "flutter build windows"}, "{}")
        return {"final_response": "ok", "session_id": self.session_id, "messages": [], "api_calls": 1}


def test_the_runner_binds_one_join_to_both_callbacks(monkeypatch):
    """The join is per run and SHARED -- the guarantee lives in
    ``execute.build_turn_state``, so it is pinned through the runner.

    *Killing mutation:* drop ``join=tool_finish_join`` from the
    ``tool_complete_callback`` line -> the finished event has no duration and
    reads ``passed``.
    """

    from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner

    monkeypatch.setattr(
        "agent_runtime.profile_runner.execute.resolve_runtime_provider",
        lambda requested, target_model: {"provider": requested, "model": target_model, "api_mode": "codex_responses"},
    )
    events = []
    ProfileAgentRunner(agent_factory=_ToolCallingAgent).run(
        AgentRunRequest(
            profile=None, provider="openai-codex", model="gpt-5.5", api_mode="codex_responses",
            session_id="session_1", user_message="build it", system_message="system",
            task_id="run_1", progress_callback=events.append,
        )
    )

    finished = [event for event in events if event.get("step") == "tool_finished"]
    assert [event["type"] for event in finished] == ["run.tool.finished"]
    assert finished[0]["status"] == "failed"
    assert finished[0]["duration_ms"] == 4500


# --------------------------------------------------------------------------- #
# Every tool start carries its input preview (w3-turn, 2026-10-01)             #
# --------------------------------------------------------------------------- #
_MCP = "mcp__launcher_qa__mcp_launcher_qa_get_runtime_state"


def _sunk_start(tool, invocation):
    """The started payload AFTER the progress sink's redaction boundary -- the
    record the stream frame, the trace row and the Launcher read."""

    from agent_runtime.progress import _safe_progress_payload

    return _safe_progress_payload("run.tool.started", _started(tool, invocation))


def test_an_argument_less_mcp_start_says_so():
    """events.81417412.jsonl 17586: ``get_runtime_state`` started with no input
    field at all, indistinguishable from "input not reported".

    *Killing mutation:* ``return TOOL_INPUT_NO_ARGUMENTS`` -> ``return None``.
    *Positive control:* a start WITH arguments carries them.
    """

    from agent_runtime.profile_runner.operator_redaction import TOOL_INPUT_NO_ARGUMENTS

    assert _sunk_start(_MCP, {})["tool_input"] == TOOL_INPUT_NO_ARGUMENTS
    assert 'tab: "news"' in _sunk_start(_MCP, {"tab": "news", "screenshot": False})["tool_input"]


def test_a_start_whose_every_argument_is_secret_still_says_it_had_input():
    """*Killing mutation:* drop ``or TOOL_INPUT_ALL_REDACTED`` -> no field.
    The secret itself never reaches the record."""

    from agent_runtime.profile_runner.operator_redaction import TOOL_INPUT_ALL_REDACTED

    started = _sunk_start(_MCP, {"api_key": "sk-live-1234567890abcdef"})
    assert started["tool_input"] == TOOL_INPUT_ALL_REDACTED
    assert "sk-live" not in json.dumps(started)


def test_a_raw_json_argument_string_is_previewed():
    """*Killing mutation:* drop the ``isinstance(invocation, str)`` decode ->
    no field for a runtime that hands the raw arguments string."""

    assert 'tab: "news"' in _sunk_start(_MCP, json.dumps({"tab": "news"}))["tool_input"]


def test_a_terminal_start_keeps_its_command_as_the_input_record():
    """Unchanged: ``command_full`` IS a terminal call's input, never doubled."""

    started = _sunk_start("terminal", {"command": "flutter build windows"})
    assert started["command_full"] == "flutter build windows"
    assert "tool_input" not in started
