"""The ``scheduled_turn`` lane — a scheduler fire from the moment it queues until its turn settles.

RT-SCHEDULE-TURN-RUNNING-WORK (RULED 2026-10-18: a scheduled fire is a new kind ``scheduled_turn``, not
``cron_job``). A fire of ``work_store/serve_scheduler.py::ServeTickScheduler`` is a QUEUED send on a chat
root whose origin names its schedule; the send-queue entry exists from the fire until the runner has
recorded the turn's settle and removed it, so the entry IS the durable record — read from any process,
nothing new written. ``phase`` says whether the turn waits for its root (``queued``) or runs
(``running``); while it runs the chat-turn lane also carries the turn itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import chat_root_send_queue as send_queue
from ..projection_accountant import ProjectionAccountant

from .ownership import _owner_of
from .rows import LanePass, _source, bounded_operator_text, elapsed_seconds, work_row
from .vocabulary import KIND_SCHEDULED_TURN, LANE_DURABLE, SOURCE_OK, SOURCE_UNAVAILABLE, STATUS_RUNNING

__layer__ = "lanes"
__all__ = ["ScheduledTurnLane", "_collect_scheduled_turns"]


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


class ScheduledTurnLane(LanePass):
    """Durable: the send-queue entries whose origin carries ``schedule``."""

    kind = KIND_SCHEDULED_TURN

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            entries = send_queue.entries_from(send_queue.SCHEDULE_ORIGIN_KEY)
        except OSError as exc:
            return [], _source(SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="store_unreadable",
                               detail=type(exc).__name__)
        rows = [self.row(entry) for entry in entries]
        return self.finish(rows), _source(SOURCE_OK, lane=LANE_DURABLE)

    def row(self, entry: send_queue.QueuedSend) -> dict[str, Any]:
        self.consider()
        origin = entry.args.get(send_queue.ORIGIN_ARG) or {}
        key = bounded_operator_text(origin.get(send_queue.SCHEDULE_ORIGIN_KEY), limit=120)
        persona_id, instance_id = _owner_of(entry.root_session_id, memo=self.owners)  # rule 5: one authority
        started = _epoch(origin.get("fired_at")) or _epoch(entry.queued_at)
        running = entry.state == send_queue.STATE_RUNNING
        return work_row(
            kind=self.kind,
            stable_id=f"{entry.root_session_id}/{entry.client_message_id}",
            label=f"scheduled: {key}",
            status=STATUS_RUNNING,
            source_lane=LANE_DURABLE,
            persona_id=persona_id,
            persona_instance_id=instance_id,
            session_id=entry.root_session_id,
            started_at=str(origin.get("fired_at") or entry.queued_at or ""),
            elapsed_seconds=elapsed_seconds(started, now=self.now),
            extra={"schedule_key": key, "fire": bounded_operator_text(origin.get("fire"), limit=160),
                   "phase": "running" if running else "queued", "work_request": origin.get("work") or None},
        )


def _collect_scheduled_turns(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The scheduled-turn lane's collector: one :class:`ScheduledTurnLane` pass."""

    return ScheduledTurnLane(now=now, accountant=accountant).collect()
