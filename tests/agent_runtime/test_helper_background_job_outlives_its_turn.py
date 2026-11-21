"""A helper's background job keeps running after its turn, and its lead is told so.

RT-FU-A-HELPERS-BACKGROUND-JOB-DIES-WHEN-ITS-TURN-ENDS (seen 2026-11-21 07:21Z: a helper's background
``git bisect`` died with the child Hermes its dispatched turn ran in, about two hours short). A dispatched
turn now runs natively in the serve, so the job stays in the serve's process registry and its completion
comes back to the helper as a turn of its own (read live 2026-11-21, lane w1118a-onepath-hm). The local
supervisor names the jobs the turn left running on the dispatch's result, and the delivery tells the lead.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime.dispatch_delivery import format_dispatch_delivery
from agent_runtime.dispatch_store import get_dispatch, mint_dispatch_id, record_dispatch
from tests.agent_runtime.dispatch_turn_stub import StubTurn, bind_stub_turn
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import native

HELPER_ROOT = "persona_chat_personainst_dev_agent_8b319ebf_b48258a95ca8"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    return home


class _Registry:
    def __init__(self, rows):
        self.rows = rows
        self.asked: list[str | None] = []

    def list_sessions(self, task_id=None, session_key=None, **kw):
        self.asked.append(session_key)
        return list(self.rows)


@pytest.fixture
def registry(monkeypatch):
    import tools.process_registry as module

    fake = _Registry([
        {"session_id": "proc_bisect", "command": "git bisect run ./check.sh", "status": "running", "uptime_seconds": 0},
        {"session_id": "proc_old", "command": "npm run dev", "status": "running", "uptime_seconds": 9_000},
        {"session_id": "proc_done", "command": "ls", "status": "exited", "uptime_seconds": 1},
    ])
    monkeypatch.setattr(module, "process_registry", fake)
    return fake


def test_only_the_jobs_this_turn_started_and_left_running_are_named(registry):
    """*Killing mutation:* drop the ``uptime_seconds <= age`` test -> the helper's hours-old dev server
    is reported as this turn's job."""

    jobs = native.jobs_left_running({"session_id": HELPER_ROOT}, time.time() - 5)

    assert jobs == [{"session_id": "proc_bisect", "command": "git bisect run ./check.sh"}]
    assert registry.asked == [HELPER_ROOT]
    assert native.jobs_left_running({}, time.time()) == []


def test_the_lead_is_told_the_job_goes_on(store_home, registry, monkeypatch):
    """*Killing mutation:* drop ``background_jobs=`` from the local settle -> the delivery says nothing."""

    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id="persona_chat_personainst_neko_aaaaaaaaaaaa",
                    target_persona="dev", ask="bisect the red test")
    bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "Started the bisect.", "session_id": HELPER_ROOT}))

    agent_chat_dispatch._run_dispatch(dispatch_id, {
        "persona_id": "dev", "message": "bisect", "max_seconds": 5.0, "client_message_id": "agent-dispatch-bg",
    })

    row = get_dispatch(dispatch_id)
    assert row["result"]["background_jobs"] == [{"session_id": "proc_bisect", "command": "git bisect run ./check.sh"}]
    text = format_dispatch_delivery(row)
    assert "Still running after their turn ended (1):" in text
    assert "proc_bisect" in text and "keeps running" in text
