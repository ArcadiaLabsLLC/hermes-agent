"""ONE dispatched turn, run natively in this Hermes: the door's arguments, its turn thread, its interrupt.

Owner ruling 2026-11-21 (row ``RT-AGENT-DISPATCH-RUNS-AS-A-NATIVE-TURN-IN-THE-SAME-HERMES``): a turn one
agent sends another runs in the same Hermes as every other turn — the same memory, approvals, model
resolution and job lifecycle — never in a second Hermes spawned for it. It therefore enters through the
same door as the inline relay and the delivery forge (``agent_runtime.mission_chat_door``, bound to the
CLI's turn handler at serve boot), on a thread of this process. What a turn gets from that door, it gets
here unchanged: the helper's own approval queue (``tools.approval``'s per-session gateway queue, bound by
``profile_runner``'s ``session_approval_scope`` on the helper's chat root), the helper's chat model
resolution, its background jobs in this process's registry, and its entry in ``live_turns``.

Crash and hang isolation (the row's open question; decided 2026-11-21 by this lane, recorded on the row):
in-process with cooperative limits, the way upstream's ``delegate_task`` runs its children
(``tools/delegate_tool.py``: in-process ``AIAgent`` on a daemon pool, stopped through the agent's own
``interrupt``). The turn carries its own wall budget (``max_seconds``) and lands itself; the supervisor
(:func:`run_turn`) waits for it on a daemon thread, interrupts it through ``live_turns`` when a Stop or the
budget plus :data:`~.outcome.KILL_GRACE_SECONDS` arrives, and past :data:`ABANDON_GRACE_SECONDS` more
settles the request without it (``abandoned``): a thread cannot be killed, so a wedged tool keeps its thread
until it returns, but the request, the concurrency slot and the sender are free. A Python exception in the
turn is the handler's to settle as for any turn; a fault that takes the interpreter down takes the serve with
it, as it would an operator's own turn.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from .outcome import KILL_GRACE_SECONDS

logger = logging.getLogger(__name__)

__layer__ = "lanes"

#: How long a turn that was told to stop (by a Stop, or past its budget plus grace) gets to end before the
#: request is settled without it. The interrupt bit is read by the running tool's wait loop and the agent's
#: loop between steps, so a cooperative turn ends within seconds.
ABANDON_GRACE_SECONDS = 30.0
#: How often the supervisor looks at its turn: a Stop that lands before the turn registered in ``live_turns``
#: is re-sent at this cadence until it is taken.
SUPERVISE_POLL_SECONDS = 0.5


@dataclass
class TurnRun:
    """What one native dispatched turn came back with."""

    exit_code: int | None = None
    payload: dict[str, Any] | None = None
    #: ``""`` when the turn ended by itself; ``budget_exceeded`` past its budget plus grace;
    #: ``failed:<Type>`` when the door raised.
    exit_reason: str = ""
    error: str = ""
    #: The turn was told to stop (a Stop or the budget) and did not end within the grace: the request is
    #: settled without it and its thread is left to return on its own.
    abandoned: bool = False
    #: The supervisor reached the turn's interrupt seam.
    interrupted: bool = False


def turn_args(spec: dict[str, Any], *, deadline_epoch: float) -> SimpleNamespace:
    """The mission-chat handler's arguments for a dispatched turn — the inline relay's namespace.

    ``new_session`` travels uncoerced (``None`` lets the handler's thread policy decide). The relay chain
    travels whole so depth and cycle detection run at the handler's chokepoint; only the clock is fresh,
    minted by the caller when the turn starts (a dispatch queued behind the concurrency cap never burns
    its budget waiting).
    """

    return SimpleNamespace(
        persona_id=str(spec["persona_id"]),
        persona_instance_id=spec.get("persona_instance_id") or None,
        session_id=spec.get("session_id") or None,
        clarify_token=spec.get("clarify_token") or None,
        new_session=spec.get("new_session"),
        task_id=None,
        goal_id=None,
        title=spec.get("title") or None,
        message=str(spec["message"]),
        provider=None,
        model=None,
        use_agent_default=False,
        surface_prompt="",
        intent_hint=str(spec.get("intent_hint") or "chat"),
        requested_by=str(spec.get("requested_by") or "agent-chat-relay"),
        client_message_id=spec.get("client_message_id") or None,
        stream=False,
        max_seconds=float(spec["max_seconds"]),
        json=True,
        requested_by_session=spec.get("requested_by_session") or None,
        relay_chain=[str(item) for item in (spec.get("relay_chain") or []) if str(item).strip()],
        relay_deadline_epoch=float(deadline_epoch),
    )


def _dispatch_homes_scope(spec: dict[str, Any]):
    """The homes the dispatch was made from, bound context-locally on the turn's thread.

    Captured in the sender's turn (``tools/agent_chat/detached.py::_dispatch_homes``): the head home, so
    the target resolves against the roster the inline relay resolves against, and the background-work
    home. A ContextVar binding, so no other turn of this process sees it.
    """

    from contextlib import nullcontext

    home = str(spec.get("hermes_home") or "")
    if not home:
        return nullcontext()
    from agent_runtime.profile_context import process_home_scope

    return process_home_scope(home, head_home=str(spec.get("head_home") or "") or None)


def _turn_body(spec: dict[str, Any], args: SimpleNamespace, run: TurnRun) -> None:
    from agent_runtime.mission_chat_door import run_mission_chat_turn

    try:
        with _dispatch_homes_scope(spec):
            run.exit_code, run.payload = run_mission_chat_turn(args)
    except BaseException as exc:  # the supervisor records it; the thread never raises into nothing
        logger.exception("dispatched turn %s raised", getattr(args, "client_message_id", ""))
        run.exit_reason = f"failed:{type(exc).__name__}"
        run.error = f"{type(exc).__name__}: {exc}"


def interrupt_dispatch_turn(client_message_id: str) -> bool:
    """Stop a dispatched turn running in this process through its agent's own seam; False when none runs.

    The turn is found by its request id (``dispatch_store.models.dispatch_turn_request_id``) in the turn
    journal's in-flight rows, then interrupted in ``live_turns`` — the seam the conversation's Stop uses.
    """

    from agent_runtime.live_turns import interrupt_turn
    from agent_runtime.mission_chat_turns.reads import inflight_turn_rows

    message = str(client_message_id or "")
    if not message:
        return False
    try:
        rows = [row for row in inflight_turn_rows() if row.get("client_message_id") == message]
    except Exception:
        logger.debug("dispatched turn %s: journal not read for its stop", message, exc_info=True)
        rows = []
    for row in rows:
        turn_id = str(row.get("turn_id") or "")
        if turn_id and interrupt_turn(turn_id, reason="dispatch_cancel"):
            return True
    from agent_runtime.serde import safe_assignment_token

    fallback = safe_assignment_token(message)
    return bool(fallback) and interrupt_turn(fallback, reason="dispatch_cancel")


def run_turn(
    spec: dict[str, Any],
    *,
    budget: float,
    stop_requested: Callable[[], bool],
    interrupt: Callable[[str], bool] | None = None,
) -> TurnRun:
    """Run one dispatched turn on a thread of this process and supervise it to its end.

    ``stop_requested`` is read each poll: a Stop is carried to the turn's interrupt seam (and re-sent until
    the turn has registered to take it). Past ``budget`` plus :data:`~.outcome.KILL_GRACE_SECONDS` the turn
    is interrupted as ``budget_exceeded``. A turn told to stop that is still running
    :data:`ABANDON_GRACE_SECONDS` later is left to its thread and the run comes back ``abandoned``. The
    three timings are read when the run starts.
    """

    interrupt = interrupt or interrupt_dispatch_turn
    poll_seconds, grace_seconds, abandon_seconds = SUPERVISE_POLL_SECONDS, KILL_GRACE_SECONDS, ABANDON_GRACE_SECONDS

    deadline_epoch = time.time() + float(budget)
    args = turn_args(spec, deadline_epoch=deadline_epoch)
    run = TurnRun()
    thread = threading.Thread(
        target=_turn_body, args=(spec, args, run), daemon=True,
        name=f"agent-chat-dispatch-turn-{str(args.client_message_id or '')[:28]}",
    )
    thread.start()
    hard_stop = time.monotonic() + float(budget) + float(grace_seconds)
    told_at: float | None = None
    while True:
        thread.join(poll_seconds)
        if not thread.is_alive():
            return run
        now = time.monotonic()
        stopping = stop_requested()
        if not stopping and now >= hard_stop and not run.exit_reason:
            run.exit_reason = "budget_exceeded"
        if (stopping or run.exit_reason) and not run.interrupted:
            run.interrupted = bool(interrupt(str(args.client_message_id or "")))
        if (stopping or run.exit_reason) and told_at is None:
            told_at = now
        if told_at is not None and now - told_at >= float(abandon_seconds):
            run.abandoned = True
            logger.warning(
                "dispatched turn %s did not end %.0fs after it was told to stop; settled without it",
                args.client_message_id, abandon_seconds,
            )
            return run
