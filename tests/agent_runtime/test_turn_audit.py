"""``RT-TURN-AUDIT-ENTRY`` — ``mission-chat audit`` / ``runtime.chat.turn_audit`` over the turn journal.

Each test names the mutation that kills it (recorded in the landing commit).
"""

from __future__ import annotations

from agent_runtime.chat_verbs.turn_audit import _git_changes, turn_audit
from agent_runtime.mission_chat_turns import persist_mission_chat_turn, transition_mission_chat_turn
from agent_runtime.turn_usage import safe_turn_usage


def _tool(seq, command, *, exit_code=0, duration_ms=10, outcome="passed", name="terminal"):
    return {"kind": "tool", "id": f"t_{seq}", "turn_id": "turn", "seq": seq, "state": "finished",
            "name": name, "command": command, "exit_code": exit_code, "duration_ms": duration_ms,
            "outcome": outcome, "status": "passed" if outcome == "passed" else "failed"}


def _seed(session_id, message_id, *, instance, elements, metadata=None):
    meta = {"persona_instance_id": instance, "root_chat_session_id": session_id}
    elements = [{**element, "turn_id": message_id, "id": f"{message_id}_{element['id']}"} for element in elements]
    persist_mission_chat_turn(session_id=session_id, client_message_id=message_id, turn_id=message_id,
                              elements=[], state="pending", write_ahead=True, metadata=meta)
    transition_mission_chat_turn(session_id=session_id, client_message_id=message_id, turn_id=message_id,
                                 elements=[], state="executing")
    transition_mission_chat_turn(session_id=session_id, client_message_id=message_id, turn_id=message_id,
                                 elements=elements, state="native_committed", metadata={**meta, **(metadata or {})})


# Mutation: drop the ``worktree`` arm of ``_git_changes`` -> no worktree row; drop the
# ``-b`` capture -> no branch row.
def test_git_changes_reads_worktrees_and_branches_with_their_exit_code():
    worktrees, branches = _git_changes(
        'cd /c/ && git -C "$R" worktree add --lock --reason "lane x live" C:/wt/x -b wave/x origin/main 2>&1 | tail -5;'
        " git -C C:/r worktree remove C:/wt/y && git branch -D wave/y", 1)
    assert worktrees == [{"op": "add", "path": "C:/wt/x", "exit_code": 1},
                         {"op": "remove", "path": "C:/wt/y", "exit_code": 1}]
    assert branches == [{"op": "create", "name": "wave/x", "exit_code": 1},
                        {"op": "delete", "name": "wave/y", "exit_code": 1}]
    assert _git_changes('git commit -m "worktree add C:/nope"', 0) == ([], [])


# Mutation: drop the persona filter in ``matches`` -> the other instance's turn is listed;
# set ``timed_out`` from ``status`` -> the timed-out call reads False.
def test_audit_lists_one_instances_turns_with_every_tool_call(isolate_agent_runtime_root):
    _seed("chat_a", "turn_a", instance="inst_a", metadata={
        "provider_usage": {"schema": 1, "model": "m", "provider": "p", "input_tokens": 7}},
        elements=[_tool(1, "git worktree add C:/wt/a -b a origin/main"),
                  _tool(2, "flutter test x", exit_code=124, duration_ms=60000, outcome="timed_out")])
    _seed("chat_c", "turn_c", instance="inst_c", elements=[])

    audit = turn_audit(persona_instance_id="inst_a", price=lambda usage: {"usd": "0.01", "status": "estimated"})

    assert audit["ok"] is True and audit["total"] == 1
    [turn] = audit["turns"]
    assert turn["turn_id"] == "turn_a"
    assert [call["timed_out"] for call in turn["tool_calls"]] == [False, True]
    assert turn["tool_calls"][1]["duration_ms"] == 60000 and turn["tool_ms"] == 60010
    assert turn["worktrees"] == [{"op": "add", "path": "C:/wt/a", "exit_code": 0}]
    assert turn["branches"] == [{"op": "create", "name": "a", "exit_code": 0}]
    assert turn["usage"]["input_tokens"] == 7 and turn["cost"]["usd"] == "0.01"
    assert audit["namespace"]["kind"] == "base" and audit["namespace"]["id"] == "base"
    assert turn_audit(session_id="chat_c")["turns"][0]["usage"] is None


def test_audit_refuses_an_unfiltered_read():
    assert turn_audit()["error_kind"] == "invalid_request"


# Mutation: remove ``_count``'s ``type(value) is int`` guard -> True is admitted.
def test_safe_turn_usage_drops_what_it_cannot_read():
    assert safe_turn_usage(None) is None
    assert safe_turn_usage({"schema": 2, "input_tokens": 1}) is None
    assert safe_turn_usage({"schema": 1, "input_tokens": True, "output_tokens": -1}) is None
    assert safe_turn_usage({"schema": 1, "input_tokens": 3, "calls": [{"input_tokens": 2}, "x"]}) == {
        "schema": 1, "input_tokens": 3, "calls": [{"call_index": 1, "input_tokens": 2}]}


def test_the_rpc_twin_returns_the_argv_row(isolate_agent_runtime_root):
    from agent_runtime.serve_rpc.chat_verbs import _runtime_chat_turn_audit

    reply = _runtime_chat_turn_audit("r1", {"session_id": "chat_none"})
    assert reply["result"]["ok"] is True and reply["result"]["turns"] == []
    refused = _runtime_chat_turn_audit("r2", {"limit": "x"})
    assert refused["error"]["data"]["reason"] == "invalid_request"
