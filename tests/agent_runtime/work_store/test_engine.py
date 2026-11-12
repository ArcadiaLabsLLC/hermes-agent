"""The Work engine: persona-claimed rows become runs; endings are written back by row ID (W3).

Plan ``docs/agent-runtime-harness/archive/work-on-markdown-2026-10-18.md`` §6.3 / §8. A fake executor
records the runs; a fake writer applies each ``RowOp`` to a real note with the real ``grammar.apply``
(replaying a request id it has seen, as the W2 writer does), so every written row is checked by the
grammar the lint runs. Run records are real files on this test's isolated home.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_runtime.work.store import Synced
from agent_runtime.work_store import engine as engine_mod
from agent_runtime.work_store.board import Board
from agent_runtime.work_store.engine import RecordState, WorkEngine, records
from agent_runtime.work_store.executor import (
    ExecutorKind, Outcome, RowEnding, Run, RunStatus, StopReason, Verdict,
)
from agent_runtime.work_store.grammar import Op, Status, apply as apply_line, archive_note_for, find, parse_note, row_defects
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.writer import Receipt

WS = "ws_work_test"
BRAIN = "Repo_Brain/20 — Active Initiatives"
NOTE = f"{BRAIN}/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
DATE = "2026-10-18"


def _row(row_id: str, taken: str | None = None, status: str = f"READY {DATE}") -> str:
    line = f"- **`{row_id}` — do {row_id.lower()}** · `docs/{row_id}.md` · {status}"
    return line + (f" · **TAKEN {DATE} {taken}**" if taken else "")


class FakeWriter:
    def __init__(self, root: Path) -> None:
        self.worktree = root
        self.ops = []
        self.seen: set[str] = set()
        self.fail_next: Reason | None = None

    def apply(self, op):
        self.ops.append(op)
        if op.request_id in self.seen:
            return Receipt(op.ref, op.op, op.who, op.request_id, "replayed", 0, False, True, f"work.row_{op.op}")
        if self.fail_next is not None:
            reason, self.fail_next = self.fail_next, None
            raise WorkRefused(reason, "planted")
        path = self.worktree / op.ref.note
        lines = path.read_text(encoding="utf-8").split("\n")
        row = find(parse_note("\n".join(lines), slot=op.ref.slot, note=op.ref.note), op.ref.id)
        if row is None:
            raise WorkRefused(Reason.ROW_GONE, op.ref.id)
        edited = apply_line(row.raw, op.op, who=op.who, date=DATE, payload=dict(op.payload))
        if op.op is Op.CLOSE:
            archive = self.worktree / archive_note_for(op.ref.note, DATE)
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text((archive.read_text(encoding="utf-8") if archive.exists() else "") + edited + "\n", encoding="utf-8")
            del lines[row.line_no - 1]
        elif edited is None:
            del lines[row.line_no - 1]
        else:
            lines[row.line_no - 1] = edited
        path.write_text("\n".join(lines), encoding="utf-8")
        self.seen.add(op.request_id)
        return Receipt(op.ref, op.op, op.who, op.request_id, f"c{len(self.seen)}", 0, False, False,
                       f"work.row_{op.op}")


class FakeExecutor:
    kind = ExecutorKind.PERSONA_TURN

    def __init__(self) -> None:
        self.started = []
        self.statuses: dict[str, RunStatus] = {}
        self.refuse: Reason | None = None
        self.raise_once: Exception | None = None
        self.cb = None
        self.stops = []

    def can_start(self, a):
        return self.refuse

    def start(self, a):
        if self.raise_once is not None:
            exc, self.raise_once = self.raise_once, None
            raise exc
        self.started.append(a)
        run_id = f"root/work-{a.request_id}"
        self.statuses.setdefault(run_id, RunStatus.QUEUED)
        return Run(run_id, a.request_id, a, "root", f"work-{a.request_id}", "now", RunStatus.QUEUED)

    def status(self, run_id):
        return self.statuses.get(run_id, RunStatus.STOPPED)

    def stop(self, run_id, reason):
        stopped = self.statuses.get(run_id) is RunStatus.QUEUED
        self.stops.append((run_id, reason))
        if stopped:
            self.statuses[run_id] = RunStatus.STOPPED
        return {"kind": "work.exec_stop", "stopped": stopped}

    def on_settle(self, cb):
        self.cb = cb

    def settle(self, assignment, ending: RowEnding):
        run_id = f"root/work-{assignment.request_id}"
        self.statuses[run_id] = RunStatus.SETTLED
        run = Run(run_id, assignment.request_id, None, "root", f"work-{assignment.request_id}", "now",
                  RunStatus.SETTLED)
        self.cb(run, Outcome(ending.verdict, {assignment.rows[0]: ending}))


@pytest.fixture
def board(tmp_path):
    def make(*rows: str) -> tuple[FakeWriter, Board]:
        (tmp_path / BRAIN).mkdir(parents=True, exist_ok=True)
        (tmp_path / NOTE).write_text(HEAD + "".join(row + "\n" for row in rows), encoding="utf-8")
        board = Board(WS, "repo", tmp_path, BRAIN, "main", None, True, True, False, tmp_path)
        return FakeWriter(tmp_path), board
    return make


def _engine(writer, board, executor=None, **kw):
    executor = executor or FakeExecutor()
    kw.setdefault("cap_for", lambda ws: 4)
    kw.setdefault("now", lambda: datetime(2026, 10, 18, tzinfo=UTC))
    engine = WorkEngine(executor=executor, sync=lambda ws: Synced([board], {"repo": writer}, False),
                        workspaces=lambda: [WS], brief_of=lambda row, writer: "", **kw)
    return engine, executor


def _rows(writer: FakeWriter):
    return {row.ref.id: row for row in parse_note((writer.worktree / NOTE).read_text(encoding="utf-8"),
                                                  slot="repo", note=NOTE)}


def test_tick_starts_a_run_for_each_persona_claimed_row_and_none_for_a_lane_claim(board):
    writer, b = board(_row("RT-A", "persona:inst-1"), _row("RT-B", "r-x"), _row("RT-C"))
    engine, executor = _engine(writer, b)
    assert engine.tick()["started"] == 1
    [assignment] = executor.started
    assert assignment.persona_instance_id == "inst-1" and [r.id for r in assignment.rows] == ["RT-A"]
    assert assignment.brief.inputs[0] == _row("RT-A", "persona:inst-1")
    assert assignment.request_id.startswith(f"{WS}:repo:RT-A:{DATE}:")
    [record] = records()
    assert record.state is RecordState.RUNNING and record.who == "persona:inst-1"
    engine.tick()
    assert len(executor.started) == 1, "a row with a live run is not started twice"
    assert writer.ops == []


def test_tick_never_claims_a_ready_row(board, caplog):
    """Claim-only (RULED): a READY row — even one assigned to a persona — waits for a claim."""

    assigned = f"- **`RT-C` — assigned** · assignee: persona:inst-1 · READY {DATE}"
    writer, b = board(_row("RT-A"), _row("RT-B", status=f"BLOCKED {DATE}: hermes — RT-X"), assigned)
    engine, executor = _engine(writer, b)
    with caplog.at_level(logging.WARNING, logger="agent_runtime.work_store.engine"):
        assert engine.tick() == {}
    assert caplog.records == [], "the tick read the board cleanly"
    assert executor.started == [] and writer.ops == [] and records() == []
    assert _rows(writer)["RT-A"].taken is None and _rows(writer)["RT-C"].taken is None


def test_cap_limits_running_per_workspace(board, caplog):
    writer, b = board(*(_row(f"RT-{c}", f"persona:inst-{c}") for c in "ABC"))
    engine, executor = _engine(writer, b, cap_for=lambda ws: 2)
    with caplog.at_level(logging.INFO, logger="agent_runtime.work_store.receipts"):
        counts = engine.tick()
    assert counts == {"started": 2, "refused": 1}
    assert "cap_reached" in caplog.text
    executor.settle(executor.started[0], RowEnding(Verdict.DONE, result="ok"))
    engine.tick()
    assert len(executor.started) == 3, "a freed lane takes the waiting row"


def test_a_refused_start_leaves_the_row_and_emits_a_receipt(board, caplog):
    writer, b = board(_row("RT-A", "persona:inst-far"))
    before = (writer.worktree / NOTE).read_text(encoding="utf-8")
    engine, executor = _engine(writer, b)
    executor.refuse = Reason.PERSONA_UNAVAILABLE
    with caplog.at_level(logging.INFO, logger="agent_runtime.work_store.receipts"):
        engine.tick()
        engine.tick()
    assert executor.started == [] and records() == [] and writer.ops == []
    assert (writer.worktree / NOTE).read_text(encoding="utf-8") == before
    assert caplog.text.count('"kind": "work.run_refused"') == 1, "logged once per (row, reason), not per tick"
    assert "persona_unavailable" in caplog.text


ENDINGS = {
    "RT-D": RowEnding(Verdict.DONE, result="shipped it"),
    "RT-B": RowEnding(Verdict.BLOCKED, question="ship on Friday?", recommend="yes, behind the flag"),
    "RT-S": RowEnding(Verdict.STOPPED, reason="operator stop"),
    "RT-F": RowEnding(Verdict.FAILED, reason="no readable work_report block"),
}


def test_an_out_of_time_runs_row_says_it_ran_out_of_time(board):
    """RT-WORK-TURN-OUT-OF-TIME-READS-FAILED: the row's write-back names the time budget, not a missing report."""

    from agent_runtime.work_store.executor import CAUSE_OUT_OF_TIME

    writer, b = board(_row("RT-T", "persona:inst-RT-T"))
    engine, executor = _engine(writer, b)
    engine.tick()
    [assignment] = executor.started
    executor.settle(assignment, RowEnding(Verdict.FAILED, cause=CAUSE_OUT_OF_TIME,
                                          reason="the turn used its 240 s time budget before it reported"))
    row = _rows(writer)["RT-T"]
    assert row.status is Status.NEEDS_PLAN and row_defects(row.raw) == []
    assert "ran out of time (the turn used its 240 s time budget before it reported)" in row.status_body
    assert "work_report" not in row.status_body and "re-claim to retry" in row.status_body


