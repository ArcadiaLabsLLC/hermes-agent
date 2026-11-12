"""``RT-SCHEDULE-TASK-RUN-NEVER-STARTS``: a scheduled task's fire, against the REAL board writer.

Seen live 2026-11-12 (Eternia lane w1112b-work3, hermes 7bb8dbd9f6): every fire of a ``run_task`` schedule
was refused ``invalid_request: request_id is [A-Za-z0-9_.:-]{1,200}``. The fire ran under
``<key>@<fire stamp>`` and the board writer (``writer.REQUEST_ID``) accepts no ``@``; the scheduler's and
the engine's own tests drove a writer that checks no request id, so they passed while no scheduled run of
a task could start.

Nothing of the failing path is faked here: a bare ``origin.git``, a clone bound as the workspace's slot,
the store's own ``synced`` and ``Writer``, the real ``WorkEngine`` and ``ServeTickScheduler``. Only the
executor is a recorder (the turn is not what failed).

Killing mutations (each recorded red in the commit body):
* ``serve_scheduler.fire_request_id`` joins with ``@`` again → every test here red (the fire is refused);
* ``_per_fire`` builds its own ``@`` id → ``test_a_repeating_assignment_fire_is_accepted_by_the_real_writer`` red.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.work_store import schedule_store
from agent_runtime.work_store.board import boards
from agent_runtime.work_store.engine import WorkEngine, records
from agent_runtime.work_store.executor import (
    Assignment, Brief, ExecutorKind, GoalMode, Outcome, RowEnding, Run, RunStatus, Verdict,
)
from agent_runtime.work_store.grammar import RowRef, Status, parse_note
from agent_runtime.work_store.scheduler import KEY, RunAssignment, RunTask, Trigger
from agent_runtime.work_store.serve_scheduler import ServeTickScheduler, fire_request_id
from agent_runtime.work_store.writer import REQUEST_ID

from work_store_support import bind_here, declare_slots, slot_decl

NOTE = "Harness_Brain/20 — Active Initiatives/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
ROWS = "- **`RT-S` — sweep the inbox** · READY 2026-10-18\n"
ID = ("-c", "user.name=Test Session", "-c", "user.email=session@test.invalid")
AT = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
#: The key Eternia arms a task's schedule under (``task:<workspace>:<slot>:<row id>``).
LAUNCHER_KEY = "task:ws_5e5ba40a77474115315011b76efa1046:hermes:RT-S"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


class _Executor:
    """Records what the engine starts; settles a run when the test says so."""

    kind = ExecutorKind.PERSONA_TURN

    def __init__(self) -> None:
        self.started: list[Assignment] = []
        self.statuses: dict[str, RunStatus] = {}
        self.cb = None

    def can_start(self, a):
        return None

    def start_from(self, a, origin):
        self.started.append(a)
        run_id = f"root/work-{a.request_id}"
        self.statuses[run_id] = RunStatus.QUEUED
        return Run(run_id, a.request_id, a, "root", f"work-{a.request_id}", "now", RunStatus.QUEUED)

    start = start_from

    def status(self, run_id):
        return self.statuses.get(run_id, RunStatus.STOPPED)

    def stop(self, run_id, reason):
        return {"kind": "work.exec_stop", "stopped": False}

    def on_settle(self, cb):
        self.cb = cb

    def settle(self, a, ending: RowEnding) -> None:
        run_id = f"root/work-{a.request_id}"
        self.statuses[run_id] = RunStatus.SETTLED
        run = Run(run_id, a.request_id, None, "root", f"work-{a.request_id}", "now", RunStatus.SETTLED)
        self.cb(run, Outcome(ending.verdict, {a.rows[0]: ending}))


@pytest.fixture
def served(tmp_path: Path, workspace: str) -> SimpleNamespace:
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / NOTE).parent.mkdir(parents=True)
    (seed / NOTE).write_text(HEAD + ROWS, encoding="utf-8", newline="\n")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=clone)
    assert [b.slot for b in boards(workspace)] == ["hermes"]
    executor = _Executor()
    engine = WorkEngine(executor=executor, workspaces=lambda: [workspace], cap_for=lambda ws: 4,
                        now=lambda: AT)
    executor.on_settle(engine.on_settle)
    scheduler = ServeTickScheduler(executor=executor, machine=lambda: "machine-a", clock=lambda: AT,
                                   start_task=engine.adopt_task, start_assignment=engine.adopt)
    return SimpleNamespace(ws=workspace, seed=seed, executor=executor, engine=engine, scheduler=scheduler)


def _row(served: SimpleNamespace):
    git("pull", "-q", "--ff-only", cwd=served.seed)
    text = (served.seed / NOTE).read_text(encoding="utf-8")
    return next(r for r in parse_note(text, slot="hermes", note=NOTE) if r.ref.id == "RT-S")


@pytest.mark.parametrize("key", ["nightly", LAUNCHER_KEY])
def test_a_scheduled_task_fire_claims_its_row_on_the_real_board_and_starts_the_run(served, key):
    served.scheduler.arm(key, Trigger.every(5), RunTask(served.ws, "hermes", "RT-S", "inst-1", GoalMode.NONE))
    [fire] = served.scheduler.tick(AT + timedelta(minutes=5))

    assert fire["kind"] == "schedule.fire" and fire["refused"] is None, fire
    [started] = served.executor.started
    assert fire["request_id"] == started.request_id == f"{key}:20261018T120500Z"
    assert REQUEST_ID.match(started.request_id) and REQUEST_ID.match(f"{started.request_id}:claim")
    assert _row(served).taken.who == "persona:inst-1", "the claim reached origin through the real writer"
    assert schedule_store.load_one(key).fires == 1 and schedule_store.last_result(key) is None


def test_the_runs_ending_is_written_back_and_the_next_fire_starts_again(served):
    served.scheduler.arm("nightly", Trigger.every(5), RunTask(served.ws, "hermes", "RT-S", "inst-1", GoalMode.NONE))
    served.scheduler.tick(AT + timedelta(minutes=5))
    served.executor.settle(served.executor.started[0], RowEnding(Verdict.DONE, result="swept"))
    row = _row(served)
    assert row.taken is None and row.status is Status.READY, "a repeating run's DONE releases the row"
    assert schedule_store.last_result("nightly")["verdict"] == "done"
    served.engine.tick()  # reaps the closed record
    assert records() == []

    [fire] = served.scheduler.tick(AT + timedelta(minutes=10))
    assert fire["refused"] is None and fire["request_id"] == "nightly:20261018T121000Z"
    assert _row(served).taken.who == "persona:inst-1"


def test_a_repeating_assignment_fire_is_accepted_by_the_real_writer(served):
    """The same separator served ``RunAssignment`` (``_per_fire``): a repeating one was refused as well."""

    assignment = Assignment((RowRef("hermes", NOTE, "RT-S"),), "inst-1",
                            Brief(title="nightly", objective="Sweep."), f"{served.ws}:hermes:RT-S:x")
    served.scheduler.arm("nightly", Trigger.every(5), RunAssignment(assignment))
    [fire] = served.scheduler.tick(AT + timedelta(minutes=5))
    assert fire["refused"] is None, fire
    assert served.executor.started[0].request_id == f"{served.ws}:hermes:RT-S:x:20261018T120500Z"
    assert _row(served).taken.who == "persona:inst-1"


def test_every_schedule_key_makes_a_fire_id_the_writer_accepts():
    """The two patterns are held together: the longest key a schedule may have, at any fire time, is a
    request id the writer takes — with the engine's longest write-back suffix on it."""

    longest = "k" * 120
    assert KEY.match(longest) and not KEY.match(longest + "k")
    request_id = fire_request_id(longest, AT)
    assert REQUEST_ID.match(f"{request_id}:blocked:release"), request_id
    for char in "_.:-":
        assert REQUEST_ID.match(fire_request_id(f"a{char}b", AT))
