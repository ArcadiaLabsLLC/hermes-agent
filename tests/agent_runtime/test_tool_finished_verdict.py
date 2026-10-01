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

from agent_runtime.profile_runner.progress import _progress_payload_from_callback


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