def test_done_archives_blocked_sets_owner_decision_stopped_defers_failed_needs_plan(board):
    writer, b = board(*(_row(row_id, f"persona:inst-{row_id}") for row_id in ENDINGS))
    engine, executor = _engine(writer, b)
    engine.tick()
    for assignment in executor.started:
        executor.settle(assignment, ENDINGS[assignment.rows[0].id])
    rows = _rows(writer)
    assert "RT-D" not in rows
    close = next(op for op in writer.ops if op.op is Op.CLOSE)
    assert close.payload == {"result": "shipped it", "outcome": "DONE", "date": DATE, "commit": "here"}
    assert close.who == "persona:inst-RT-D"
    archived = (writer.worktree / archive_note_for(NOTE, DATE)).read_text(encoding="utf-8")
    assert f"DONE {DATE} here" in archived and "result: shipped it" in archived
    for row in rows.values():
        assert row_defects(row.raw) == [] and row.taken is None, row.raw
    # RT-WORK-QUESTION-WRITES-DECISION. KILLING MUTATION: write ``Status.BLOCKED`` with ``owner decision — `` in
    # ``engine._blocked`` -> the question is not among the DECISION rows, red.
    assert rows["RT-B"].status is Status.DECISION
    assert rows["RT-B"].status_body == "ship on Friday?"
    assert rows["RT-B"].recommend == "yes, behind the flag"
    assert (rows["RT-S"].status, rows["RT-S"].status_body) == (Status.DEFERRED, "stopped — operator stop")
    assert rows["RT-F"].status is Status.NEEDS_PLAN
    assert "ended without a readable work_report" in rows["RT-F"].status_body
    assert "re-claim to retry" in rows["RT-F"].status_body
    assert all(record.state is RecordState.CLOSED for record in records())
    engine.tick()
    assert records() == [], "closed records are reaped"


