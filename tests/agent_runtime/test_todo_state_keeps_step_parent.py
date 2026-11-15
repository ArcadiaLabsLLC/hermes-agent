"""RT-TODO-STATE-KEEPS-STEP-PARENT: a nested plan reaches Eternia nested, live and saved.

The todo tool keeps an optional ``parent`` per item. The finished-tool copy
(``tool_payloads._todo_state_payload``, the live ``tool.finished`` lane) and its
saved-turn twin (``mission_chat_turns._safe_todo_state``, the reloaded turn) used to
rebuild each item from id, content and status only, so a sub-step arrived flat. Both
now keep ``parent`` when it names ANOTHER item inside the same capped list, and drop it
otherwise; a client that ignores the key reads the same flat list as before.
"""
from __future__ import annotations

from agent_runtime.mission_chat_turns import _safe_todo_state
from agent_runtime.profile_runner.tool_payloads import _TODO_STATE_MAX_ITEMS, _tool_finished_payload
from tools.todo_tool import TodoStore, todo_tool


def _live_and_saved(todos):
    store = TodoStore()
    invocation = {"todos": todos}
    payload = _tool_finished_payload("run.tool.finished", "todo", duration=0.1, is_error=False,
                                     result=todo_tool(todos, store=store), invocation=invocation)
    live = payload["todo_state"]
    return live, _safe_todo_state(live)


def test_a_sub_step_keeps_its_parent_live_and_saved():
    live, saved = _live_and_saved([
        {"id": "build", "content": "Build the conversion", "status": "in_progress"},
        {"id": "convert", "content": "Convert saved documents", "status": "pending", "parent": "build"},
        {"id": "ship", "content": "Ship it", "status": "pending"},
    ])
    assert live == [
        {"id": "build", "content": "Build the conversion", "status": "in_progress"},
        {"id": "convert", "content": "Convert saved documents", "status": "pending", "parent": "build"},
        {"id": "ship", "content": "Ship it", "status": "pending"},
    ]
    assert saved == live  # the reloaded turn is byte-identical to the live frame


def test_a_flat_plan_carries_no_parent_key():
    live, saved = _live_and_saved([{"id": "a", "content": "one", "status": "pending"}])
    assert all("parent" not in item for item in live + saved)


def test_a_parent_cut_off_by_the_item_cap_is_dropped():
    # The child sits inside the cap, its parent past it: the client never receives the
    # parent row, so the child must not point at it (it shows at the top level).
    todos = [{"id": f"s{i}", "content": f"step {i}", "status": "pending"} for i in range(_TODO_STATE_MAX_ITEMS)]
    todos.append({"id": "late", "content": "past the cap", "status": "pending"})
    todos[1]["parent"] = "late"
    live, saved = _live_and_saved(todos)
    assert len(live) == _TODO_STATE_MAX_ITEMS
    assert "parent" not in live[1]
    assert saved == live


def test_the_saved_twin_drops_a_foreign_or_self_parent():
    # Foreign / legacy rows reach the persist boundary without the producer's rule.
    saved = _safe_todo_state([
        {"id": "a", "content": "one", "status": "pending", "parent": "nowhere"},
        {"id": "b", "content": "two", "status": "pending", "parent": "b"},
        {"id": "c", "content": "three", "status": "pending", "parent": "a"},
    ])
    assert saved == [
        {"id": "a", "content": "one", "status": "pending"},
        {"id": "b", "content": "two", "status": "pending"},
        {"id": "c", "content": "three", "status": "pending", "parent": "a"},
    ]
