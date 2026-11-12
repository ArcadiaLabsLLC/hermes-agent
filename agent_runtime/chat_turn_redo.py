"""Redo a delivered reply on another model, once, without moving the chat's model (RT-CHAT-TURN-MODEL-AND-REDO).

A redo is a ``runtime.chat.message`` send that carries ``turn_model`` (``turn_provider``) and
``retry_of`` naming the chat's LATEST turn that delivered a reply (Eternia plan
``REGENERATE_WITH_ANOTHER_MODEL_2026-11-12`` decision 3). The new turn answers the same operator
message on that model for this turn alone; the redone turn's rows stay in history (its reply row
gets ``retried_as``) and are left out of the model input of the redo and of every turn after a
delivered redo, so the chat reads to the model as a straight line.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .mission_chat_turns.states import TURN_STATE_COMPLETED, TURN_STATE_NATIVE_COMMITTED, TURN_STATE_PROJECTED
from .persona_assignments import safe_assignment_text

__layer__ = "policy"

#: The journal states of a turn that delivered its reply (settling included: the reply is durable).
DELIVERED_TURN_STATES = frozenset({TURN_STATE_PROJECTED, TURN_STATE_NATIVE_COMMITTED, TURN_STATE_COMPLETED})

#: The redo's provider and model, stamped on its write-ahead record and echoed on its reply row.
TURN_MODEL_FIELDS = ("turn_provider", "turn_model")


def _cid(record: Mapping[str, Any]) -> str:
    return safe_assignment_text(record.get("client_message_id"), limit=240)


def latest_delivered_turn(records: Iterable[Mapping[str, Any]], *, current: str) -> str | None:
    """The client_message_id of the newest delivered turn other than ``current``, or ``None``.

    ``records`` is the chat's journal in start order (``mission_chat_turn_records``)."""
    delivered = [_cid(record) for record in records
                 if record.get("state") in DELIVERED_TURN_STATES and _cid(record) != current]
    return delivered[-1] if delivered else None


def redone_message_ids(records: Iterable[Mapping[str, Any]], *, current: str, current_redo_of: str | None) -> set[str]:
    """The turns whose rows a turn's model input leaves out: the one this turn redoes, and every
    turn an earlier redo replaced once that redo delivered (a redo that failed gives its origin back)."""
    redone = {current_redo_of} if current_redo_of else set()
    for record in records:
        origin = safe_assignment_text(record.get("retry_of"), limit=240)
        if (origin and record.get("turn_model") and _cid(record) != current
                and record.get("state") in DELIVERED_TURN_STATES):
            redone.add(origin)
    return redone