def test_write_backs_use_derived_request_ids_so_a_replay_cannot_double_apply(board):
    writer, b = board(_row("RT-B", "persona:inst-1"))
    engine, executor = _engine(writer, b)
    engine.tick()
    [assignment] = executor.started
    writer.ops.clear()

    original = writer.apply
    calls = []

    def fail_second(op):
        calls.append(op)
        if len(calls) == 2:
            raise WorkRefused(Reason.PUSH_CONTENDED, "planted")
        return original(op)

    writer.apply = fail_second
    executor.settle(assignment, ENDINGS["RT-B"])
    [record] = records()
    assert record.state is RecordState.SETTLED and record.error.startswith("push_contended")
    executor.settle(assignment, ENDINGS["RT-B"])  # a second settle of the same run is ignored
    assert len(calls) == 2
    engine.tick()  # the owed write-back is retried: step 1 replays by its request id, step 2 lands
    rid = assignment.request_id
    assert [op.request_id for op in calls] == [f"{rid}:blocked:status", f"{rid}:blocked:release",
                                                f"{rid}:blocked:status", f"{rid}:blocked:release"]
    row = _rows(writer)["RT-B"]
    assert row.raw.count("DECISION") == 1 and row.raw.count("Recommend:") == 1 and row.taken is None
    assert row_defects(row.raw) == []
    assert records() == [] or all(r.state is RecordState.CLOSED for r in records())


