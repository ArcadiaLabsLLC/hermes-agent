"""The ``scheduled_turn`` running-work lane (RT-SCHEDULE-TURN-RUNNING-WORK, RULED 2026-10-18).

A real ``ServeTickScheduler`` fire on this test's isolated home (fake instance store and root lookup)
queues a send whose origin names the schedule; the projection reads that entry as a ``scheduled_turn``
row until the runner removes it.

Killing mutation: drop the lane's row from ``running_work.surface._COLLECTORS`` →
``test_a_scheduled_fire_is_a_scheduled_turn_row`` red.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from agent_runtime import paths
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.running_work import KIND_SCHEDULED_TURN, RUNNING_WORK_SOURCES, build_running_work, split_work_id
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from agent_runtime.work_store.scheduler import PersonaPrompt, Trigger
from agent_runtime.work_store.serve_scheduler import ServeTickScheduler

ROOT = "persona_chat_root_rw"
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="neko", runtime_root=str(paths.store_root()))


def _fire() -> dict:
    executor = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None,
                                   workdir_of=lambda instance: None)
    scheduler = ServeTickScheduler(executor=executor, machine=lambda: "machine-a", clock=lambda: T0)
    scheduler.arm("standup", Trigger.at_utc(T0), PersonaPrompt("inst-1", "Stand-up: what moved?"))
    [receipt] = scheduler.tick(T0)
    return receipt


def _rows() -> list[dict]:
    return [row for row in build_running_work()["rows"] if row["kind"] == KIND_SCHEDULED_TURN]


def test_the_kind_is_on_the_wire_and_reports_a_source():
    assert KIND_SCHEDULED_TURN == "scheduled_turn" and KIND_SCHEDULED_TURN in RUNNING_WORK_SOURCES
    assert build_running_work()["sources"][KIND_SCHEDULED_TURN]["status"] == "ok"


def test_a_scheduled_fire_is_a_scheduled_turn_row():
    receipt = _fire()
    [row] = _rows()
    assert row["work_id"] == f"scheduled_turn:{receipt['run_id']}"
    assert split_work_id(row["work_id"]) == ("scheduled_turn", receipt["run_id"])
    assert row["schedule_key"] == "standup" and row["phase"] == "queued" and row["status"] == "running"
    assert row["owner"]["session_id"] == ROOT and row["label"] == "scheduled: standup"
    root, _sep, cmid = receipt["run_id"].partition("/")
    send_queue.mark(root, cmid, state=send_queue.STATE_RUNNING)
    assert _rows()[0]["phase"] == "running"
    send_queue.remove(root, cmid)  # the runner, once the settle is recorded
    assert _rows() == []


def test_an_operator_send_is_not_a_scheduled_turn():
    send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "operator"}, "message": "hi"})
    assert _rows() == []
