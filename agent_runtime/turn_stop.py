"""Stop on a running reply, ONE function for every door and every starter (``RT-STOP-REACHES-EVERY-RUNNING-REPLY-THROUGH-ONE-SEAM``).

A reply is started by many hands: the operator's send (admitted by the serve), a send that waited on its
busy chat (the queued-send runner), a schedule's fire, a Work pass, a goal's next turn, a lens episode, a
relay from another agent, a helper's result coming back. Every one of them runs through the mission-chat
turn handler, and the handler registers ONE stop handle for the turn when it starts
(:func:`agent_runtime.live_turns.turn_stop_handle`, upstream's ``InterruptScope``). Stop reaches a reply
through that handle, whoever started it, and two doors call this one function:

* the conversation's Stop (``runtime.operator.conversation.stop`` → ``operator_execution``);
* the Activity cancel of a chat-turn row (``runtime.work.cancel`` → ``running_work.surface``).

Every step below applies to every turn; none asks who started it:

1. the run the turn is a pass of is told to stop (``goal_turns.stop_from_conversation``; a turn that is
   no pass of a run answers None and nothing is marked) — Stop on a pass of an until-done run ends the run;
2. a reply still waiting in its conversation's send queue is told to stop when it starts: its stop handle
   is cancelled as it registers, and upstream's scope interrupts the agent the moment it joins, so the reply
   settles ``stopped`` through its own path (the settle, the queue entry, the Work engine's ``settled``);
3. a running reply is stopped through its stop handle (and its agent's own interrupt).

The answer is one vocabulary, :class:`TurnStop`, which each door spells in its own envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__layer__ = "lanes"

__all__ = ["ENDS_AFTER_PASS", "ENDS_NOW", "TurnStop", "stop_turn"]

#: The reply ends now: it was interrupted here, or will be the moment it begins.
ENDS_NOW = "now"
#: A Work pass running where this process cannot reach it: it ends the run when it settles.
ENDS_AFTER_PASS = "after_pass"


@dataclass(frozen=True)
class TurnStop:
    """What one Stop reached. ``owner_observed``: a running reply here was told to stop, or a waiting one
    will be when it starts — the stop is not only recorded."""

    turn_id: str
    owner_observed: bool
    ends: str
    #: ``work_run`` when the turn was a pass of an until-done run (the whole run stops), else ``turn``.
    stopped: str = "turn"
    work_request: str = ""
    dependent_dispatches: list[dict] = field(default_factory=list)

    def block(self) -> dict:
        """The fields both doors carry, spelled once."""

        return {"outcome": "stop_requested", "stop_requested": True, "owner_observed": self.owner_observed,
                "ends": self.ends, "stopped": self.stopped,
                **({"work_request": self.work_request} if self.work_request else {}),
                "dependent_dispatches": list(self.dependent_dispatches)}


def stop_turn(session_id: str, turn_id: str, *, reason: str, scope_checked: bool = False) -> TurnStop | None:
    """Stop the reply ``turn_id`` of conversation ``session_id``; None when it names no reply of it here.

    ``turn_id`` is the client message id or its turn-id spelling (``safe_assignment_token``: the
    running-work row's ``chat_turn:<turn id>``). ``scope_checked``: the caller proved the turn belongs to
    this conversation already (an admitted send's receipt, ``operator_execution_reservation``), so a reply
    whose handle has not learnt its conversation yet is reached too.
    """

    from agent_runtime.live_turns import stop_live_turn, stop_when_started
    from agent_runtime.mission_chat_turns.states import TERMINAL_TURN_STATES
    from agent_runtime.serde import safe_assignment_token
    from agent_runtime.work_store.goal_turns import stop_from_conversation

    session, named = str(session_id or ""), str(turn_id or "").strip()
    if not session or not safe_assignment_token(named):
        return None
    record = _journal(session, named)
    cmid = str((record or {}).get("client_message_id") or named)
    live_id = str((record or {}).get("turn_id") or safe_assignment_token(named))
    run = stop_from_conversation(session, cmid)
    reached = stop_live_turn(live_id, session_id=session, reason=reason, any_session=scope_checked)
    waiting = False
    if not reached and _waiting(session, live_id):
        waiting = stop_when_started(live_id, session_id=session)
        # It started between the two reads: its handle is there now, so it is stopped as a running reply.
        reached = not waiting and stop_live_turn(live_id, session_id=session, reason=reason, any_session=scope_checked)
    if run is None and not waiting and not reached:
        return None
    bound, pass_running = run if run is not None else (None, False)
    # A pass still running that this process could not reach (its record says so) ends the run at its settle.
    unsettled = record is not None and record.get("state") not in TERMINAL_TURN_STATES
    ends = ENDS_AFTER_PASS if bound is not None and (pass_running or unsettled) and not (reached or waiting) \
        else ENDS_NOW
    return TurnStop(turn_id=named, owner_observed=bool(reached or waiting), ends=ends,
                    stopped="work_run" if bound is not None else "turn",
                    work_request=bound.request_id if bound is not None else "",
                    dependent_dispatches=_cancel_dispatches(session, live_id, reason))


def _journal(session: str, named: str) -> dict | None:
    """The turn's journal record, named by its client message id or by its turn id (the running-work row's
    spelling); None when this conversation has none. It joins the two names: the run's pass is known by the
    first, the live registry by the second."""

    from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record, mission_chat_turn_records
    from agent_runtime.serde import safe_assignment_token

    record = mission_chat_turn_record(session_id=session, client_message_id=named)
    if record is not None:
        return record
    token = safe_assignment_token(named)
    return next((row for row in mission_chat_turn_records(session_id=session) if row.get("turn_id") == token), None)


def _waiting(session: str, live_id: str) -> bool:
    """A reply of this conversation waits in its send queue, not yet begun (either spelling of its id)."""

    from agent_runtime import chat_root_send_queue as send_queue
    from agent_runtime.serde import safe_assignment_token

    return any(entry.state != send_queue.STATE_RUNNING and safe_assignment_token(entry.client_message_id) == live_id
               for entry in send_queue.entries(session))


def _cancel_dispatches(session: str, live_id: str, reason: str) -> list[dict]:
    from agent_runtime.operator_execution import cancel_turn_dispatches

    return cancel_turn_dispatches(session, live_id, reason=reason)