def test_a_run_settled_while_down_is_failed_on_boot(board):
    writer, b = board(_row("RT-A", "persona:inst-1"))
    first, executor = _engine(writer, b)
    first.tick()
    [assignment] = executor.started
    executor.statuses[f"root/work-{assignment.request_id}"] = RunStatus.SETTLED  # no callback: the serve died

    # The serve comes back: a new engine over the same run records.
    second, _ = _engine(writer, b, executor=executor)
    second.tick()
    row = _rows(writer)["RT-A"]
    assert row.status is Status.NEEDS_PLAN and row.taken is None
    assert "the run ended while the serve was down" in row.status_body
    assert len(executor.started) == 1


def test_a_settle_that_never_reaches_the_engine_fails_after_one_tick_of_grace(board):
    writer, b = board(_row("RT-A", "persona:inst-1"))
    engine, executor = _engine(writer, b)
    engine.tick()
    [assignment] = executor.started
    executor.statuses[f"root/work-{assignment.request_id}"] = RunStatus.SETTLED
    engine.tick()
    assert _rows(writer)["RT-A"].taken is not None, "its on_settle may still be on its way"
    engine.tick()
    row = _rows(writer)["RT-A"]
    assert row.status is Status.NEEDS_PLAN and "never reached the engine" in row.status_body


def test_run_records_rebuild_state_after_restart(board):
    writer, b = board(_row("RT-A", "persona:inst-1"))
    first, executor = _engine(writer, b)
    first.tick()
    [assignment] = executor.started

    restarted = FakeExecutor()
    restarted.statuses = dict(executor.statuses)
    second, _ = _engine(writer, b, executor=restarted)
    second.tick()
    assert restarted.started == [], "the run on disk is still live: no second turn"
    restarted.settle(assignment, RowEnding(Verdict.DONE, result="ok"))
    assert "RT-A" not in _rows(writer)


