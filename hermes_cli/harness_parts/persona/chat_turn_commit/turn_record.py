"""A chat turn's admission record: who sent it, from where, and when it started — taken ONCE.

``TASK-ONE-TURN-RECORD`` (review batch B59 H4). Before this module a turn rebuilt its sender at
every point that needed it: the active-turn hand-off (``run.py::_agent_ready_for_steer``) and both
leftover-steer queues (``leftover_steer.py``) each called ``queued_turn_origin.send_origin()`` again,
mid-turn, off the serve request's context variables, and each got the right answer for a QUEUED
run only because ``chat_root_send_queue.persistable_args`` lets the namespace's own
``send_origin`` field (restored from the queued entry) overwrite the live read it was handed. The
journal, meanwhile, stamped its own ``started_at`` at the write-ahead, a third clock.

Now the turn takes one :class:`ChatTurnRecord` when ``TurnCommit`` is built (admission, under the
chat-root lease) and every reader takes it from there:

- ``origin`` — the queued entry's origin when the runner runs a queued send (the namespace carries
  it), else the serve request's (``send_origin()``); the device a late steer's turn answers and the
  link a queued turn binds follow from it;
- ``requested_by`` — the send's requester (operator, ``work:<request>``, ``agent:<session>``);
- ``started_at`` — the admission instant; the write-ahead journal record's ``started_at`` IS this
  value (``journal.transition_mission_chat_turn(started_at=)``), so the running-work row, replay
  order and the record agree.

The record is frozen: nothing later in the turn re-derives or replaces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

__layer__ = "lanes"

__all__ = ["ChatTurnRecord", "admit_turn_record"]


@dataclass(frozen=True)
class ChatTurnRecord:
    """Who sent one chat turn, from where, and when it was admitted."""

    origin: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    requested_by: str | None = None
    started_at: str = ""

    def origin_dict(self) -> dict[str, Any]:
        """A fresh, mutable copy of :attr:`origin` for a persisted send."""

        return dict(self.origin)


def _admitted_origin(args: Any) -> dict[str, Any]:
    from agent_runtime.chat_root_send_queue import ORIGIN_ARG
    from hermes_cli.harness_parts.serve.queued_turn_origin import send_origin

    carried = getattr(args, ORIGIN_ARG, None)
    # MUTATION: read send_origin() first and a queued run's record names no sender
    # (test_turn_record's queued-run case reddens).
    if isinstance(carried, Mapping):
        return dict(carried)
    return send_origin()


def admit_turn_record(args: Any, *, now: str | None = None) -> ChatTurnRecord:
    """The turn's one record, taken at admission from its send and the serve request it arrived on."""

    from agent_runtime.clock import now_iso_micro

    requested_by = getattr(args, "requested_by", None)
    return ChatTurnRecord(
        origin=MappingProxyType(_admitted_origin(args)),
        requested_by=str(requested_by) if requested_by else None,
        started_at=now or now_iso_micro(),
    )
