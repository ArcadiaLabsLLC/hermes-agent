"""``BoardSource`` — the production SOURCE (dispatcher plan §2.1) over the boards and the W2 writer.

Reads come from hermes's own worktree of each slot after a fetch (``work.store.synced``); every write
is the writer's ``apply`` of ONE row op, by ID, replayed on a lost race. Nothing is cached across
calls except the fetch. ``release``, ``block`` and ``done`` carry no request id in the contract, so
each derives one from the row, the claimant and what it writes: a repeat is a replay, a different
ending is a different commit. Status text passes through ``grammar.segment_text`` (a persona's words
can never break the row grammar).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..work_store import board as boards_store
from ..work_store.board import Board
from ..work_store.grammar import OWNER_DECISION, Op, Row, RowRef, Status, render_status, segment_text
from ..work_store.models import Claimant
from ..work_store.reasons import Reason, WorkRefused
from ..work_store.writer import Receipt, RowOp

__layer__ = "lanes"  # imports work_store.source.Claimant (a lanes module); RT-BATCH-LAYER-TYPES
__all__ = ["BoardSource"]


def _derived_id(verb: str, ref: RowRef, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join([ref.slot, ref.note, ref.id, *parts]).encode("utf-8")).hexdigest()[:12]
    return f"{verb}:{ref.id}:{digest}"


class BoardSource:
    """One workspace's rows from every board; writes through each slot's writer.

    Bound to ``workspace_id`` because the contract's writes carry only a ``RowRef`` (slot, note, ID).
    """

    def __init__(self, workspace_id: str, *, sync: Callable[..., Any] | None = None,
                 today: Callable[[], str] | None = None) -> None:
        self.workspace_id = workspace_id
        self._sync = sync
        self._today = today or (lambda: datetime.now(UTC).date().isoformat())

    def _view(self, workspace_id: str, *, slot: str | None = None) -> Any:
        if self._sync is None:
            from ..work.store import synced

            self._sync = synced
        return self._sync(workspace_id, slot=slot)

    def _writer(self, ref: RowRef, workspace_id: str) -> Any:
        view = self._view(workspace_id, slot=ref.slot)
        writer = view.writers.get(ref.slot)
        if writer is None:
            raise WorkRefused(Reason.SLOT_UNBOUND, ref.slot)
        return writer

    def _apply(self, ref: RowRef, op: Op, who: Claimant, request_id: str, payload: dict[str, Any]) -> Receipt:
        return self._writer(ref, self.workspace_id).apply(RowOp(ref, op, who.who, request_id, payload))

    # ── the contract ─────────────────────────────────────────────────────

    def boards(self, workspace_id: str) -> list[Board]:
        return list(self._view(workspace_id).boards)

    def rows(self, workspace_id: str, *, status: Status | None = None, slot: str | None = None,
             assignee: str | None = None) -> list[Row]:
        view = self._view(workspace_id)
        return boards_store.rows(workspace_id, status=status, slot=slot, assignee=assignee, read_roots=view.read_roots)

    def ready(self, workspace_id: str) -> list[Row]:
        return [row for row in self.rows(workspace_id, status=Status.READY) if row.taken is None]

    def claim(self, ref: RowRef, who: Claimant, request_id: str) -> Receipt:
        return self._apply(ref, Op.CLAIM, who, request_id, {})

    def release(self, ref: RowRef, who: Claimant, status: Status, reason: str) -> Receipt:
        body = segment_text(reason)
        rid = _derived_id("release", ref, who.who, status.value, body)
        self._apply(ref, Op.RELEASE, who, f"{rid}:release", {})
        return self._apply(ref, Op.SET_STATUS, who, f"{rid}:status",
                           {"status": render_status(status, self._today(), body)})

    def block(self, ref: RowRef, who: Claimant, question: str, recommend: str) -> Receipt:
        status = render_status(Status.BLOCKED, self._today(), f"{OWNER_DECISION} — {segment_text(question)}")
        status += f" · Recommend: {segment_text(recommend) or 'none offered'}"
        rid = _derived_id("block", ref, who.who, status)
        self._apply(ref, Op.SET_STATUS, who, f"{rid}:status", {"status": status})
        return self._apply(ref, Op.RELEASE, who, f"{rid}:release", {})

    def done(self, ref: RowRef, who: Claimant, result: str) -> Receipt:
        text = " ".join(str(result or "done").split())[:4000]
        return self._apply(ref, Op.DELETE, who, _derived_id("done", ref, who.who), {"result": text})

    def append(self, board: Board, row: Row, request_id: str) -> Receipt:
        if board.workspace_id != self.workspace_id:
            raise WorkRefused(Reason.INVALID, f"board of {board.workspace_id}, source of {self.workspace_id}")
        return self._apply(row.ref, Op.APPEND, Claimant.operator(), request_id, {"row": row.raw})