def test_a_crash_between_record_and_start_retries_the_same_run(board):
    writer, b = board(_row("RT-A", "persona:inst-1"))
    engine, executor = _engine(writer, b)
    executor.raise_once = RuntimeError("serve died mid-start")
    with pytest.raises(RuntimeError):
        engine._start_claimed(WS)
    [record] = records()
    assert record.state is RecordState.STARTING
    engine.tick()
    [assignment] = executor.started
    assert assignment.request_id == record.request_id
    assert [r.state for r in records()] == [RecordState.RUNNING]


def test_stop_defers_a_queued_run_and_waits_on_a_running_one(board):
    writer, b = board(_row("RT-A", "persona:inst-1"), _row("RT-B", "persona:inst-2"))
    engine, executor = _engine(writer, b)
    engine.tick()
    queued, running = executor.started
    executor.statuses[f"root/work-{running.request_id}"] = RunStatus.RUNNING
    assert engine.stop(queued.request_id, StopReason.OPERATOR)["stopped"] is True
    assert engine.stop(running.request_id, StopReason.OPERATOR)["stopped"] is False
    rows = _rows(writer)
    assert (rows["RT-A"].status, rows["RT-A"].status_body) == (Status.DEFERRED, "stopped — operator stop")
    assert rows["RT-A"].taken is None and rows["RT-B"].taken is not None
    assert engine_mod.WRITE_BACKS.keys() == set(Verdict)


def test_a_run_failed_on_boot_frees_its_lane_in_the_same_tick(board):
    """Phase order: settle (1) before start (2), so a lane a dead run held is free for a waiting row."""

    writer, b = board(_row("RT-A", "persona:inst-1"))
    first, executor = _engine(writer, b, cap_for=lambda ws: 1)
    first.tick()
    [held] = executor.started
    executor.statuses[f"root/work-{held.request_id}"] = RunStatus.SETTLED
    lines = (writer.worktree / NOTE).read_text(encoding="utf-8")
    (writer.worktree / NOTE).write_text(lines + _row("RT-B", "persona:inst-2") + "\n", encoding="utf-8")

    second, _ = _engine(writer, b, executor=executor, cap_for=lambda ws: 1)
    counts = second.tick()
    assert counts.get("started") == 1 and "refused" not in counts, counts
    assert [a.rows[0].id for a in executor.started] == ["RT-A", "RT-B"]


# ── RT-SCHEDULE-RUN-ASSIGNMENT-CLAIM: a scheduled RunAssignment is an engine run ──


class _OriginExecutor(FakeExecutor):
    """The serve's executor also takes ``start_from`` (a scheduled fire names itself in the origin)."""

    def __init__(self) -> None:
        super().__init__()
        self.origins = []

    def start_from(self, a, origin):
        self.origins.append(dict(origin))
        return self.start(a)


def _scheduled(board, *rows):
    from datetime import UTC, datetime

    from agent_runtime.work_store.executor import Assignment, Brief
    from agent_runtime.work_store.grammar import RowRef
    from agent_runtime.work_store.scheduler import RunAssignment, Trigger
    from agent_runtime.work_store.serve_scheduler import ServeTickScheduler

    writer, b = board(*rows)
    engine, executor = _engine(writer, b, executor=_OriginExecutor())
    at = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    scheduler = ServeTickScheduler(executor=executor, machine=lambda: "machine-a", clock=lambda: at,
                                   start_assignment=engine.adopt)
    assignment = Assignment((RowRef("repo", "q.md", "RT-S"),), "inst-1",
                            Brief(title="nightly", objective="Run the nightly row."), "ws:repo:RT-S:x")
    scheduler.arm("nightly", Trigger.at_utc(at), RunAssignment(assignment))
    [fire] = scheduler.tick(at)
    return writer, engine, executor, assignment, fire


