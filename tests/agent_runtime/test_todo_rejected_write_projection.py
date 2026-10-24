"""RT-TODO-REJECTED-WRITE-PROJECTION: a refused todo write projects NO checklist.

``TodoStore.write`` keeps the previous list when it refuses; the finished payload
(live lane) and the persisted turn record (``records._safe_todo_state`` reads the
same ``todo_state``) must not show the rejected input in its place.
"""
from __future__ import annotations

from agent_runtime.mission_chat_turns import _safe_todo_state
from agent_runtime.profile_runner.tool_payloads import _tool_finished_payload
from tools.todo_tool import TodoStore, todo_tool


def _finished(result, invocation):
    return _tool_finished_payload("run.tool.finished", "todo", duration=0.1, is_error=False,
                                  result=result, invocation=invocation)


def test_a_rejected_write_leaves_the_prior_plan_and_projects_nothing():
    store = TodoStore()
    todo_tool([{"id": "a", "content": "existing", "status": "pending"}], store=store)
    rejected = {"todos": [{"id": "b", "content": "", "status": "pending"}]}

    result = todo_tool(rejected["todos"], store=store)

    assert '"error"' in result
    assert [item["content"] for item in store.read()] == ["existing"]
    payload = _finished(result, rejected)
    assert "todo_state" not in payload
    assert _safe_todo_state(payload.get("todo_state")) is None


def test_an_accepted_write_projects_the_store_list():
    store = TodoStore()  # positive control: same shape, accepted
    invocation = {"todos": [{"id": "b", "content": "next", "status": "in_progress"}]}
    payload = _finished(todo_tool(invocation["todos"], store=store), invocation)
    assert payload["todo_state"] == [{"id": "b", "content": "next", "status": "in_progress"}]


def test_an_explicit_successful_empty_write_still_clears():
    store = TodoStore()
    todo_tool([{"id": "a", "content": "existing", "status": "pending"}], store=store)
    payload = _finished(todo_tool([], store=store), {"todos": []})
    assert payload["todo_state"] == []
