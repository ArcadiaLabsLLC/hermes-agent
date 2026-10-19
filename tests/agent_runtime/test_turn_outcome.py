"""``RT-TURN-LEFT-BEHIND-RECORD`` — what a turn left behind (plan
``docs/agent-runtime-harness/planned/p10-turn-2026-10-19.md`` §1.5).

Each test names the mutation that kills it.
"""

from __future__ import annotations

import json

from agent_runtime.turn_outcome import (
    TURN_OUTCOME_MAX_TESTS,
    CommandKind,
    bind_turn_outcome,
    classify_command,
    on_post_tool_call,
)


def _terminal(command: str, *, exit_code, output: str = "", status: str = "ok") -> None:
    on_post_tool_call(
        tool_name="terminal", args={"command": command},
        result=json.dumps({"output": output, "exit_code": exit_code, "error": None}),
        status=status, task_id="t", turn_id="turn",
    )


# 1. Mutation: return the kinds in table order (push before commit) instead of line
#    order -> the combined line reads (PUSH, COMMIT) and the push cannot mark the commit.
def test_classify_command_walks_the_table_in_line_order():
    assert classify_command("pytest tests/x.py") == (CommandKind.TEST,)
    assert classify_command("git commit -m x") == (CommandKind.COMMIT,)
    assert classify_command("git commit -m x && git push") == (CommandKind.COMMIT, CommandKind.PUSH)
    assert classify_command("git -C X:/repo push origin HEAD:main") == (CommandKind.PUSH,)
    # Documented over-approximation: a quoted pytest still reads as a test.
    assert classify_command("echo 'pytest'") == (CommandKind.TEST,)
    # The verb is the git subcommand, not a word in the message.
    assert classify_command('git commit -m "push fix"') == (CommandKind.COMMIT,)
    assert classify_command("ls -la") == ()


# 2. Mutation: skip rows whose status != "ok" -> the failed test vanishes.
def test_the_hook_folds_a_failed_test_a_commit_and_its_push():
    with bind_turn_outcome() as fold:
        _terminal("python -m pytest tests/x.py", exit_code=1, output="1 failed", status="error")
        _terminal("git commit -m msg", exit_code=0, output="[main abc1234] msg\n 1 file changed")
        _terminal("git push origin main", exit_code=0)
        on_post_tool_call(tool_name="write_file", args={"path": "a.py"}, result="{}", status="ok")
        on_post_tool_call(tool_name="patch", args={"path": "a.py"}, result="{}", status="ok")
        on_post_tool_call(tool_name="patch", args={"path": "a.py"}, result="{}", status="ok")
        on_post_tool_call(tool_name="patch", args={"path": "b.py"}, result="{}", status="error")
        on_post_tool_call(tool_name="read_file", args={"path": "c.py"}, result="{}", status="ok")
    block = fold.block()
    assert block["schema"] == 1
    assert block["tests"] == [{"command": "python -m pytest tests/x.py", "exit_code": 1, "verdict": "failed"}]
    assert block["commits"] == [{"command": "git commit -m msg", "sha": "abc1234", "pushed": True}]
    assert block["files"] == [{"path": "a.py", "op": "write"}, {"path": "a.py", "op": "patch"}]
    assert block["truncated"] is False


def test_pushed_is_null_never_false_and_an_unknown_exit_is_unknown():
    with bind_turn_outcome() as fold:
        _terminal("git push", exit_code=1)  # a push before any commit marks nothing
        _terminal("git commit -am x && git push", exit_code=1, output="[main (root-commit) 0123abcd] x")
        _terminal("pytest -q", exit_code=None)
        _terminal("pytest -q", exit_code=0)
    block = fold.block()
    assert block["commits"] == [{"command": "git commit -am x && git push", "sha": "0123abcd", "pushed": None}]
    assert [row["verdict"] for row in block["tests"]] == ["unknown", "passed"]


# 3. Mutation: default-construct a fold when unbound -> a block appears outside a turn.
def test_unbound_hook_records_nothing_and_raises_nothing():
    from agent_runtime import turn_outcome

    _terminal("pytest", exit_code=0)
    on_post_tool_call()
    on_post_tool_call(tool_name="terminal", args=None, result=object())
    assert turn_outcome._FOLD.get() is None
    with bind_turn_outcome() as fold:
        on_post_tool_call(tool_name="terminal", args={"command": "ls"}, result="not json")
    assert fold.block() is None  # nothing folded: absent stays absent


# 4. Mutation: drop the cap -> 40 rows.
def test_caps_bound_the_rows_and_mark_truncated():
    with bind_turn_outcome() as fold:
        for index in range(40):
            _terminal(f"pytest tests/test_{index}.py", exit_code=0)
    block = fold.block()
    assert len(block["tests"]) == TURN_OUTCOME_MAX_TESTS == 32
    assert block["truncated"] is True