def test_a_scheduled_assignment_claims_its_row_and_its_settle_is_written_back(board):
    """Killing mutation: ``_fire_assignment`` starts the run on the executor without ``adopt`` → red
    (the row is never TAKEN and the DONE settle deletes nothing)."""

    writer, engine, executor, assignment, fire = _scheduled(board, _row("RT-S"))

    assert fire["refused"] is None and executor.origins[0]["schedule"] == "nightly"
    assert _rows(writer)["RT-S"].taken.who == "persona:inst-1"
    assert engine.tick().get("started") is None  # the engine does not start a second run for the claim
    executor.settle(assignment, RowEnding(Verdict.DONE, result="ran"))
    assert "RT-S" not in _rows(writer)


def test_a_scheduled_assignment_on_a_row_another_claimant_holds_is_refused(board):
    _writer, _engine, executor, _assignment, fire = _scheduled(board, _row("RT-S", taken="lane-x"))

    assert fire["refused"] == Reason.ALREADY_TAKEN.value and executor.started == []
    assert records() == []


# ── RT-SCHEDULE-RUN-TASK-REPEATS: a scheduled RunTask builds its assignment at each fire ──


def _task_schedule(board, *rows, minutes=5, goal_mode="none"):
    from datetime import UTC, datetime, timedelta

    from agent_runtime.work_store.executor import GoalMode
    from agent_runtime.work_store.scheduler import RunTask, Trigger
    from agent_runtime.work_store.serve_scheduler import ServeTickScheduler

    writer, b = board(*rows)
    engine, executor = _engine(writer, b, executor=_OriginExecutor())
    at = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    scheduler = ServeTickScheduler(executor=executor, machine=lambda: "machine-a", clock=lambda: at,
                                   start_task=engine.adopt_task)
    scheduler.arm("nightly", Trigger.every(minutes), RunTask(WS, "repo", "RT-S", "inst-1", GoalMode(goal_mode)))
    return writer, engine, executor, scheduler, [at + timedelta(minutes=minutes * n) for n in (1, 2, 3)]


def test_a_repeating_scheduled_task_stays_open_and_each_fire_reads_the_row_as_it_is_then(board):
    """Killing mutations: ``_done`` ignores ``record.repeats`` → the first DONE archives the row and the second
    fire abandons, red; ``adopt_task`` reusing the first fire's assignment → the second brief is stale, red."""

    writer, engine, executor, scheduler, (t1, t2, _t3) = _task_schedule(board, _row("RT-S"), goal_mode="until_done")
    [fire] = scheduler.tick(t1)
    assert fire["refused"] is None and fire["request_id"] == "nightly@20261018T120500Z"
    [first] = executor.started
    assert first.request_id == "nightly@20261018T120500Z" and first.persona_instance_id == "inst-1"
    assert first.goal_mode.value == "until_done" and first.brief.title == "do rt-s"
    assert _rows(writer)["RT-S"].taken.who == "persona:inst-1"
    executor.settle(first, RowEnding(Verdict.DONE, result="ran"))
    row = _rows(writer)["RT-S"]
    assert row.taken is None and row.status is Status.READY, "DONE leaves the task open and unclaimed"
    assert row_defects(row.raw) == []
    note = writer.worktree / NOTE
    note.write_text(note.read_text(encoding="utf-8").replace("do rt-s", "do the edited thing"), encoding="utf-8")
    engine.tick()  # reaps the closed record of the first run
    [fire] = scheduler.tick(t2)
    assert fire["refused"] is None
    second = executor.started[1]
    assert second.request_id == "nightly@20261018T121000Z" and second.brief.title == "do the edited thing"
    assert "do the edited thing" in second.brief.inputs[0]


def test_a_scheduled_task_whose_row_is_gone_removes_its_schedule(board):
    from agent_runtime.work_store import schedule_store

    writer, _eng, executor, scheduler, (t1, _t2, _t3) = _task_schedule(board, _row("RT-OTHER"))
    [receipt] = scheduler.tick(t1)
    assert receipt["kind"] == "schedule.abandoned" and receipt["reason"] == "row_gone"
    assert executor.started == [] and schedule_store.load_all() == [] and writer.ops == []


