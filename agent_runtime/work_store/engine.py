"""The Work engine — hands each persona-claimed row to its executor, writes the ending back (W3).

Work plan ``work-on-markdown-2026-10-18.md`` §6.3 and §8. The engine runs in the serve only (one writer
per machine) and NEVER claims: a row ``**TAKEN <date> persona:<instance_id>**`` (claimed through
``runtime.work.claim`` or ``start`` with an assignee) becomes ONE ``Assignment`` of that row; a row
taken by a session lane (``<who>`` not ``persona:…``) is never touched.

Every run is a ``RunRecord`` file under ``paths.work_runs_dir(ws)``; the engine's whole state is
rebuilt from those files, so a restart loses nothing. A record moves
``starting → running → settled → closed``: ``starting`` is written BEFORE the executor's ``start``
(whose ``request_id`` makes it idempotent), so a crash between them retries the same run instead of
starting a second one; ``settled`` holds the outcome until the write-back lands; ``closed`` is reaped.

``tick`` runs three phases, in order: (1) settle what ended without reporting — a run that ended while
the serve was down (seen at construction, before the runner's first pass) or whose settle never
reached ``on_settle`` within a tick is ``FAILED`` — and retry owed write-backs; (2) start a run for
each persona-claimed row with no live record, under the workspace's lane cap; (3) reap closed records.

The write-back is the ``WRITE_BACKS`` table, one ``RowOp`` per step through the W2 writer, keyed by
row ID, each with a request id derived from the run's (``<run request_id>:<verdict>:<step>``) so a
replay cannot double-apply: DONE deletes the row (the result in the commit body); BLOCKED sets
``BLOCKED <date>: owner decision — <question> · Recommend: <answer>`` then releases; STOPPED releases
then ``DEFERRED <date>: stopped — <reason>``; FAILED releases then ``NEEDS PLAN <date>: …``.
Receipts: ``work.run_start | run_settle | run_refused | engine_tick``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .. import paths
from ..serde import write_json_atomic
from . import receipts
from .board import board_rows
from .executor import Assignment, Brief, Executor, Outcome, RowEnding, Run, RunStatus, StopReason, Verdict
from .grammar import Op, Row, RowRef, Status, render_status, segment_text
from .reasons import Reason, WorkRefused

__layer__ = "lanes"
__all__ = [
    "DEFAULT_CAP",
    "TICK_SECONDS",
    "WRITE_BACKS",
    "RecordState",
    "RunRecord",
    "WorkEngine",
    "home_scope",
    "records",
    "start_work_engine",
]

logger = logging.getLogger(__name__)

TICK_SECONDS = 15.0
DEFAULT_CAP = 4
#: A write-back refused for one of these can never land: the row is not this run's any more.
_ABANDON = frozenset({Reason.ROW_GONE, Reason.NOT_CLAIMANT, Reason.ALREADY_TAKEN})
_ENDED = frozenset({RunStatus.SETTLED, RunStatus.STOPPED})
_TOKEN = re.compile(r"[^A-Za-z0-9_.-]")
_CONSTRAINT = "Work only this row; the engine writes its ending to the queue — do not edit the row yourself."


class RecordState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    SETTLED = "settled"
    CLOSED = "closed"


@dataclass
class RunRecord:
    request_id: str
    ref: RowRef
    workspace_id: str
    persona_instance_id: str
    root_session_id: str
    client_message_id: str
    started_at: str
    state: RecordState
    who: str = ""
    run_id: str = ""
    ending: dict[str, str] | None = None
    error: str = ""

    def wire(self) -> dict[str, Any]:
        return {**asdict(self), "ref": asdict(self.ref), "state": self.state.value}

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> RunRecord:
        return cls(**{**raw, "ref": RowRef(**raw["ref"]), "state": RecordState(raw["state"])})


# ── the write-back table ───────────────────────────────────────────────────

Step = tuple[str, Op, dict[str, Any]]


def _done(record: RunRecord, ending: RowEnding, date: str) -> list[Step]:
    return [("done", Op.DELETE, {"result": " ".join(str(ending.result or "done").split())[:4000]})]


def _blocked(record: RunRecord, ending: RowEnding, date: str) -> list[Step]:
    status = render_status(Status.BLOCKED, date, f"owner decision — {segment_text(ending.question)}")
    status += f" · Recommend: {segment_text(ending.recommend) or 'none offered'}"
    return [("blocked:status", Op.SET_STATUS, {"status": status}), ("blocked:release", Op.RELEASE, {})]


def _stopped(record: RunRecord, ending: RowEnding, date: str) -> list[Step]:
    status = render_status(Status.DEFERRED, date, f"stopped — {segment_text(ending.reason) or 'no reason given'}")
    return [("stopped:release", Op.RELEASE, {}), ("stopped:status", Op.SET_STATUS, {"status": status})]


def _failed(record: RunRecord, ending: RowEnding, date: str) -> list[Step]:
    body = (f"work run {record.request_id} ended without a readable work_report "
            f"({segment_text(ending.reason, 200) or 'no detail'}); re-claim to retry")
    return [("failed:release", Op.RELEASE, {}),
            ("failed:status", Op.SET_STATUS, {"status": render_status(Status.NEEDS_PLAN, date, body)})]


WRITE_BACKS: dict[Verdict, Callable[[RunRecord, RowEnding, str], list[Step]]] = {
    Verdict.DONE: _done,
    Verdict.BLOCKED: _blocked,
    Verdict.STOPPED: _stopped,
    Verdict.FAILED: _failed,
}


# ── the defaults the serve runs with ───────────────────────────────────────


def _default_sync(workspace_id: str) -> Any:
    from ..work.store import synced

    return synced(workspace_id)


def _default_workspaces() -> list[str]:
    from ..work.service import workspace_ids

    return workspace_ids()


def default_cap(workspace_id: str) -> int:
    """The workspace's ``max_concurrent_lanes``, else :data:`DEFAULT_CAP`."""

    from ..store import WorkspaceStore

    try:
        return int(WorkspaceStore().get(workspace_id).max_concurrent_lanes or DEFAULT_CAP)
    except Exception:
        return DEFAULT_CAP


