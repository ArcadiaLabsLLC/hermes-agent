"""PersonaTurnExecutor: a claimed row runs as one queued chat turn of the claiming instance (W3).

Plan ``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` §6.3 / §8. The queue and the
settle records are the real ones on this test's isolated home; the instance store, the root lookup and
the open-chat door are fakes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_turn_settles, mission_chat_door, paths
from agent_runtime.chat_turn_settles import TurnOutcome
from agent_runtime.work_store.executor import (
    Assignment, Brief, GoalMode, RunStatus, StopReason, Verdict,
)
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import (
    BRIEF_MAX_LINES, PersonaTurnExecutor, parse_work_report, render_brief,
)
from agent_runtime.work_store.reasons import Reason, WorkRefused

ROOT = "persona_chat_root_work"
REF = RowRef("repo", "Repo_Brain/20 — Active Initiatives/q.md", "RT-A")
ROW = "- **`RT-A` — fix the thing** · `docs/plan.md` · READY 2026-10-18 · **TAKEN 2026-10-18 persona:inst-1**"


class _Instances:
    def __init__(self, *instances):
        self.by_id = {instance.id: instance for instance in instances}

    def get(self, instance_id):
        return self.by_id[instance_id]


def _instance(instance_id="inst-1", *, runtime_root=None):
    root = str(paths.store_root()) if runtime_root is None else runtime_root
    return SimpleNamespace(id=instance_id, persona_id="neko", runtime_root=root)


def _assignment(request_id="ws:repo:RT-A:2026-10-18:abc", **kw):
    brief = Brief(title="fix the thing", objective="Make it work.", inputs=(ROW, "`docs/plan.md`"))
    return Assignment((REF,), kw.pop("persona_instance_id", "inst-1"), brief, request_id, **kw)


def _executor(*instances, root=ROOT, **kw):
    woken: list[bool] = []
    executor = PersonaTurnExecutor(
        instances=_Instances(*(instances or (_instance(),))), root_of=lambda store, **_: root,
        wake=lambda: woken.append(True), **kw)
    return executor, woken


@pytest.fixture
def no_direct_turns(monkeypatch):
    """A Work run never runs a turn itself: the door's turn must not be called by ``start``."""

    def refuse(args):
        raise AssertionError("start ran a chat turn directly instead of queueing it")

    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


def test_start_enqueues_on_the_instance_root_with_a_work_origin_and_wakes(no_direct_turns):
    executor, woken = _executor()
    run = executor.start(_assignment())

    entry = send_queue.find(ROOT, run.client_message_id)
    assert entry is not None and entry.state == send_queue.STATE_QUEUED
    assert run.client_message_id == "work-ws:repo:RT-A:2026-10-18:abc"
    assert run.run_id == f"{ROOT}/{run.client_message_id}" and run.status is RunStatus.QUEUED
    origin = entry.args[send_queue.ORIGIN_ARG]
    assert origin["work"] == "ws:repo:RT-A:2026-10-18:abc"
    assert origin["rows"] == [[REF.slot, REF.note, REF.id]]
    assert entry.args["persona_instance_id"] == "inst-1" and entry.args["session_id"] == ROOT
    assert entry.args["new_session"] is False and entry.args["requested_by"].startswith("work:")
    assert ROW in entry.args["message"]
    assert woken == [True]
    # Exactly one Run per request id: a second start converges on the same entry.
    again = executor.start(_assignment())
    assert again.run_id == run.run_id and len(send_queue._entries(ROOT)) == 1


def test_no_root_opens_a_chat_through_the_door(no_direct_turns):
    opened: list[SimpleNamespace] = []

    def open_chat(args):
        opened.append(args)
        return 0, {"ok": True, "session_id": "persona_chat_opened"}

    executor, _ = _executor(root=None, open_chat=open_chat)
    run = executor.start(_assignment())
    assert run.root_session_id == "persona_chat_opened"
    assert opened[0].persona_instance_id == "inst-1" and opened[0].add_instance is False
    assert send_queue.find("persona_chat_opened", run.client_message_id) is not None

    def unbound(args):
        raise mission_chat_door.MissionChatDoorUnbound("nothing bound")

    executor, _ = _executor(root=None, open_chat=unbound)
    with pytest.raises(WorkRefused) as refused:
        executor.start(_assignment(request_id="other"))
    assert refused.value.reason is Reason.DOOR_UNBOUND


def test_can_start_refuses_missing_instance_other_root_and_drain():
    draining = [False]
    executor, _ = _executor(_instance(), _instance("inst-far", runtime_root="Z:/another/machine/store"),
                            _instance("inst-blank", runtime_root=""), draining=lambda: draining[0])
    assert executor.can_start(_assignment()) is None
    assert executor.can_start(_assignment(persona_instance_id="inst-gone")) is Reason.PERSONA_UNAVAILABLE
    assert executor.can_start(_assignment(persona_instance_id="inst-far")) is Reason.PERSONA_UNAVAILABLE
    assert executor.can_start(_assignment(persona_instance_id="inst-blank")) is Reason.PERSONA_UNAVAILABLE
    assert executor.can_start(_assignment(goal_mode=GoalMode.UNTIL_DONE)) is None  # B3: UNTIL_DONE runs
    draining[0] = True
    assert executor.can_start(_assignment()) is Reason.DRAIN_BEGUN
    with pytest.raises(WorkRefused) as refused:
        executor.start(_assignment())
    assert refused.value.reason is Reason.DRAIN_BEGUN
    assert not send_queue.has_entries(ROOT)