def test_a_scheduled_task_whose_board_cannot_be_read_keeps_its_schedule(board):
    """A sync refusal is that fire's refusal, never "the row is gone".
    Killing mutation: ``_locate`` ignores ``view.refused`` → the fire reads ``row_gone`` and abandons, red."""

    from agent_runtime.work_store import schedule_store

    _writer, engine, executor, scheduler, (t1, _t2, _t3) = _task_schedule(board, _row("RT-S"))
    engine._sync = lambda ws: Synced([], {}, False, {"repo": WorkRefused(Reason.UNAVAILABLE, "fetch failed")})
    [fire] = scheduler.tick(t1)
    assert fire["kind"] == "schedule.fire" and fire["refused"] == Reason.UNAVAILABLE.value
    assert [r.key for r in schedule_store.load_all()] == ["nightly"] and executor.started == []


def test_a_scheduled_task_fire_while_its_last_run_is_live_starts_no_second_run(board):
    _writer, _eng, executor, scheduler, (t1, t2, _t3) = _task_schedule(board, _row("RT-S"))
    scheduler.tick(t1)
    [fire] = scheduler.tick(t2)
    assert fire["kind"] == "schedule.skipped" and fire["run_id"] == "nightly@20261018T120500Z"
    assert len(executor.started) == 1


# ── RT-SCHEDULE-PAUSE-END-AND-LAST-RESULT: the run's ending is its schedule's last_result ──


def test_a_scheduled_run_s_ending_is_its_schedule_s_last_result(board):
    """Killing mutation: ``_record_ending`` never calls ``_note_schedule`` → ``last_result`` stays None, red."""

    from agent_runtime.work_store import schedule_store
    from agent_runtime.work_store.executor import CAUSE_OUT_OF_TIME

    _writer, engine, executor, scheduler, (t1, t2, t3) = _task_schedule(board, _row("RT-S"))
    scheduler.tick(t1)
    assert schedule_store.last_result("nightly") is None
    [skipped] = scheduler.tick(t2)
    assert skipped["kind"] == "schedule.skipped" and skipped["run_id"] == "nightly@20261018T120500Z"
    assert schedule_store.last_result("nightly")["verdict"] == "skipped"
    executor.settle(executor.started[0], RowEnding(Verdict.DONE, result="swept the inbox"))
    result = schedule_store.last_result("nightly")
    assert result == {"verdict": "done", "at": "2026-10-18T00:00:00+00:00", "detail": "swept the inbox",
                      "run_id": "root/work-nightly@20261018T120500Z"}
    assert schedule_store.load_one("nightly").fires == 1, "the skipped fire counted nothing"
    engine.tick()
    scheduler.tick(t3)
    executor.settle(executor.started[1], RowEnding(Verdict.FAILED, reason="the turn used its 1800 s time budget",
                                                   cause=CAUSE_OUT_OF_TIME))
    late = schedule_store.last_result("nightly")
    assert late["verdict"] == "failed" and late["detail"].startswith("ran out of time (")


