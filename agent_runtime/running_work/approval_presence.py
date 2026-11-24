"""A pending approval rides the ``running_work`` section, raised and settled as stream events.

Row ``RT-FU-A-PENDING-APPROVAL-ARRIVES-AS-AN-UPDATE``. Eternia polled
``runtime.operator.conversation.approvals`` every 2 s for every chat it watched (a running turn,
each running helper chat, Home's deck): on the owner's serve 2026-11-23 those reads queued about
1.8 s each behind other reads. The approval is a fact hermes already holds — upstream's gateway
queue (``tools.approval``), which every chat turn of the serve uses
(``session_controls.session_approval_scope``) — so hermes pushes it instead:

* raised: the root's gateway notify callback (``session_controls._notify_root``) calls
  :func:`approval_raised` after upstream queued the entry, which records the root, observes the
  entry's settle (``tools.approval.observe_gateway_settle``, the additive seam) and appends
  :data:`EVENT_APPROVAL_RAISED`;
* settled (answered, denied, timed out, withdrawn, the turn ended): the observer appends
  :data:`EVENT_APPROVAL_SETTLED` after upstream took the entry off the queue.

Both are ``running_work`` events (``stream.frames``): a batch of them ships the section alone,
and inside a turn's batch they name no root, so the turn's overlay (which carries the whole
section) still carries the batch. :func:`pending_approvals` is the section's
``pending_approvals``: each pending request of each root, as ``conversation.approvals``
answers it (``session_controls.pending_session_approvals``, redacted), with its ``session_id``.
``conversation.approvals`` stays as the one-shot read.

Process-local, like :mod:`agent_runtime.live_turns`: only the serve that runs a chat's turns
holds its queue, so a section read in any other process lists none. Every append is fail-safe:
a notice is not the approval, and a raising notify would make upstream deny it for every surface.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

__layer__ = "lanes"

__all__ = [
    "APPROVAL_PRESENCE_EVENT_TYPES",
    "EVENT_APPROVAL_RAISED",
    "EVENT_APPROVAL_SETTLED",
    "approval_raised",
    "pending_approvals",
]

logger = logging.getLogger(__name__)

#: Registered in :mod:`agent_runtime.decision_contract_registry` in the same commit as this emitter (S55).
EVENT_APPROVAL_RAISED = "running_work.approval_raised"
EVENT_APPROVAL_SETTLED = "running_work.approval_settled"
APPROVAL_PRESENCE_EVENT_TYPES = frozenset({EVENT_APPROVAL_RAISED, EVENT_APPROVAL_SETTLED})

_ID_LIMIT = 240

#: Roots that raised an approval in this process and may still hold one. Written by
#: :func:`approval_raised`; a root whose queue is empty leaves it at the next read.
_roots: set[str] = set()
_lock = threading.Lock()


def approval_raised(session_id: str, data: dict[str, Any]) -> bool:
    """One raised approval of ``session_id``'s queue: observe its settle, append the raise. Never raises."""

    try:
        from ..persona_assignments import safe_assignment_text

        root = safe_assignment_text(session_id, limit=_ID_LIMIT)
        request_id = safe_assignment_text(data.get("request_id"), limit=_ID_LIMIT)
        if not root:
            return False
        with _lock:
            _roots.add(root)
        if request_id:
            from tools.approval import observe_gateway_settle

            observe_gateway_settle(root, request_id,
                                   lambda reason: _append_approval_event(EVENT_APPROVAL_SETTLED, root, request_id, reason))
        # MUTATION: drop this append and test_a_turns_approval_reaches_the_running_work_section reddens.
        return _append_approval_event(EVENT_APPROVAL_RAISED, root, request_id, None)
    except Exception:
        logger.debug("approval_presence: the raise notice failed", exc_info=True)
        return False


def pending_approvals() -> list[dict[str, Any]]:
    """Every pending approval this process holds, oldest root first: ``{session_id, id, command,
    description, choices}``. Never raises (a lane must never break the section)."""

    with _lock:
        roots = sorted(_roots)
    rows: list[dict[str, Any]] = []
    try:
        from ..session_controls import pending_session_approvals
    except Exception:
        return rows
    for root in roots:
        try:
            pending = pending_session_approvals(root)
        except Exception:
            continue
        if not pending:
            with _lock:
                _roots.discard(root)
            continue
        rows.extend({"session_id": root, **row} for row in pending)
    return rows


def _append_approval_event(event_type: str, root: str, request_id: str | None, reason: Any) -> bool:
    try:
        from hermes_time import now

        from ..events import EventLog
        from ..models import Event

        payload = {"root_chat_session_id": root, "approval_id": request_id or None}
        # Each type named at its own append so the S55 emitter walk sees both.
        if event_type == EVENT_APPROVAL_SETTLED:
            payload["reason"] = str(reason or "") or None
            EventLog().append(Event(type="running_work.approval_settled", task_id=None, run_id=None,
                                    persona_id=None, ts=now(), payload=payload, session_id=root))
        else:
            EventLog().append(Event(type="running_work.approval_raised", task_id=None, run_id=None,
                                    persona_id=None, ts=now(), payload=payload, session_id=root))
        return True
    except Exception:
        logger.debug("approval_presence: %s for %s was not appended", event_type, root, exc_info=True)
        return False
