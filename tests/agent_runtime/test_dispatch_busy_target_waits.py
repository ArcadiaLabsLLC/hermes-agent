"""RT-A-LEADS-STOP-TO-A-BUSY-HELPER-COMES-BACK-AS-WORK-FAILED.

Seen live 2026-11-19: a lead sent its lane a stop order with
``agent_chat_send(wait=false)`` while the lane was still on the lead's first
dispatch. The stop's child turn was refused ``chat_busy`` before anything ran,
the supervisor recorded that refusal as the dispatch's failure, and the lead's
chat read "Launcher Dev Agent's work failed: persona chat root is busy: …".

Pinned here, through the supervisor's real body (``_run_dispatch``) with only
the child process faked: a busy target is waited out and the message runs once
the target is free; a target busy for the whole wait is reported as "never
ran", not as raw lease text; a cancel during the wait settles ``cancelled``;
and the sending agent can stop its own dispatch from ``agent_chat_dispatches``.

Named sabotage (each red recorded in the landing commit):

* ``local._run_dispatch_guarded``: ``busy_root = None`` (never wait) →
  the first and third tests red (the row is ``error`` after one child).
* ``child._LANE_REWRITES``: drop the ``chat_busy`` entry → the second red.
* ``detached.agent_chat_dispatches``: drop the ``cancel`` arm → the last two red.
"""

from __future__ import annotations

import io
import json

import pytest

from agent_runtime.dispatch_store import (
    STATE_CANCELLED,
    STATE_ERROR,
    STATE_RUNNING,
    get_dispatch,
    mint_dispatch_id,
    record_dispatch,
)
from tools import agent_chat_dispatch
import tools.agent_chat_dispatch.local_child  # the spawn the tests patch
from tools.agent_chat_dispatch import local
from tools.agent_chat_tool import agent_chat_dispatches

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"
TARGET_ROOT = "persona_chat_personainst_dev_agent_8b319ebf_564c80cf8806"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(local, "BUSY_TARGET_POLL_SECONDS", 0.0)
    monkeypatch.setattr(local, "_child_identity", lambda pid: 777)
    monkeypatch.setattr(local, "_kill_child", lambda pid, started: None)
    return home


class _Proc:
    def __init__(self, payload: dict, returncode: int):
        self.pid = 4242
        self.stdout = io.StringIO(json.dumps(payload))
        self.stderr = io.StringIO("")
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode


def _busy() -> _Proc:
    # The chat lane's own refusal shape (``chat_admission._busy_refused``).
    return _Proc(
        {
            "ok": False,
            "capability_id": "mission.chat.message",
            "error_kind": "chat_busy",
            "chat_busy": True,
            "root_chat_session_id": TARGET_ROOT,
            "session_id": TARGET_ROOT,
            "error": f"persona chat root is busy: {TARGET_ROOT}",
        },
        2,
    )


def _replied() -> _Proc:
    return _Proc(
        {"ok": True, "capability_id": "mission.chat.message", "reply": "stopped at abc123",
         "session_id": TARGET_ROOT},
        0,
    )


def _children(monkeypatch, procs: list[_Proc]) -> list[_Proc]:
    spawned: list[_Proc] = []

    def popen(*a, **k):
        proc = procs.pop(0)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(agent_chat_dispatch.local_child.subprocess, "Popen", popen)
    return spawned


def _dispatch(sender: str = SENDER_ROOT) -> str:
    dispatch_id = mint_dispatch_id()
    record_dispatch(
        dispatch_id=dispatch_id,
        sender_session_id=sender,
        target_persona="@personainst_dev_agent_8b319ebf",
        ask="STOP order: commit what you have and stop.",
    )
    return dispatch_id


def _spec(max_seconds: float = 5.0) -> dict:
    return {"persona_id": "dev", "message": "STOP order", "max_seconds": max_seconds}


def test_a_message_to_a_busy_teammate_waits_and_runs_once_they_are_free(store_home, monkeypatch):
    dispatch_id = _dispatch()
    spawned = _children(monkeypatch, [_busy(), _replied()])
    looked: list[str] = []
    monkeypatch.setattr(local, "chat_root_is_busy", lambda root, probe_owner: looked.append(root) and False)

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == "completed", row["result"]
    assert row["result"]["reply"] == "stopped at abc123"
    assert len(spawned) == 2
    # It looked at the root that refused it, not at some other root.
    assert looked == [TARGET_ROOT]


def test_a_teammate_busy_the_whole_wait_is_reported_as_never_ran(store_home, monkeypatch):
    dispatch_id = _dispatch()
    _children(monkeypatch, [_busy()])
    monkeypatch.setattr(local, "chat_root_is_busy", lambda root, probe_owner: True)

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec(max_seconds=0.05))

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    error = row["result"]["error"]
    assert error.startswith("Not delivered")
    assert "never ran" in error and "agent_chat_dispatches(cancel=" in error
    assert "persona chat root is busy" not in error


def test_a_cancel_while_waiting_settles_cancelled_not_failed(store_home, monkeypatch):
    dispatch_id = _dispatch()
    spawned = _children(monkeypatch, [_busy(), _replied()])

    def still_busy_and_cancelled(root, probe_owner):
        local._request_cancel_mark(dispatch_id, "sender_cancel")
        return True

    monkeypatch.setattr(local, "chat_root_is_busy", still_busy_and_cancelled)

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_CANCELLED
    assert "sender_cancel" in row["result"]["error"]
    assert len(spawned) == 1


def test_a_lead_can_stop_its_own_dispatch(store_home):
    dispatch_id = _dispatch()

    answer = json.loads(
        agent_chat_dispatches(cancel=dispatch_id, requested_by_session=SENDER_ROOT)
    )

    assert answer["ok"] is True
    assert answer["outcome"] == "cancelled"
    assert get_dispatch(dispatch_id)["state"] == STATE_CANCELLED


def test_a_lead_cannot_stop_another_agents_dispatch(store_home):
    dispatch_id = _dispatch(sender="persona_chat_personainst_other_bbbbbbbbbbbb")

    answer = json.loads(
        agent_chat_dispatches(cancel=dispatch_id, requested_by_session=SENDER_ROOT)
    )

    assert answer["ok"] is False
    assert answer["error_kind"] == "dispatch_not_yours"
    assert get_dispatch(dispatch_id)["state"] == STATE_RUNNING
