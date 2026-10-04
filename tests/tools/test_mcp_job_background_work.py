"""A pending MCP background job (a QA build) shows in background work like a background terminal.

The join, end to end: a ``launch_or_attach`` result names a running ``build_job`` →
``tools/mcp_job_wake.py`` writes a row to ``mcp_jobs.json`` in the background-work home → the
``running_work`` projection's ``mcp_job`` lane (``agent_runtime/running_work/lanes_process.py``)
ships it beside the ``terminal`` lane's rows → the finish notification turns it ready/failed →
the serve drain settling the wake retires it.
"""

import os
import time

import pytest

from agent_runtime.dispatch_delivery import completions
from agent_runtime.dispatch_delivery.forge import DrainPolicy
from agent_runtime.running_work import build_running_work
from tests.tools.test_mcp_job_wake import (  # noqa: F401 — `registry` is the shared fixture
    JOB,
    SERVER,
    SESSION,
    _call_qa_tool,
    _finished,
    _notify,
    _rebuilding_envelope,
    registry,
)
from tools import mcp_job_wake
from unittest.mock import MagicMock

COMMIT = "abc1234def5678"
JOB_WORK_ID = f"mcp_job:{SERVER}:{JOB}"


@pytest.fixture
def head(tmp_path, monkeypatch):
    """The REAL resolver on both sides: the writer and the reader must name one directory."""
    profile, head_home = tmp_path / "profiles" / "neko", tmp_path / "profiles" / "base"
    profile.mkdir(parents=True)
    head_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head_home))
    return head_home


def _qa_envelope(job_id=JOB, status="running"):
    envelope = _rebuilding_envelope(job_id=job_id, status=status)
    envelope["build_job"].update(commit=COMMIT, eta_ms=200_000, expected_ms=240_000, elapsed_ms=40_000)
    return envelope


def _rows(kind=None):
    rows = build_running_work()["rows"]
    return [row for row in rows if kind is None or row["kind"] == kind]


def _terminal_checkpoint(head_home):
    """A background ``terminal`` as the process registry checkpoints it — this very process."""
    from gateway.status import get_process_start_time
    import json
    # Not a build command: a build-shaped terminal row is reclassified to ``build`` (build plan H4).
    entry = {"session_id": "proc_control", "command": "npm run dev", "pid": os.getpid(),
             "host_start_time": get_process_start_time(os.getpid()), "started_at": time.time() - 5,
             "session_key": SESSION}
    (head_home / "processes.json").write_text(json.dumps([entry]), encoding="utf-8")


class _Forge:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return True, {"ok": True}


def test_positive_control_a_terminal_and_an_mcp_job_side_by_side(registry, head):
    _terminal_checkpoint(head)
    _call_qa_tool(MagicMock(), _qa_envelope())
    by_kind = {row["kind"]: row for row in _rows()}
    assert set(by_kind) >= {"terminal", "mcp_job"}
    assert by_kind["terminal"]["work_id"] == "terminal:proc_control"
    job = by_kind["mcp_job"]
    assert (job["work_id"], job["label"], job["status"]) == (JOB_WORK_ID, "QA build abc1234", "running")
    assert (job["server"], job["job_id"], job["job_kind"]) == (SERVER, JOB, "qa_build")
    assert (job["eta_ms"], job["expected_ms"], job["outcome"]) == (200_000, 240_000, None)
    assert job["started_at"] and job["elapsed_seconds"] >= 40
    assert job["owner"]["session_id"] == SESSION and job["pid_verified"] is True
    assert build_running_work()["sources"]["mcp_job"] == {"status": "ok", "lane": "durable"}


def test_the_finish_notification_marks_the_row_failed_with_elapsed_and_tail(registry, head):
    _call_qa_tool(MagicMock(), _qa_envelope())
    _notify(_finished(outcome="failed", failure_tail="error: lib/x.dart:12: Undefined name 'y'"))
    [job] = _rows("mcp_job")
    assert (job["status"], job["outcome"], job["elapsed_seconds"], job["eta_ms"]) == ("error", "failed", 281, 0)
    assert "Undefined name 'y'" in job["tail_preview"]
    assert job["finished_at"]


def test_a_ready_build_reads_completed(registry, head):
    _call_qa_tool(MagicMock(), _qa_envelope())
    _notify(_finished())
    [job] = _rows("mcp_job")
    assert (job["status"], job["outcome"]) == ("completed", "ready")


def test_an_unrouted_job_never_adds_an_entry(registry, head):
    _notify(_finished(job_id="qab-nobody-routed-this"))
    _call_qa_tool(MagicMock(), _qa_envelope(status="ready"))  # a FINISHED job routes nothing either
    assert _rows("mcp_job") == []
    assert not (head / mcp_job_wake.CHECKPOINT_FILENAME).exists()


def test_a_duplicate_bind_or_finish_never_adds_an_entry(registry, head):
    _call_qa_tool(MagicMock(), _qa_envelope())
    _call_qa_tool(MagicMock(), _qa_envelope(), task_id="persona_chat_second_asker")
    _notify(_finished())
    _notify(_finished(outcome="failed"))  # the duplicate is dropped; it must not rewrite the row
    [job] = _rows("mcp_job")
    assert (job["owner"]["session_id"], job["status"]) == (SESSION, "completed")


def test_the_entry_leaves_once_the_drain_delivers_the_wake(registry, head):
    _call_qa_tool(MagicMock(), _qa_envelope())
    _notify(_finished())
    assert len(_rows("mcp_job")) == 1
    completions._background_attempts.clear()
    policy = DrainPolicy(sender_persona=lambda root: ("neko", "personainst_neko") if root == SESSION else None,
                         sender_is_idle=lambda _root: True)
    forge = _Forge()
    tally = completions.drain_background_completions(policy=policy, forge=forge)
    assert tally["delivered"] == 1 and len(forge.calls) == 1
    assert _rows("mcp_job") == []


def test_an_expired_entry_is_not_shown(registry, head, monkeypatch):
    _call_qa_tool(MagicMock(), _qa_envelope())
    monkeypatch.setattr(time, "time", lambda real=time.time: real() + mcp_job_wake._ROUTE_TTL_S + 1)
    assert _rows("mcp_job") == []
