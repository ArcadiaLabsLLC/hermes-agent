"""RT-RUNNING-CHAT-TURN-CARRIES-PLAN-PROGRESS: a running chat turn says where its plan is.

A running chat turn row carried title, status and current tool and nothing about the
plan, so Eternia had no plan for a chat it had not opened. Inside the process executing
the turn, the row now carries ``plan: {done, total, current}`` read off the agent's own
todo store (``current`` = the step in progress, capped like ``todo_state``; cancelled
counts as resolved, as Eternia's ``AgentPlan.progress`` does), and omits ``plan`` when the
turn has no plan. Pinned through the running-work collector, not the helper alone.
"""
from __future__ import annotations

import pytest

from agent_runtime import live_turns
from agent_runtime.profile_runner.tool_payloads import _TODO_STATE_MAX_CONTENT
from agent_runtime.running_work import KIND_CHAT_TURN, build_running_work, lanes_chat, lanes_process, ownership
from tools.todo_tool import TodoStore

TURN = "turn-plan-1"
SESSION = "persona_chat_personainst_dev_agent_plan_000000000001"
INSTANCE = "personainst_dev_agent_plan"


@pytest.fixture
def journal(tmp_path, monkeypatch, isolate_agent_runtime_root):
    from agent_runtime.mission_chat_turns import persist_mission_chat_turn

    head = tmp_path / "home"
    head.mkdir()
    for module in (lanes_chat, lanes_process, ownership):
        if hasattr(module, "_head_home"):
            monkeypatch.setattr(module, "_head_home", lambda: (head, "test_home"))
    monkeypatch.setattr(lanes_chat, "_chat_titles", lambda ids: {})
    persist_mission_chat_turn(
        session_id=SESSION,
        client_message_id=TURN,
        turn_id=TURN,
        elements=None,
        state="executing",
        write_ahead=True,
        metadata={"persona_instance_id": INSTANCE, "root_chat_session_id": SESSION},
    )


class _Agent:
    def __init__(self, todos=None) -> None:
        self._todo_store = TodoStore()
        if todos:
            self._todo_store.write(todos)

    def get_activity_summary(self) -> dict:
        return {"api_call_count": 1, "seconds_since_activity": 1.0}


def _turn_row(agent):
    with live_turns.live_turn(turn_id=TURN, session_id=SESSION, persona_instance_id=INSTANCE, agent=agent):
        payload = build_running_work()
    [row] = [row for row in payload["rows"] if row["kind"] == KIND_CHAT_TURN]
    return row


def test_a_running_turn_with_a_plan_carries_its_progress(journal):
    long_step = "word " * 100
    row = _turn_row(_Agent([
        {"id": "1", "content": "Survey the old format", "status": "completed"},
        {"id": "2", "content": "Keep a shim", "status": "cancelled"},
        {"id": "3", "content": long_step, "status": "in_progress"},
        {"id": "3a", "content": "Convert saved documents", "status": "pending", "parent": "3"},
        {"id": "4", "content": "Delete the old renderer", "status": "pending"},
    ]))
    plan = row["plan"]
    assert (plan["done"], plan["total"]) == (2, 5)  # cancelled counts as resolved
    assert plan["current"].startswith("word word")
    assert len(plan["current"]) == _TODO_STATE_MAX_CONTENT and plan["current"].endswith("…")


def test_a_plan_with_no_step_in_progress_has_no_current(journal):
    row = _turn_row(_Agent([{"id": "1", "content": "Done already", "status": "completed"}]))
    assert row["plan"] == {"done": 1, "total": 1, "current": None}


def test_a_running_turn_with_no_plan_omits_it(journal):
    assert "plan" not in _turn_row(_Agent())


def test_a_turn_this_process_is_not_running_omits_it(journal):
    payload = build_running_work()
    [row] = [row for row in payload["rows"] if row["kind"] == KIND_CHAT_TURN]
    assert "plan" not in row
