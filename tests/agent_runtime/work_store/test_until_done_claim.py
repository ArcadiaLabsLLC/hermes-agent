"""``RT-WORK-CLAIM-RUNS-UNTIL-DONE``: a claim can ask its run to keep going until the task is done.

Owner ruling 2026-11-12: at most 20 passes, 30 minutes per pass, a visible Stop, done judged against the
task's text and its tests. The send queue, the goal binding and the claim's kept goal mode are real files
on this test's isolated home; the goal engine is ``contract_fakes.FakeGoals``.

Killing mutations (each recorded red in the commit body):
* ``arm_run`` drops ``max_turns`` → ``test_a_run_takes_at_most_twenty_passes_pinned_over_upstreams_default`` red;
* ``_ending_now`` drops the own-stopped-pass arm → ``test_stop_on_a_pass_ends_the_whole_run_not_one_pass`` red.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime import chat_goal, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store import goal_turns, until_done
from agent_runtime.work_store.executor import Assignment, Brief, GoalMode, Verdict
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor, parse_work_report

from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

ROOT = "persona_chat_root_until_done"
REF = RowRef("repo", "q.md", "RT-A")


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="neko", runtime_root=str(paths.store_root()))


def _started(request_id="run-1", **brief):
    goals = FakeGoals()
    executor = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   goals=goals, workdir_of=lambda instance: None)
    brief = Brief(title="Sweep the inbox", objective="Sweep the inbox\n\nAnswer every thread.", **brief)
    run = executor.start(Assignment((REF,), "inst-1", brief, request_id, goal_mode=GoalMode.UNTIL_DONE))
    return executor, goals(ROOT), run


def test_a_run_takes_at_most_twenty_passes_pinned_over_upstreams_default():
    from hermes_cli.goals import DEFAULT_MAX_TURNS

    assert chat_goal.MAX_PASSES == DEFAULT_MAX_TURNS == 20
    _executor, goal, _run = _started(tests=("pytest tests/inbox",))
    assert goal.state.max_turns == 20, "the run states its own cap; a configured default cannot widen it"
    assert goal.state.goal == "Sweep the inbox\n\nAnswer every thread." and goal.gates == ["pytest tests/inbox"]


def _settle(executor, cmid, payload, *, own=True):
    entry = send_queue.find(ROOT, cmid)
    if not own:
        entry = goal_turns.direct_entry(ROOT, "operator-send")
    executor.settled(entry, 0, payload)


def test_stop_on_a_pass_ends_the_whole_run_not_one_pass():
    """The run's own pass settling ``stopped: true`` (the conversation's Stop) ends the run STOPPED — the
    judge is never asked, so nothing can continue it."""

    executor, goal, run = _started()
    ended = []
    executor.on_settle(lambda r, outcome: ended.append(outcome))
    goal.decisions = [decision("continue", go_on=True)]
    _settle(executor, run.client_message_id, {"ok": True, "reply": "half way", "stopped": True})
    [outcome] = ended
    assert outcome.verdict is Verdict.STOPPED and outcome.per_row[REF].reason == "operator stop"
    assert goal.evaluated == [] and chat_goal.binding(ROOT) is None
    assert [e for e in send_queue.entries(ROOT) if e.client_message_id != run.client_message_id] == []


def test_an_operators_own_stopped_turn_on_the_root_does_not_end_the_run():
    executor, goal, run = _started()
    ended = []
    executor.on_settle(lambda r, outcome: ended.append(outcome))
    send_queue.remove(ROOT, run.client_message_id)  # the run's first pass has left the queue
    goal.decisions = [decision("continue", go_on=True)]
    _settle(executor, run.client_message_id, {"ok": True, "reply": "", "stopped": True}, own=False)
    assert ended == [] and len(goal.evaluated) == 1 and chat_goal.binding(ROOT) is not None


def test_a_pass_says_which_pass_it_is_and_only_the_runs_own_turn_does():
    executor, goal, run = _started()
    assert chat_goal.run_pass(ROOT, run.client_message_id) == {
        "work_request": "run-1", "goal": {"pass": 1, "max_passes": 20}}
    assert chat_goal.run_pass(ROOT, "operator-send") == {} and chat_goal.run_pass("other-root", "x") == {}
    goal.decisions = [decision("continue", go_on=True)]
    executor.settled(send_queue.find(ROOT, run.client_message_id), 0, {"ok": True, "reply": "more to do"})
    second = chat_goal.binding(ROOT).cmid
    assert second != run.client_message_id
    assert chat_goal.run_pass(ROOT, second)["goal"] == {"pass": 2, "max_passes": 20}
    assert chat_goal.run_pass(ROOT, run.client_message_id) == {}, "the settled first pass is no longer the run's turn"


def test_the_claims_goal_mode_is_kept_for_its_claimant_only():
    ws = "ws_until_done"
    assert set(until_done.GOAL_MODES) == {mode.value for mode in GoalMode}, "the store's words are the contract's"
    assert until_done.kept(ws, REF, "persona:inst-1") == "none"
    until_done.keep(ws, REF, "persona:inst-1", "until_done")
    assert until_done.kept(ws, REF, "persona:inst-1") == "until_done"
    assert until_done.kept(ws, REF, "persona:inst-2") == "none", "another claimant's run is one pass"
    until_done.keep(ws, REF, "persona:inst-1", "none")
    assert until_done.kept(ws, REF, "persona:inst-1") == "none", "a plain re-claim clears it"
    until_done.keep(ws, REF, "persona:inst-1", "until_done")
    until_done.forget(ws, REF)
    assert until_done.kept(ws, REF, "persona:inst-1") == "none"


def test_done_is_judged_against_the_tasks_text_and_the_tests_its_body_names():
    body = "Answer every thread.\n\n- **Tests:** `pytest tests/inbox`, `ruff check`\nTest: `make smoke`\nSee `notes.md`."
    assert until_done.objective("Sweep the inbox", body).startswith("Sweep the inbox\n\nAnswer every thread.")
    assert until_done.objective("Sweep the inbox", "") == "Sweep the inbox"
    assert until_done.gate_commands(body) == ("pytest tests/inbox", "ruff check", "make smoke")
    assert until_done.gate_commands("no tests named, only `a span`") == ()
    assert parse_work_report("") is None  # positive control: the report parser is the real one