def test_a_repeating_schedule_waits_for_the_owners_answer_before_it_runs_the_task_again(board):
    """RT-SCHEDULE-REPEAT-RUNS-A-TASK-THAT-WAITS-ON-THE-OWNER: a run that ended BLOCKED on a question is not
    re-run every fire; the fire is skipped (no count) until the row is answered. A FAILED run's row
    (NEEDS PLAN) is retried — that is what a repeat is for."""

    from agent_runtime.work_store import schedule_store

    writer, engine, executor, scheduler, (t1, t2, t3) = _task_schedule(board, _row("RT-S"))
    scheduler.tick(t1)
    executor.settle(executor.started[0], RowEnding(Verdict.BLOCKED, question="ship on Friday?", recommend="yes"))
    assert _rows(writer)["RT-S"].status is Status.DECISION
    engine.tick()
    [skipped] = scheduler.tick(t2)
    assert skipped["kind"] == "schedule.skipped" and skipped["reason"] == "waits_on_owner"
    assert len(executor.started) == 1 and _rows(writer)["RT-S"].taken is None
    result = schedule_store.last_result("nightly")
    assert result["verdict"] == "skipped" and result["detail"] == "the task is waiting on your answer"
    assert result["run_id"] is None and schedule_store.load_one("nightly").fires == 1
    note = writer.worktree / NOTE
    text = note.read_text(encoding="utf-8")
    line = next(l for l in text.split("\n") if "RT-S" in l)
    note.write_text(text.replace(line, _row("RT-S", status=f"NEEDS PLAN {DATE}: the last run failed")), encoding="utf-8")
    [fire] = scheduler.tick(t3)
    assert fire["kind"] == "schedule.fire" and fire["refused"] is None and len(executor.started) == 2


# ── RT-WORK-CLAIM-RUNS-UNTIL-DONE: the goal mode kept with a claim is the run's ──


def test_a_claim_that_asked_for_it_runs_until_done_judged_against_the_tasks_text_and_tests(board):
    from agent_runtime.work_store import until_done
    from agent_runtime.work_store.executor import GoalMode

    writer, b = board(_row("RT-A", "persona:inst-1"), _row("RT-B", "persona:inst-2"))
    rows = _rows(writer)
    until_done.keep(WS, rows["RT-A"].ref, "persona:inst-1", "until_done")
    until_done.keep(WS, rows["RT-B"].ref, "persona:someone-else", "until_done")
    executor = FakeExecutor()
    engine = WorkEngine(executor=executor, sync=lambda ws: Synced([b], {"repo": writer}, False),
                        workspaces=lambda: [WS], cap_for=lambda ws: 4,
                        now=lambda: datetime(2026, 10, 18, tzinfo=UTC),
                        brief_of=lambda row, writer: "Answer every thread.\nTests: `pytest tests/inbox`")
    assert engine.tick()["started"] == 2
    by_row = {a.rows[0].id: a for a in executor.started}
    kept = by_row["RT-A"]
    assert kept.goal_mode is GoalMode.UNTIL_DONE
    assert kept.brief.objective == "do rt-a\n\nAnswer every thread.\nTests: `pytest tests/inbox`"
    assert kept.brief.tests == ("pytest tests/inbox",)
    plain = by_row["RT-B"]
    assert plain.goal_mode is GoalMode.NONE and plain.brief.tests == (), "kept for another claimant: one pass"
    assert {r.ref.id: r.goal_mode for r in records()} == {"RT-A": "until_done", "RT-B": "none"}
    executor.settle(kept, RowEnding(Verdict.DONE, result="swept"))
    assert until_done.kept(WS, rows["RT-A"].ref, "persona:inst-1") == "none", "forgotten once the run closed"


def test_a_row_with_skills_hands_them_to_the_assignment(board):
    """p10-work S1: ``Assignment.skills`` is DERIVED from the row's ``skills:`` segment, never a pointer."""

    lent = f"- **`RT-L` — lend** · `docs/RT-L.md` · skills: `git-workflow`, `eternia/qa` · READY {DATE} · **TAKEN {DATE} persona:inst-1**"
    writer, b = board(lent, _row("RT-M", "persona:inst-2"))
    engine, executor = _engine(writer, b)
    engine.tick()
    by_row = {a.rows[0].id: a for a in executor.started}
    assert by_row["RT-L"].skills == ("git-workflow", "eternia/qa")
    assert "`git-workflow`" not in by_row["RT-L"].brief.inputs[1:]
    assert by_row["RT-M"].skills == ()
