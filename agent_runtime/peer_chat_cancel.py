"""``peer.agent_chat.cancel``'s owner side: stop a turn a paired install asked this one to run.

Cancel is owned by the process that supervises the work, and for a cross-install
dispatch that is THIS install: the sender's row lives on install A, the turn runs
here. A asks with the dispatch id; this module re-derives the turn request id the
execute carried (:func:`agent_runtime.chat_turn.dispatch_turn_request_id`), proves
the receipt belongs to the asking install, and stops the turn through the chat
Stop door (the serve's ``interrupt_operator`` seam plus the receipt's durable
``stop_requested``, which a turn still queued on the pool reads when it starts).

Stop semantics (owner ruling D1.07 b, 2026-10-10): a turn that already produced
partial output is stopped and its partial output is kept — the interrupt ends the
turn the way the operator's Stop does, and what it wrote stays in its thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__layer__ = "lanes"

__all__ = [
    "PEER_CANCEL_ALREADY_FINISHED",
    "PEER_CANCEL_NOT_RUNNING",
    "PEER_CANCEL_OUTCOMES",
    "PEER_CANCEL_STOPPING",
    "cancel_peer_turn",
]

#: A live turn was found and its Stop was delivered; the turn settles itself.
PEER_CANCEL_STOPPING = "stopping"
#: The turn is settled here; its ``exit_code`` is echoed.
PEER_CANCEL_ALREADY_FINISHED = "already_finished"
#: No turn for this dispatch, accepted from the ASKING install, exists here.
PEER_CANCEL_NOT_RUNNING = "not_running"
PEER_CANCEL_OUTCOMES: tuple[str, ...] = (
    PEER_CANCEL_STOPPING,
    PEER_CANCEL_ALREADY_FINISHED,
    PEER_CANCEL_NOT_RUNNING,
)


def cancel_peer_turn(
    dispatch_id: str,
    *,
    peer_install_id: str,
    interrupt: Callable[[str], bool],
) -> dict[str, Any]:
    """Stop the turn ``peer_install_id`` asked this install to run for ``dispatch_id``.

    The receipt's replay SCOPE carries the install that sent the execute
    (``normalize_peer_chat_execute``), so a receipt another install's execute
    wrote answers ``not_running`` here: install C cannot stop the turn install A
    asked for, and is not told that one exists.
    """

    from agent_runtime.chat_turn import PEER_CHAT_EXECUTE_METHOD, dispatch_turn_request_id
    from agent_runtime.chat_turn_reservations import (
        STATE_ACCEPTED,
        STATE_SETTLED,
        read_chat_turn_receipt,
        reserve_chat_turn,
    )
    from agent_runtime.serve_rpc.protocol import PEER_REQUESTED_BY_PREFIX

    turn_request_id = dispatch_turn_request_id(dispatch_id)
    answer: dict[str, Any] = {"dispatch_id": dispatch_id, "turn_request_id": turn_request_id}
    receipt = read_chat_turn_receipt(turn_request_id)
    owned_scope = f"{PEER_REQUESTED_BY_PREFIX}{peer_install_id}/"
    if (
        receipt is None
        or receipt.verb != PEER_CHAT_EXECUTE_METHOD
        or not receipt.session_scope.startswith(owned_scope)
    ):
        return {**answer, "outcome": PEER_CANCEL_NOT_RUNNING}
    if receipt.state == STATE_SETTLED:
        return {**answer, "outcome": PEER_CANCEL_ALREADY_FINISHED, "exit_code": receipt.exit_code}
    if receipt.state != STATE_ACCEPTED:  # pragma: no cover - a written receipt is one of the two
        return {**answer, "outcome": PEER_CANCEL_NOT_RUNNING}
    # Durable FIRST: a turn still queued behind the pool has no inflight entry
    # for the interrupt to find, and reads this mark when its worker starts it.
    with reserve_chat_turn(
        turn_request_id=turn_request_id,
        verb=PEER_CHAT_EXECUTE_METHOD,
        session_scope=receipt.session_scope,
    ) as reservation:
        reservation.request_stop()
    return {
        **answer,
        "outcome": PEER_CANCEL_STOPPING,
        # True when this serve held the turn in flight and interrupted it; False
        # when it was queued (the durable mark stops it) or already exiting.
        "owner_observed": bool(interrupt(turn_request_id)),
    }