def _settle_with(executor, reply, *, exit_code=0, origin=True):
    told = []
    executor.on_settle(lambda run, outcome: told.append((run, outcome)))
    args = {send_queue.ORIGIN_ARG: {"work": "rid-1", "rows": [[REF.slot, REF.note, REF.id]]}} if origin else {}
    entry, _, _ = send_queue.enqueue(ROOT, "work-rid-1", args)
    executor.settled(entry, exit_code, {"ok": exit_code == 0, "reply": reply})
    return told


def test_settled_parses_the_last_work_report_block():
    reply = ("I quoted the template first:\n```work_report\nverdict: done\nresult: not this one\n```\n"
             "Then did the work.\n\n```work_report\nverdict: blocked\nresult: half way\n"
             "question: ship on Friday?\nrecommend: yes, behind the flag\n```\n")
    executor, _ = _executor()
    [(run, outcome)] = _settle_with(executor, reply)
    assert run.request_id == "rid-1" and run.root_session_id == ROOT and run.status is RunStatus.SETTLED
    assert outcome.verdict is Verdict.BLOCKED
    ending = outcome.per_row[REF]
    assert (ending.question, ending.recommend, ending.result) == ("ship on Friday?", "yes, behind the flag", "half way")
    assert parse_work_report("```work_report\nverdict: done\nresult: shipped it\n```").result == "shipped it"


@pytest.mark.parametrize("reply", [
    "All done, trust me.",
    "```work_report\nverdict: finished\nresult: x\n```",
    "```work_report\nverdict: blocked\nresult: stuck\n```",
    "```work_report\nverdict: done\n```\nthen\n```work_report\nverdict: maybe\n```",
])
def test_unparsable_reply_is_failed(reply):
    executor, _ = _executor()
    [(_run, outcome)] = _settle_with(executor, reply)
    assert outcome.verdict is Verdict.FAILED
    assert "work_report" in outcome.per_row[REF].reason


def test_a_refused_turn_fails_with_its_refusal_and_a_foreign_send_is_not_reported():
    executor, _ = _executor()
    told = []
    executor.on_settle(lambda run, outcome: told.append(outcome))
    entry, _, _ = send_queue.enqueue(ROOT, "work-rid-2", {send_queue.ORIGIN_ARG: {"work": "rid-2", "rows": []}})
    executor.settled(entry, 2, {"ok": False, "error_kind": "chat_turn_outcome_unknown"})
    assert told[0].verdict is Verdict.FAILED and told[0].per_row == {}
    operator, _, _ = send_queue.enqueue(ROOT, "cm-operator", {send_queue.ORIGIN_ARG: {"owner": "stdio"}})
    executor.settled(operator, 0, {"ok": True, "reply": "```work_report\nverdict: done\n```"})
    assert len(told) == 1


def test_stop_removes_a_queued_send_and_waits_on_a_running_turn(no_direct_turns):
    executor, _ = _executor()
    queued = executor.start(_assignment(request_id="queued-run"))
    receipt = executor.stop(queued.run_id, StopReason.OPERATOR)
    assert receipt["stopped"] is True and receipt["kind"] == "work.exec_stop"
    assert send_queue.find(ROOT, queued.client_message_id) is None
    assert executor.status(queued.run_id) is RunStatus.STOPPED

    running = executor.start(_assignment(request_id="running-run"))
    send_queue.mark(ROOT, running.client_message_id, state=send_queue.STATE_RUNNING)
    assert executor.status(running.run_id) is RunStatus.RUNNING
    receipt = executor.stop(running.run_id, StopReason.OPERATOR)
    assert receipt["stopped"] is False and receipt["detail"] == "the turn ends on its own"
    assert send_queue.find(ROOT, running.client_message_id) is not None
    chat_turn_settles.record_settle(client_message_id=running.client_message_id, session_id=ROOT,
                                    request_id="queued:x", exit_code=0, outcome=TurnOutcome())
    assert executor.status(running.run_id) is RunStatus.SETTLED


def test_render_brief_is_under_forty_lines_and_names_the_row_and_pointers():
    long = Brief(title="fix the thing", objective="\n".join(f"step {i}" for i in range(100)),
                 inputs=(ROW, *(f"`docs/p{i}.md`" for i in range(20))), constraints=("one", "two", "three", "four"),
                 acceptance="the suite is green")
    text = render_brief(Assignment(tuple(RowRef("repo", "q.md", f"RT-{i}") for i in range(9)), "inst-1", long, "r"))
    lines = text.split("\n")
    assert len(lines) <= BRIEF_MAX_LINES
    assert ROW in text and "`docs/p0.md`" in text and "RT-0" in text
    assert lines[-1] == "```" and "```work_report" in lines
    short = render_brief(_assignment())
    assert "Make it work." in short and "`docs/plan.md`" in short and len(short.split("\n")) <= BRIEF_MAX_LINES