def _brief_text(row: Row, writer: Any) -> str:
    from ..work.store import brief_text

    return brief_text(row, getattr(writer, "worktree", None))


def _token(value: str) -> str:
    return _TOKEN.sub("-", value)[:60]


# ── run records on disk ────────────────────────────────────────────────────


def _record_path(workspace_id: str, request_id: str) -> Path:
    return paths.work_runs_dir(workspace_id) / f"{paths.safe_path_token(request_id)}.json"


def _save(record: RunRecord) -> None:
    write_json_atomic(_record_path(record.workspace_id, record.request_id), record.wire())


def _drop(record: RunRecord) -> None:
    try:
        _record_path(record.workspace_id, record.request_id).unlink()
    except FileNotFoundError:
        pass


def records() -> list[RunRecord]:
    """Every run record on this machine, oldest first (unreadable files are skipped, never fatal)."""

    found = []
    for path in sorted(paths.work_dir().glob("*/runs/*.json")):
        try:
            found.append(RunRecord.from_wire(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError, KeyError):
            logger.warning("work run record %s is unreadable; skipped", path)
    return sorted(found, key=lambda record: (record.started_at, record.request_id))


class WorkEngine:
    """Claimed rows in, chat turns out, endings written back by row ID."""

    def __init__(
        self,
        *,
        executor: Executor,
        sync: Callable[[str], Any] | None = None,
        workspaces: Callable[[], list[str]] | None = None,
        cap_for: Callable[[str], int] | None = None,
        now: Callable[[], datetime] | None = None,
        brief_of: Callable[[Row, Any], str] | None = None,
        held: Callable[[str, Any], set[RowRef]] | None = None,
        after_tick: Callable[[], Any] | None = None,
    ) -> None:
        self.executor = executor
        # Rows another dispatcher runs (a batch lane's, dispatcher plan §3): claimed persona:<id> too,
        # but handed to their lane's ONE turn, never one engine run per row.
        self._held = held or (lambda _workspace_id, _view: set())
        self._after_tick = after_tick
        self._sync = sync or _default_sync
        self._workspaces = workspaces or _default_workspaces
        self._cap_for = cap_for or default_cap
        self._now = now or (lambda: datetime.now(UTC))
        self._brief_of = brief_of or _brief_text
        self._lock = threading.RLock()
        self._unreported: set[str] = set()
        self._refused: dict[RowRef, str] = {}
        # Runs that had already ended when this engine was built (before the runner's first pass):
        # their settle can never reach on_settle, so phase 1 fails them on the first tick.
        self._ended_before_boot = {
            record.request_id for record in records()
            if record.state is RecordState.RUNNING and self._status(record) in _ENDED
        }
        executor.on_settle(self.on_settle)

    # ── the tick ─────────────────────────────────────────────────────────

    def tick(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        counts["settled"] = self._settle_pending()
        for workspace_id in self._workspaces():
            try:
                counts.update(self._start_claimed(workspace_id))
            except Exception:
                logger.warning("work engine could not read workspace %s", workspace_id, exc_info=True)
        counts["reaped"] = self._reap()
        if self._after_tick is not None:
            try:
                self._after_tick()
            except Exception:
                logger.warning("work engine after-tick hook failed", exc_info=True)
        tally = {key: value for key, value in counts.items() if value}
        if tally:
            receipts.emit("work.engine_tick", counts=tally)
        return tally

    def _status(self, record: RunRecord) -> RunStatus | None:
        return self.executor.status(record.run_id) if record.run_id else None

    def _settle_pending(self) -> int:
        """Phase 1: fail runs that ended without reporting; retry owed write-backs."""

        done = 0
        for record in records():
            with self._lock:
                fresh = self._fresh(record)
                if fresh is None:
                    continue
                if fresh.state is RecordState.SETTLED:
                    done += self._write_back(fresh)
                elif fresh.state is RecordState.RUNNING:
                    done += self._unreported_end(fresh)
        return done

    def _fresh(self, record: RunRecord) -> RunRecord | None:
        path = _record_path(record.workspace_id, record.request_id)
        try:
            return RunRecord.from_wire(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _unreported_end(self, record: RunRecord) -> int:
        if self._status(record) not in _ENDED:
            self._unreported.discard(record.request_id)
            return 0
        if record.request_id in self._ended_before_boot:
            reason = "the run ended while the serve was down"
        elif record.request_id in self._unreported:
            reason = "the run ended and its settle never reached the engine"
        else:
            self._unreported.add(record.request_id)  # its on_settle may still be on its way
            return 0
        self._record_ending(record, RowEnding(Verdict.FAILED, reason=reason))
        return self._write_back(record)

    def _start_claimed(self, workspace_id: str) -> Counter[str]:
        """Phase 2: one run for each persona-claimed row with no live record, under the lane cap."""

        counts: Counter[str] = Counter()
        with self._lock:
            view = self._sync(workspace_id)
            held = self._held(workspace_id, view)
            live = {record.ref: record for record in records()
                    if record.workspace_id == workspace_id and record.state is not RecordState.CLOSED}
            for board in view.boards:
                writer = view.writers.get(board.slot)
                if writer is None or board.read_root is None:
                    continue
                for row in board_rows(board):
                    if row.taken is None or row.taken.persona_instance_id is None or row.ref in held:
                        continue  # untaken (the engine never claims), a session lane's claim, or a batch lane's
                    handed = self._hand_off(workspace_id, row, writer, live.get(row.ref))
                    counts.update([handed] if handed else [])
        return counts

    def _hand_off(self, workspace_id: str, row: Row, writer: Any, record: RunRecord | None) -> str | None:
        """Start (or retry the start of) the row's run; ``started`` / ``refused``, None when it has one."""

        if record is not None and record.state is not RecordState.STARTING:
            return None
        if record is None:
            request_id = ":".join([_token(workspace_id), _token(row.ref.slot), row.ref.id,
                                   row.taken.date, os.urandom(3).hex()])
            assignment = self._assignment(row, writer, request_id)
            refusal = self.executor.can_start(assignment)
            if refusal is None and self._running(workspace_id) >= self._cap_for(workspace_id):
                refusal = Reason.CAP_REACHED
            if refusal is not None:
                return self._refuse(row.ref, refusal, assignment.persona_instance_id)
            record = RunRecord(request_id, row.ref, workspace_id, assignment.persona_instance_id, "", "",
                               self._stamp(), RecordState.STARTING, who=row.taken.who)
            _save(record)
        return self._start(record, self._assignment(row, writer, record.request_id))

    def _assignment(self, row: Row, writer: Any, request_id: str) -> Assignment:
        body = self._brief_of(row, writer)
        brief = Brief(title=row.title, objective=body or row.title,
                      inputs=(row.raw, *(f"`{pointer}`" for pointer in row.pointers)), constraints=(_CONSTRAINT,))
        return Assignment((row.ref,), row.taken.persona_instance_id, brief, request_id)

    def _start(self, record: RunRecord, assignment: Assignment) -> str:
        try:
            run = self.executor.start(assignment)
        except WorkRefused as refused:
            _drop(record)
            return self._refuse(record.ref, refused.reason, refused.detail)
        record.run_id, record.root_session_id, record.client_message_id = (
            run.run_id, run.root_session_id, run.client_message_id)
        record.state = RecordState.RUNNING
        _save(record)
        self._refused.pop(record.ref, None)
        receipts.emit("work.run_start", ref=asdict(record.ref), request_id=record.request_id,
                      workspace_id=record.workspace_id, persona_instance_id=record.persona_instance_id,
                      run_id=run.run_id)
        return "started"

    def _refuse(self, ref: RowRef, reason: Reason, detail: str = "") -> str:
        """A refused start leaves the row as is; the receipt is logged once per (row, reason)."""

        if self._refused.get(ref) != reason.value:
            self._refused[ref] = reason.value
            receipts.emit("work.run_refused", ref=asdict(ref), reason=reason.value, detail=detail)
        return "refused"

    def _running(self, workspace_id: str) -> int:
        return sum(1 for record in records() if record.workspace_id == workspace_id
                   and record.state in (RecordState.STARTING, RecordState.RUNNING))

    def _reap(self) -> int:
        """Phase 3: a closed record has nothing left to do (its receipts are the history)."""

        closed = [record for record in records() if record.state is RecordState.CLOSED]
        for record in closed:
            _drop(record)
        return len(closed)

    # ── endings ──────────────────────────────────────────────────────────

    def on_settle(self, run: Run, outcome: Outcome) -> None:
        """The executor's callback: record the ending, then write it back."""

        with self._lock:
            record = next((r for r in records() if r.request_id == run.request_id), None)
            if record is None or record.state in (RecordState.SETTLED, RecordState.CLOSED):
                return
            ending = next((e for ref, e in outcome.per_row.items() if ref.id == record.ref.id), None)
            self._record_ending(record, ending or RowEnding(outcome.verdict, reason="the run named no ending"))
            self._write_back(record)

    def stop(self, request_id: str, reason: StopReason = StopReason.OPERATOR) -> dict[str, Any]:
        """Stop a run: a send not yet begun is removed and the row deferred; a running turn is waited on."""

        with self._lock:
            record = next((r for r in records() if r.request_id == request_id), None)
            if record is None or record.state is not RecordState.RUNNING:
                return {"stopped": False, "detail": "no running work run"}
            receipt = self.executor.stop(record.run_id, reason)
            if receipt.get("stopped"):
                self._record_ending(record, RowEnding(Verdict.STOPPED, reason=f"{StopReason(reason).value} stop"))
                self._write_back(record)
            return receipt

    def _record_ending(self, record: RunRecord, ending: RowEnding) -> None:
        record.ending = {key: str(value) for key, value in asdict(ending).items()}
        record.state = RecordState.SETTLED
        _save(record)

    def _write_back(self, record: RunRecord) -> int:
        ending = RowEnding(**{**record.ending, "verdict": Verdict(record.ending["verdict"])})
        steps = WRITE_BACKS[ending.verdict](record, ending, self._now().date().isoformat())
        try:
            commits = self._apply(record, steps)
        except WorkRefused as refused:
            record.error = f"{refused.reason.value}: {refused.detail}"[:500]
            if refused.reason not in _ABANDON:
                _save(record)  # owed: the next tick retries (each step replays by request id)
                return 0
            commits = []
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"[:500]
            _save(record)
            logger.warning("work write-back for %s failed; retried next tick", record.request_id, exc_info=True)
            return 0
        record.state = RecordState.CLOSED
        _save(record)
        receipts.emit("work.run_settle", ref=asdict(record.ref), request_id=record.request_id,
                      workspace_id=record.workspace_id, verdict=ending.verdict.value, commits=commits,
                      error=record.error or None)
        return 1

    def _apply(self, record: RunRecord, steps: list[Step]) -> list[str]:
        from .writer import RowOp

        view = self._sync(record.workspace_id)
        writer = view.writers.get(record.ref.slot)
        if writer is None:
            raise WorkRefused(Reason.SLOT_UNBOUND, record.ref.slot)
        commits = []
        for suffix, op, payload in steps:
            receipt = writer.apply(RowOp(record.ref, op, record.who, f"{record.request_id}:{suffix}", payload))
            commits += [receipt.commit] if receipt.commit else []
        return commits

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")


def home_scope(home: Path | str | None) -> Any:
    """``process_home_scope(home)``, or nothing to bind when ``home`` is None."""

    import contextlib

    if home is None:
        return contextlib.nullcontext()
    from ..profile_context import process_home_scope

    return process_home_scope(home)


def start_work_engine(
    *,
    stop_event: threading.Event,
    interval_s: float = TICK_SECONDS,
    engine: WorkEngine | None = None,
    home: Path | str | None = None,
) -> threading.Thread:
    """Tick ``engine`` on a daemon thread until ``stop_event``; a failed tick is logged, never fatal.

    ``home`` is the serve's request home (the queued-send runner's), bound around every tick so the
    run records, the queue and the settles are read where the runner writes them.
    """

    if engine is None:
        from .persona_turn import PersonaTurnExecutor

        with home_scope(home):
            engine = WorkEngine(executor=PersonaTurnExecutor())

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                with home_scope(home):
                    engine.tick()
            except Exception:
                logger.warning("work engine tick failed", exc_info=True)
            stop_event.wait(interval_s)

    thread = threading.Thread(target=_loop, name="harness-serve-work-engine", daemon=True)
    thread.start()
    return thread
