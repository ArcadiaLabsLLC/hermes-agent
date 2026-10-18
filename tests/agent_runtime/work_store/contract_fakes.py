"""In-memory fakes of the dispatcher's SOURCE and EXECUTOR contracts (plan §2, stage B1).

The dispatcher's tests (B2 onwards) drive these instead of git and the chat runner. Each method has
the contract's exact signature (``test_contracts.py::test_fakes_and_production_match_the_contracts``)
and refuses with the contract's typed reasons.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from agent_runtime.work_store.board import Board
from agent_runtime.work_store.executor import (
    Assignment, ExecutorKind, Outcome, Run, RunStatus, StopReason,
)
from agent_runtime.work_store.grammar import Claim, Op, Row, RowRef, Status
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.source import Claimant
from agent_runtime.work_store.writer import Receipt

DATE = "2026-10-18"


def row(slot: str, note: str, row_id: str, *, heading: str = "Open", status: Status = Status.READY) -> Row:
    return Row(RowRef(slot, note, row_id), f"title {row_id}", status, DATE, "", None, None, None, (), (), (),
               heading, 0, f"- **`{row_id}` — title {row_id}** · {status.value} {DATE}")


class FakeSource:
    """Rows in a dict keyed by ``RowRef``; every write is one receipt, as the writer's are."""

    def __init__(self, rows: list[Row] = (), boards: list[Board] = ()) -> None:
        self.by_ref: dict[RowRef, Row] = {r.ref: r for r in rows}
        self._boards = list(boards)
        self.receipts: list[Receipt] = []

    def _receipt(self, ref: RowRef, op: Op, who: str, request_id: str) -> Receipt:
        receipt = Receipt(ref, op, who, request_id, f"c{len(self.receipts)}", 0, True, False, f"work.row_{op.value}")
        self.receipts.append(receipt)
        return receipt

    def _held(self, ref: RowRef, who: Claimant) -> Row:
        found = self.by_ref.get(ref)
        if found is None:
            raise WorkRefused(Reason.ROW_GONE, ref.id)
        if found.taken is None or found.taken.who != who.who:
            raise WorkRefused(Reason.NOT_CLAIMANT, ref.id)
        return found

    def boards(self, workspace_id: str) -> list[Board]:
        return [b for b in self._boards if b.workspace_id == workspace_id]

    def rows(self, workspace_id: str, *, status: Status | None = None, slot: str | None = None,
             assignee: str | None = None) -> list[Row]:
        return [r for r in self.by_ref.values()
                if (status is None or r.status is status) and (slot is None or r.ref.slot == slot)
                and (assignee is None or (r.assignee is not None and r.assignee.token == assignee))]

    def ready(self, workspace_id: str) -> list[Row]:
        return [r for r in self.rows(workspace_id, status=Status.READY) if r.taken is None]

    def claim(self, ref: RowRef, who: Claimant, request_id: str) -> Receipt:
        found = self.by_ref.get(ref)
        if found is None:
            raise WorkRefused(Reason.ROW_GONE, ref.id)
        if found.taken is not None and found.taken.who != who.who:
            raise WorkRefused(Reason.ALREADY_TAKEN, found.taken.who)
        self.by_ref[ref] = replace(found, taken=Claim(DATE, who.who))
        return self._receipt(ref, Op.CLAIM, who.who, request_id)

    def release(self, ref: RowRef, who: Claimant, status: Status, reason: str) -> Receipt:
        self.by_ref[ref] = replace(self._held(ref, who), taken=None, status=status, status_body=reason)
        return self._receipt(ref, Op.RELEASE, who.who, f"release:{ref.id}")

    def block(self, ref: RowRef, who: Claimant, question: str, recommend: str) -> Receipt:
        return self.release(ref, who, Status.BLOCKED, f"owner decision — {question} · Recommend: {recommend}")

    def done(self, ref: RowRef, who: Claimant, result: str) -> Receipt:
        self._held(ref, who)
        del self.by_ref[ref]
        return self._receipt(ref, Op.DELETE, who.who, f"done:{ref.id}")

    def append(self, board: Board, row: Row, request_id: str) -> Receipt:
        if any(r.ref.slot == row.ref.slot and r.ref.id == row.ref.id for r in self.by_ref.values()):
            raise WorkRefused(Reason.ID_EXISTS, row.ref.id)
        self.by_ref[row.ref] = row
        return self._receipt(row.ref, Op.APPEND, "operator", request_id)


