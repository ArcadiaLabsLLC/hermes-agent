"""Execution-scoped control through the existing operator admission receipt."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager

from agent_runtime.chat_observation_policy import chat_observation_guidance
from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
from agent_runtime.chat_turn_reservations import (
    ChatTurnReservationError, STATE_SETTLED, read_chat_turn_receipt, reserve_chat_turn,
)
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.mission_chat_phases import TURN_PHASES_KEY, turn_timing_block
from agent_runtime.serde import safe_assignment_token
from agent_runtime.mission_chat_turns.states import (
    TERMINAL_TURN_STATES, TURN_STATE_INTERRUPTED,
)

__layer__ = "lanes"


@contextmanager
def operator_execution_reservation(session_id: str, turn_id: str):
    """Join a resolved session to its immutable admission using journal evidence.

    A send without session_id is admitted under its instance (or persona),
    before the worker resolves its root. Never rewrite that replay scope or
    infer execution ownership from the instance's current default pointer.
    """
    key = str(turn_id or "").strip()
    receipt = read_chat_turn_receipt(key)
    scope = session_id
    if receipt is not None and receipt.session_scope != session_id:
        journal = mission_chat_turn_record(session_id=session_id, client_message_id=key)
        if journal is None:
            raise ChatTurnReservationError("execution_scope_unresolved",
                                           "This turn has not resolved this conversation yet.")
        instance_id = journal.get("persona_instance_id")
        scopes = {instance_id} if instance_id else set()
        if instance_id and receipt.session_scope.startswith("persona:"):
            instance = PersonaInstanceStore().get(instance_id)
            if instance.id == instance_id:
                scopes.add(f"persona:{instance.persona_id}")
        if journal.get("root_chat_session_id") != session_id or receipt.session_scope not in scopes:
            raise ChatTurnReservationError("turn_request_conflict",
                                           "This turn was admitted for a different chat target.")
        scope = receipt.session_scope
    with reserve_chat_turn(turn_request_id=turn_id, verb=CHAT_MESSAGE_METHOD,
                           session_scope=scope, accepting=False) as reservation:
        yield reservation


def execution_status(session_id: str, turn_id: str, *, stop: bool = False) -> dict:
    with operator_execution_reservation(session_id, turn_id) as reservation:
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
    timing = None
    if (not receipt.is_new and journal is not None
            and journal.get("client_message_id") == str(turn_id).strip()
            and journal.get("turn_id") == safe_assignment_token(turn_id)
            and journal.get("root_chat_session_id") == session_id):
        timing = turn_timing_block(
            phases=journal.get(TURN_PHASES_KEY), profile_timing=journal.get("profile_timing")
        )
    return {"turn_request_id": turn_id, "outcome": outcome,
            **({"timing": timing} if timing is not None else {}),
            "admitted": not receipt.is_new, "stop_requested": receipt.stop_requested,
            **chat_observation_guidance(terminal=outcome in {"stopped", "finished"})}


def stop_operator_execution(session_id: str, turn_id: str,
                            interrupt: Callable[[str], bool]) -> dict:
    result = execution_status(session_id, turn_id, stop=True)
    if result["outcome"] == "stop_requested":
        # A disconnected owner is uncertainty, never evidence that work stopped.
        result["owner_observed"] = interrupt(turn_id)
        # Stop reaches the work this turn started and nothing else: the
        # dispatches it made (an explicit wait=false, or an inline relay the
        # lane detached because the turn held the run lock) are cancelled with
        # it. A turn that finished on its own keeps its children running —
        # their answers still arrive — which is why this sits under
        # ``stop_requested`` and not beside every outcome.
        result["dependent_dispatches"] = cancel_turn_dispatches(session_id, turn_id)
    return result


def cancel_turn_dispatches(session_id: str, turn_id: str, *,
                           reason: str = "operator_stop") -> list[dict]:
    """Cancel every ``running`` dispatch the turn ``(session_id, turn_id)`` made.

    Routed through ``running_work.cancel_work`` so a dispatch is stopped by the
    same identity-guarded seam the operator's cancel button uses, and each row
    answers for itself: ``stopping`` (a child is being killed; the supervisor
    settles it), ``cancelled`` (never started), ``already_finished`` (its result
    is kept) or a typed refusal when this process does not supervise it.
    """

    from agent_runtime.dispatch_store import running_dispatches_owned_by_turn
    from agent_runtime.running_work import cancel_work
    from agent_runtime.running_work.vocabulary import KIND_DISPATCH

    answers = []
    for row in running_dispatches_owned_by_turn(session_id, turn_id):
        dispatch_id = str(row.get("dispatch_id") or "")
        verdict = cancel_work(f"{KIND_DISPATCH}:{dispatch_id}", reason=reason)
        answers.append({
            "dispatch_id": dispatch_id,
            "target_persona": row.get("target_persona") or "",
            "outcome": verdict.get("outcome") or verdict.get("code") or "unknown",
        })
    return answers
