"""The ``messaging_turn`` lane — a platform message from the moment it queues until its turn settles.

p10-messaging §2.5 / §3 M4 (RT-MESSAGING-M4-APPROVALS-OFF-DESKTOP), the ``scheduled_turn`` precedent: a
message the messaging bridge accepted is a QUEUED send on the bound instance's chat root whose origin
carries a ``messaging`` block (``messaging/bridge.py``); the send-queue entry lives until the runner has
recorded the settle and removed it, so the entry IS the durable record — read from any process, nothing
new written. ``phase`` says whether the turn waits for its root (``queued``) or runs (``running``).
"""

from __future__ import annotations

from typing import Any

from .. import chat_root_send_queue as send_queue
from ..projection_accountant import ProjectionAccountant

from .lanes_schedule import _epoch
from .ownership import _owner_of
from .rows import LanePass, _source, bounded_operator_text, elapsed_seconds, work_row
from .vocabulary import KIND_MESSAGING_TURN, LANE_DURABLE, SOURCE_OK, SOURCE_UNAVAILABLE, STATUS_RUNNING

__layer__ = "lanes"
__all__ = ["MESSAGING_ORIGIN_KEY", "MessagingTurnLane", "_collect_messaging_turns"]

#: The origin block the bridge writes (``work_store.persona_turn.OriginKind.MESSAGING``).
MESSAGING_ORIGIN_KEY = "messaging"


class MessagingTurnLane(LanePass):
    """Durable: the send-queue entries whose origin carries a ``messaging`` block."""

    kind = KIND_MESSAGING_TURN

    def collect(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            entries = send_queue.entries_from(MESSAGING_ORIGIN_KEY)
        except OSError as exc:
            return [], _source(SOURCE_UNAVAILABLE, lane=LANE_DURABLE, reason="store_unreadable",
                               detail=type(exc).__name__)
        rows = [self.row(entry) for entry in entries]
        return self.finish(rows), _source(SOURCE_OK, lane=LANE_DURABLE)

    def row(self, entry: send_queue.QueuedSend) -> dict[str, Any]:
        self.consider()
        block = (entry.args.get(send_queue.ORIGIN_ARG) or {}).get(MESSAGING_ORIGIN_KEY) or {}
        platform = bounded_operator_text(block.get("platform"), limit=40)
        persona_id, instance_id = _owner_of(entry.root_session_id, memo=self.owners)  # rule 5: one authority
        running = entry.state == send_queue.STATE_RUNNING
        return work_row(
            kind=self.kind,
            stable_id=f"{entry.root_session_id}/{entry.client_message_id}",
            label=f"{platform or 'messaging'}: message",
            status=STATUS_RUNNING,
            source_lane=LANE_DURABLE,
            persona_id=persona_id,
            persona_instance_id=instance_id,
            session_id=entry.root_session_id,
            started_at=str(entry.queued_at or ""),
            elapsed_seconds=elapsed_seconds(_epoch(entry.queued_at), now=self.now),
            extra={"platform": platform, "chat_id": bounded_operator_text(block.get("chat_id"), limit=80),
                   "thread_id": block.get("thread_id"), "phase": "running" if running else "queued"},
        )


def _collect_messaging_turns(
    *, now: float, accountant: ProjectionAccountant | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The messaging-turn lane's collector: one :class:`MessagingTurnLane` pass."""

    return MessagingTurnLane(now=now, accountant=accountant).collect()
