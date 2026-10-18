"""``ServeTickScheduler`` — the serve's scheduler over ``store/schedules/`` (dispatcher plan §2.3, §6 B4).

The schedule files, the send queue and the instance's chat root are this test's isolated home; the
executor's instance store and root lookup are fakes, the clock and the machine are pinned.

Killing mutations (each recorded red in the B4 commit body):
* ``tick`` ignores ``can_dispatch`` → ``test_tick_fires_nothing_once_the_drain_begins`` red;
* ``max_parallel`` ignored → ``test_overcap_queues_with_waited_s`` red;
* ``WHEN_IDLE`` fires on its first idle tick → ``test_when_idle_needs_two_ticks`` red.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agent_runtime import mission_chat_door, paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.work_store import schedule_store
from agent_runtime.work_store.executor import Assignment, Brief
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.scheduler import PersonaPrompt, RunAssignment, StartBatch, Trigger
from agent_runtime.work_store.serve_scheduler import ABANDON_AFTER, ORIGIN_KEY, ServeTickScheduler

ROOT = "persona_chat_root_sched"
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
PROMPT = PersonaPrompt("inst-1", "Morning: read the queue and say what is READY.")


class _Instances:
    def get(self, instance_id):
        if instance_id != "inst-1":
            raise KeyError(instance_id)
        return SimpleNamespace(id="inst-1", persona_id="neko", runtime_root=str(paths.store_root()))


@pytest.fixture(autouse=True)
def no_direct_turns(monkeypatch):
    def refuse(args):
        raise AssertionError("a scheduled fire ran a turn directly instead of queueing it")

    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _scheduler(**kw):
    clock = kw.pop("clock", _Clock())
    executor = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   workdir_of=lambda instance: None)
    kw.setdefault("machine", lambda: "machine-a")
    return ServeTickScheduler(executor=executor, clock=clock, **kw), clock


def _scheduled_entries():
    return send_queue.entries_from(ORIGIN_KEY)


def test_nothing_fires_unless_armed():
    scheduler, clock = _scheduler()
    clock.now = T0 + timedelta(days=3)
    assert scheduler.tick() == [] and _scheduled_entries() == []


def test_every_fires_queues_a_turn_and_advances_next_fire():
    scheduler, clock = _scheduler()
    armed = scheduler.arm("morning", Trigger.every(30), PROMPT)
    assert armed.next_fire == T0 + timedelta(minutes=30) and armed.owner_machine == "machine-a"
    assert json.loads((paths.schedules_dir() / "morning.json").read_text(encoding="utf-8"))["key"] == "morning"
    assert scheduler.tick(T0 + timedelta(minutes=29)) == []
    clock.now = T0 + timedelta(minutes=31)
    [receipt] = scheduler.tick()
    assert receipt["kind"] == "schedule.fire" and receipt["refused"] is None and receipt["waited_s"] == 0
    [entry] = _scheduled_entries()
    assert entry.root_session_id == ROOT and entry.args["message"] == PROMPT.prompt
    assert entry.args[send_queue.ORIGIN_ARG][ORIGIN_KEY] == "morning"
    [record] = schedule_store.load_all()
    assert record.last_fire == clock.now and record.next_fire == clock.now + timedelta(minutes=30)
    # The same fire re-presented (a crash before the advance was written) converges on one entry.
    schedule_store.save(record.evolve(next_fire=T0 + timedelta(minutes=30)))
    scheduler.tick()
    assert len(_scheduled_entries()) == 1


def test_a_busy_root_holds_the_fire_behind_the_running_turn():
    """RT-D3 by construction: a fire is a queued send behind whatever holds the root, never a steer."""

    send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "operator"}, "message": "hi"})
    scheduler, _ = _scheduler()
    scheduler.arm("now", Trigger.at_utc(T0), PROMPT)
    [receipt] = scheduler.tick(T0)
    root, _sep, cmid = receipt["run_id"].partition("/")
    assert send_queue.position(root, cmid) == 2
    assert schedule_store.load_all() == []  # AT is one-shot


def test_tick_fires_nothing_once_the_drain_begins():
    draining = {"on": True}
    scheduler, _ = _scheduler(can_dispatch=lambda: not draining["on"])
    scheduler.arm("now", Trigger.at_utc(T0), PROMPT)
    assert scheduler.tick(T0 + timedelta(minutes=1)) == [] and _scheduled_entries() == []
    draining["on"] = False
    assert [r["kind"] for r in scheduler.tick(T0 + timedelta(minutes=1))] == ["schedule.fire"]


def test_overcap_queues_with_waited_s():
    flying = {"n": 1}
    scheduler, clock = _scheduler(max_parallel=1, in_flight=lambda: flying["n"])
    scheduler.arm("a", Trigger.at_utc(T0), PROMPT)
    clock.now = T0 + timedelta(minutes=1)
    [held] = scheduler.tick()
    assert held["kind"] == "schedule.queued" and held["reason"] == "cap_reached"
    clock.now = T0 + timedelta(minutes=2)
    assert scheduler.tick() == []  # still held; the hold is logged once
    flying["n"] = 0
    clock.now = T0 + timedelta(minutes=5)
    [fired] = scheduler.tick()
    assert fired["kind"] == "schedule.fire" and fired["waited_s"] == 240


def test_zero_max_parallel_is_unlimited():
    scheduler, _ = _scheduler(max_parallel=0, in_flight=lambda: 99)
    scheduler.arm("a", Trigger.at_utc(T0), PROMPT)
    assert [r["kind"] for r in scheduler.tick(T0)] == ["schedule.fire"]


def test_when_idle_needs_two_ticks():
    idle = {"root": True}
    scheduler, clock = _scheduler(root_idle=lambda root: idle["root"])
    scheduler.arm("after-reply", Trigger.when_idle(ROOT), PROMPT)
    assert scheduler.tick() == []  # idle once
    idle["root"] = False
    clock.now += timedelta(minutes=1)
    assert scheduler.tick() == []  # busy resets the count
    idle["root"] = True
    clock.now += timedelta(minutes=1)
    assert scheduler.tick() == []
    clock.now += timedelta(minutes=1)
    assert [r["kind"] for r in scheduler.tick()] == ["schedule.fire"]
    assert schedule_store.load_all() == []


def test_when_idle_gives_up_after_fifteen_minutes():
    scheduler, clock = _scheduler(root_idle=lambda root: False)
    scheduler.arm("after-reply", Trigger.when_idle(ROOT), PROMPT)
    clock.now = T0 + ABANDON_AFTER + timedelta(seconds=1)
    [receipt] = scheduler.tick()
    assert receipt["kind"] == "schedule.abandoned" and receipt["waited_s"] == 901
    assert schedule_store.load_all() == [] and _scheduled_entries() == []


def test_only_the_owning_machine_fires():
    scheduler, _ = _scheduler()
    scheduler.arm("a", Trigger.at_utc(T0), PROMPT)
    other, _ = _scheduler(machine=lambda: "machine-b")
    assert other.due(T0) == [] and other.tick(T0) == []
    assert [f.key for f in scheduler.due(T0)] == ["a"]


def test_arm_joins_an_existing_key():
    scheduler, clock = _scheduler()
    first = scheduler.arm("a", Trigger.every(10), PROMPT)
    clock.now = T0 + timedelta(hours=1)
    assert scheduler.arm("a", Trigger.every(99), PersonaPrompt("inst-1", "other")) == first
    assert scheduler.disarm("a") is True and scheduler.disarm("a") is False


def test_start_batch_refuses_while_the_workspace_automation_is_off():
    scheduler, _ = _scheduler()
    with pytest.raises(WorkRefused) as refused:
        scheduler.arm("batch", Trigger.every(60), StartBatch("ws-1", "BATCH-ABCDEF"))
    assert refused.value.reason is Reason.AUTOMATION_OFF


def test_start_batch_fire_without_a_bound_door_is_refused_and_advanced():
    scheduler, _ = _scheduler(automation=lambda workspace_id: "start")
    scheduler.arm("batch", Trigger.at_utc(T0), StartBatch("ws-1", "BATCH-ABCDEF"))
    [receipt] = scheduler.tick(T0)
    assert receipt["refused"] == "door_unbound" and schedule_store.load_all() == []


def test_run_assignment_fire_queues_the_brief_naming_the_schedule():
    brief = Brief(title="nightly", objective="Run the nightly row.")
    action = RunAssignment(Assignment((RowRef("repo", "q.md", "RT-N"),), "inst-1", brief, "ws:repo:RT-N:x"))
    scheduler, _ = _scheduler()
    scheduler.arm("nightly", Trigger.at_utc(T0), action)
    assert schedule_store.load_one("nightly").action == action  # the wire round-trips
    scheduler.tick(T0)
    [entry] = _scheduled_entries()
    origin = entry.args[send_queue.ORIGIN_ARG]
    assert origin[ORIGIN_KEY] == "nightly" and origin["work"] == "ws:repo:RT-N:x"


def test_cron_trigger_fires_on_its_expression_in_its_zone():
    pytest.importorskip("croniter")
    scheduler, _ = _scheduler()
    armed = scheduler.arm("nine", Trigger.cron("0 9 * * *", "Europe/London"), PROMPT)
    assert armed.next_fire == datetime(2026, 10, 19, 8, 0, tzinfo=UTC)  # 09:00 BST


def test_a_malformed_key_or_action_is_schedule_invalid():
    scheduler, _ = _scheduler()
    with pytest.raises(WorkRefused) as refused:
        scheduler.arm("no spaces", Trigger.every(5), PROMPT)
    assert refused.value.reason is Reason.SCHEDULE_INVALID
    with pytest.raises(WorkRefused) as refused:
        schedule_store.action_from_wire({"type": "script", "command": "rm -rf /"})
    assert refused.value.reason is Reason.SCHEDULE_INVALID


def test_a_colon_key_is_a_safe_file_name():
    scheduler, _ = _scheduler()
    scheduler.arm("work:nightly", Trigger.every(5), PROMPT)
    assert [r.key for r in schedule_store.load_all()] == ["work:nightly"]
    assert all(":" not in p.name for p in paths.schedules_dir().iterdir())
