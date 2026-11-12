"""``RT-SUBAGENT-HISTORY-RESULT-HAS-NO-GOAL``: a finished helper's History entry says what it was asked.

Seen live 2026-11-12 (Eternia lane w1112b-worklive2, hermes 7bb8dbd9f6): the History entry of a helper's
own helper was titled "Task 1" with no goal. A result read from the delegation store takes its goal from
the stored task; one read from the TRANSCRIPT (a ``delegate_task`` tool result — every synchronous
delegation, so every helper a helper ran) had none: upstream's result entry carries no goal.

The goal is in the same transcript: the assistant's ``delegate_task`` call the result answers. Real
SessionDB rows written by the real ``append_message`` and upstream's own result builder; the read is the
real read-only ``inspect_history``.

Killing mutation (recorded red in the commit body): ``read_result_history`` passes ``entry.get("goal")``
alone (the code as it was) → the three goal tests red (``None``).
"""
import json

from tests.agent_runtime.test_subagent_history import history_call, native_result, stored  # stored: fixture


def _delegated(db, session_id, call_id, arguments, results):
    """One ``delegate_task`` call and its result, as a turn stores them."""

    db.append_message(session_id, "assistant", "", tool_calls=[
        {"id": call_id, "type": "function", "function": {"name": "delegate_task", "arguments": json.dumps(arguments)}}])
    payload = results[0] if len(results) == 1 else {"results": results}
    db.append_message(session_id, "tool", json.dumps(payload), tool_name="delegate_task", tool_call_id=call_id)


def _goals(home, db):
    roster = history_call(home, db)
    listed = [row["goal"] for row in roster["results"]]
    opened = [history_call(home, db, "result", {"expected_generation": roster["generation"],
                                                 "history_ref": row["history_ref"]})["result"]["goal"]
              for row in roster["results"]]
    assert listed == opened, "the list and the opened result say the same goal"
    return listed


def test_a_transcript_result_takes_its_goal_from_the_call_it_answers(stored):
    home, db = stored
    _delegated(db, "parent", "call-1", {"goal": "Count the sheep in the meadow", "context": "PRIVATE"},
               [native_result("Forty sheep")])
    assert _goals(home, db) == ["Count the sheep in the meadow"]


def test_a_helpers_own_helpers_result_has_its_goal(stored):
    """The live case: the delegation ran inside a helper's session (``nested`` is ``_delegate_from`` parent)."""

    home, db = stored
    _delegated(db, "nested", "call-n", {"goal": "Hold one model call for seven minutes"}, [native_result("Held")])
    assert _goals(home, db) == ["Hold one model call for seven minutes"]


def test_a_batch_gives_each_result_its_own_task_goal_and_redacts_it(stored):
    home, db = stored
    tasks = {"tasks": [{"goal": "Mow the north field"}, {"goal": "Mend the gate api_key=secret123"}]}
    _delegated(db, "parent", "call-b", tasks,
               [{**native_result("Mown"), "task_index": 0}, {**native_result("Mended"), "task_index": 1}])
    goals = _goals(home, db)
    assert len(goals) == 2 and "Mow the north field" in goals, goals
    mended = next(goal for goal in goals if goal.startswith("Mend the gate"))
    assert "secret123" not in mended, "a goal crosses the same redaction as every other history text"


def test_a_result_with_no_call_to_read_stays_without_a_goal_and_a_stated_goal_is_kept(stored):
    """Controls: absent facts stay absent (no guess from another call), and nothing overrides a goal an
    entry states itself."""

    home, db = stored
    _delegated(db, "foreign", "call-1", {"goal": "ANOTHER CONVERSATION"}, [native_result("Foreign")])
    db.append_message("parent", "tool", json.dumps(native_result("Orphan")), tool_name="delegate_task",
                      tool_call_id="call-1")
    assert _goals(home, db) == [None], "the same call id in another session is not this result's call"

    _delegated(db, "nested", "call-2", {"goal": "from the call"}, [{**native_result("Stated"), "goal": "stated by the entry"}])
    assert "stated by the entry" in _goals(home, db) and "from the call" not in _goals(home, db)
