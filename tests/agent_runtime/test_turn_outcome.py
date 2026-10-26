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


# S2 binding. Mutation: drop ``raw_result["turn_outcome"] = outcome.block()`` -> the
# key is missing; drop the runner copy -> AgentRunResult.turn_outcome stays None.
def test_the_persona_runner_binds_the_fold_around_the_turn_and_carries_the_block():
    from agent_runtime.profile_runner import _run_conversation_with_usage_ledger
    from agent_runtime.profile_runner.runner import _normalize_result

    class _Agent:
        def run_conversation(self, **kwargs):
            _terminal("pytest -q", exit_code=0)
            return {"final_response": "ok"}

    class _Quiet:
        def run_conversation(self, **kwargs):
            return {"final_response": "ok"}

    result = _run_conversation_with_usage_ledger(_Agent(), {})
    assert result["turn_outcome"]["tests"] == [{"command": "pytest -q", "exit_code": 0, "verdict": "passed"}]
    assert _normalize_result(result, agent=_Agent()).turn_outcome == result["turn_outcome"]
    quiet = _run_conversation_with_usage_ledger(_Quiet(), {})
    assert quiet["turn_outcome"] is None
    assert _normalize_result(quiet, agent=_Quiet()).turn_outcome is None


# 5. Mutation: coerce instead of drop -> "0" becomes a passed test.
def test_safe_turn_outcome_drops_what_it_cannot_read():
    from agent_runtime.mission_chat_turns.records import safe_turn_outcome

    assert safe_turn_outcome(None) is None
    assert safe_turn_outcome(["schema", 1]) is None
    assert safe_turn_outcome({"schema": 2, "tests": [{"command": "pytest", "exit_code": 0, "verdict": "passed"}]}) is None
    block = safe_turn_outcome({
        "schema": 1,
        "tests": [
            {"command": "pytest a", "exit_code": "0", "verdict": "passed"},
            {"command": "pytest b", "exit_code": 1, "verdict": "flaky"},
            {"command": "pytest c", "exit_code": True, "verdict": "passed"},
            {"command": "pytest d", "exit_code": None, "verdict": "unknown"},
            "not a row",
        ],
        "commits": [
            {"command": "git commit", "sha": "abc1234", "pushed": False},
            {"command": "git commit", "sha": "nothex!", "pushed": None},
            {"command": "git commit -m ok", "sha": None, "pushed": True},
        ],
        "files": [{"path": "a.py", "op": "delete"}, {"path": "b.py", "op": "write"}],
        "truncated": "yes",
    })
    assert block == {
        "schema": 1,
        "tests": [{"command": "pytest d", "exit_code": None, "verdict": "unknown"}],
        "commits": [{"command": "git commit -m ok", "sha": None, "pushed": True}],
        "files": [{"path": "b.py", "op": "write"}],
        "truncated": False,
    }
    # Nothing readable is no block at all; a cap re-applied marks truncated.
    assert safe_turn_outcome({"schema": 1, "tests": [{"command": "", "exit_code": 0, "verdict": "passed"}]}) is None
    many = safe_turn_outcome({"schema": 1, "files": [{"path": f"f{i}", "op": "patch"} for i in range(70)]})
    assert len(many["files"]) == 64 and many["truncated"] is True


_STORED = {
    "schema": 1,
    "tests": [{"command": "pytest -q", "exit_code": 0, "verdict": "passed"}],
    "commits": [], "files": [{"path": "a.py", "op": "write"}], "truncated": False,
}


# 7. Mutation: default ``left_behind`` to {} -> the key appears, empty, on a turn with no block.
def test_execution_status_carries_left_behind_only_for_a_turn_with_a_block(tmp_path, monkeypatch):
    from agent_runtime.mission_chat_turns import persist_mission_chat_turn
    from agent_runtime.operator_execution import execution_status
    from tests.agent_runtime.operator_lane_fixture import OperatorLane
    from tests.agent_runtime.test_operator_conversation_attachment import fixture

    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    lane = OperatorLane(tmp_path / "home", lambda _argv: 0)
    for turn, extra in (("with-block", {"turn_outcome": dict(_STORED)}), ("no-block", {})):
        send = {**target, "turn_request_id": turn, "message": "Work"}
        assert lane.rpc("runtime.chat.message", send)["result"]["accepted"]
        persist_mission_chat_turn(
            session_id=target["session_id"], client_message_id=turn, turn_id=turn, state="projected",
            elements=[], metadata={"root_chat_session_id": target["session_id"],
                                   "persona_instance_id": target["persona_instance_id"], **extra})
    status = execution_status(target["session_id"], "with-block")
    assert status["outcome"] == "finished"
    assert status["left_behind"] == _STORED
    assert "left_behind" not in execution_status(target["session_id"], "no-block")


# 8. Mutation: drop the ``_carry_turn_outcome`` call at the agent-row site -> the
#    history row of a settled turn has no block.
def test_the_history_row_carries_the_block_and_an_older_record_leaves_it_untouched(monkeypatch):
    from agent_runtime.persona_chat_history import curation
    from agent_runtime.persona_chat_history.markers import _carry_turn_outcome
    from agent_runtime.persona_chat_history.vocabulary import MessageRole

    older: dict = {"id": "r0"}
    _carry_turn_outcome(older, {"state": "projected"})
    _carry_turn_outcome(older, None)
    assert older == {"id": "r0"}

    monkeypatch.setattr(curation, "mission_chat_turn_elements", lambda **_kw: [])
    state = curation.CurationState(
        session_id="s", turn_records=[],
        turn_records_by_message={"cm-1": {"client_message_id": "cm-1", "turn_outcome": dict(_STORED)}},
    )
    ctx = curation.RowContext(index=0, raw={}, role=MessageRole.AGENT, client_message_id="cm-1",
                              logical_client_message_id="cm-1", turn_id="cm-1")
    row: dict = {"id": "r1"}
    curation.ROLE_CURATORS[MessageRole.AGENT].after_row(state, row, ctx)
    assert row["turn_outcome"] == _STORED
    row["turn_outcome"]["tests"].clear()  # a copy: the record is not aliased
    assert state.turn_records_by_message["cm-1"]["turn_outcome"]["tests"]


def _repo_with_one_commit(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(git + ["add", "a.txt"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "a"], check=True)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    return repo, head


# RT-TURN-OUTCOME-QUIET-COMMIT-SHA. Mutation: keep `head` out of `_commit_row`
# (`match.group(1) if match else None`) -> both quiet commits read sha None.
def test_a_quiet_commit_reads_its_sha_from_the_repository(tmp_path):
    repo, head = _repo_with_one_commit(tmp_path)
    with bind_turn_outcome() as fold:
        on_post_tool_call(tool_name="terminal", args={"command": "git commit -q -m x", "workdir": str(repo)},
                          result=json.dumps({"output": "", "exit_code": 0}), status="ok", task_id="t")
        _terminal(f'git -C "{repo}" commit -q -m y', exit_code=0)
    assert [row["sha"] for row in fold.block()["commits"]] == [head, head]


# Positive control: the same repository, the same quiet line, a commit that FAILED —
# nothing landed, so HEAD is not this commit's sha and must not be claimed.
def test_a_failed_quiet_commit_claims_no_sha(tmp_path):
    repo, _head = _repo_with_one_commit(tmp_path)
    with bind_turn_outcome() as fold:
        _terminal(f'git -C "{repo}" commit -q -m y', exit_code=1)
    assert fold.block()["commits"][0]["sha"] is None
