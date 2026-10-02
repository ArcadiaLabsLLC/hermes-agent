"""Execution-scoped control through the existing operator admission receipt."""
from __future__ import annotations

from collections.abc import Callable

from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
from agent_runtime.chat_turn_reservations import (
    ChatTurnReservationError, STATE_SETTLED, reserve_chat_turn,
)
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.mission_chat_turns.states import (
    TERMINAL_TURN_STATES, TURN_STATE_INTERRUPTED,
)

__layer__ = "lanes"


def execution_status(session_id: str, turn_id: str, *, stop: bool = False) -> dict:
    with reserve_chat_turn(turn_request_id=turn_id, verb=CHAT_MESSAGE_METHOD,
                           session_scope=session_id) as reservation:
        if stop and reservation.record.is_new:
            raise ChatTurnReservationError("execution_not_admitted", "This turn has no admission receipt.")
        if stop:
            reservation.request_stop()
        receipt = reservation.record
    journal = mission_chat_turn_record(session_id=session_id, client_message_id=turn_id)
    state = (journal or {}).get("state")
    if state in TERMINAL_TURN_STATES:
        outcome = "stopped" if state == TURN_STATE_INTERRUPTED else "finished"
    elif journal is None and receipt.state == STATE_SETTLED:
        outcome = "stopped" if receipt.exit_code == 130 else "finished"
    else:
        outcome = "stop_requested" if receipt.stop_requested else "unsettled"
    return {"turn_request_id": turn_id, "outcome": outcome,
            "admitted": not receipt.is_new, "stop_requested": receipt.stop_requested,
            "request_id": receipt.request_id}


def stop_operator_execution(session_id: str, turn_id: str,
                            interrupt: Callable[[str], bool]) -> dict:
    result = execution_status(session_id, turn_id, stop=True)
    if result["outcome"] == "stop_requested":
        # A disconnected owner is uncertainty, never evidence that work stopped.
        result["owner_observed"] = interrupt(turn_id)
    return result