class FakeExecutor:
    """Runs nothing: ``start`` queues, ``settle`` (the test's hand) reports an outcome."""

    kind = ExecutorKind.PERSONA_TURN

    def __init__(self, *, refuse: Reason | None = None) -> None:
        self.refuse = refuse
        self.runs: dict[str, Run] = {}
        self.statuses: dict[str, RunStatus] = {}
        self._callback: Callable[[Run, Outcome], None] | None = None

    def can_start(self, a: Assignment) -> Reason | None:
        return self.refuse

    def start(self, a: Assignment) -> Run:
        if self.refuse is not None:
            raise WorkRefused(self.refuse, a.persona_instance_id)
        run = self.runs.setdefault(a.request_id, Run(f"run-{a.request_id}", a.request_id, a, "root", "cmid", DATE,
                                                     RunStatus.QUEUED))
        self.statuses.setdefault(run.run_id, RunStatus.QUEUED)
        return run

    def status(self, run_id: str) -> RunStatus:
        return self.statuses.get(run_id, RunStatus.STOPPED)

    def stop(self, run_id: str, reason: StopReason) -> dict[str, Any]:
        stopped = self.statuses.get(run_id) is RunStatus.QUEUED
        self.statuses[run_id] = RunStatus.STOPPED if stopped else self.statuses.get(run_id, RunStatus.STOPPED)
        return {"kind": "work.exec_stop", "run_id": run_id, "reason": reason.value, "stopped": stopped}

    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None:
        self._callback = cb

    def settle(self, request_id: str, outcome: Outcome) -> None:
        run = self.runs[request_id]
        self.statuses[run.run_id] = RunStatus.SETTLED
        if self._callback is not None:
            self._callback(run, outcome)


class FakeGoal:
    """One root's goal with upstream ``GoalManager``'s surface; decisions are scripted by the test."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.state: Any = None
        self.gates: list[str] = []
        self.decisions: list[dict[str, Any]] = []
        self.evaluated: list[tuple[str, bool]] = []

    def set(self, goal: str, *, max_turns: int | None = None, contract: Any = None) -> Any:
        self.state = SimpleNamespace(goal=goal, status="active", contract=contract, max_turns=max_turns,
                                     paused_reason=None)
        self.gates = []
        return self.state

    def add_gate(self, command: str) -> None:
        self.gates.append(command)

    def is_active(self) -> bool:
        return self.state is not None and self.state.status == "active"

    def has_goal(self) -> bool:
        return self.state is not None and self.state.status in {"active", "paused"}

    def pause(self, reason: str = "user-paused") -> Any:
        self.state.status, self.state.paused_reason = "paused", reason
        return self.state

    def evaluate_after_turn(self, last_response: str, *, user_initiated: bool = True) -> dict[str, Any]:
        self.evaluated.append((last_response, user_initiated))
        decision = self.decisions.pop(0)
        if decision.get("verdict") == "done":
            self.state.status = "done"
        return decision

    def next_continuation_prompt(self) -> str:
        return f"[Continuing toward your standing goal]\nGoal: {self.state.goal}"


class FakeGoals:
    """``goals(session_id)`` → that root's one :class:`FakeGoal` (the executor's ``goals`` seam)."""

    def __init__(self) -> None:
        self.by_root: dict[str, FakeGoal] = {}

    def __call__(self, session_id: str) -> FakeGoal:
        return self.by_root.setdefault(session_id, FakeGoal(session_id))


def decision(verdict: str, *, go_on: bool = False, reason: str = "judge said so") -> dict[str, Any]:
    prompt = "continue please" if go_on else None
    return {"status": "active" if go_on else verdict, "should_continue": go_on, "continuation_prompt": prompt,
            "verdict": verdict, "reason": reason, "message": reason}
