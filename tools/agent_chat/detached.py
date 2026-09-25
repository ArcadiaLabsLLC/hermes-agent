"""The ``wait=false`` half: the delivery preconditions, the detached dispatch, and ``agent_chat_dispatches``."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from types import MappingProxyType

from .lane import refusal_json, scope_off

__layer__ = "lanes"

logger = logging.getLogger(__name__)


def _async_delivery_available() -> bool:
    """Whether THIS lane can receive a background completion after the turn ends.

    The one capability contract, consulted rather than re-derived. It is bound
    per request by the mission-chat handler and answers True only for a
    serve-hosted turn whose delivery drain is actually running.
    """

    try:
        from agent_runtime.delivery_capability import async_delivery_declared
        from gateway.session_context import async_delivery_supported

        # A POSITIVE declaration is required, not merely a non-False answer.
        # `async_delivery_supported()` returns True for an unbound session, and
        # the mission-chat binding has exactly one call site — so any lane that
        # reaches this tool without going through `_cmd_mission_chat_message`
        # inherits an unexamined True and would be granted a durable promise on
        # the strength of nobody having said otherwise. Both real lanes bind it;
        # this makes the silence a refusal rather than trusting the default.
        return bool(async_delivery_declared() and async_delivery_supported())
    except Exception:  # pragma: no cover - defensive
        # Cannot read the capability ⇒ cannot promise delivery. Fail toward the
        # inline lane, which always works.
        return False


def _persona_of_chat_root(root_session_id) -> str:
    """The persona that owns a chat root, or ``""`` when it owns none.

    Deliberately THE SAME resolver the delivery drain routes on
    (``dispatch_delivery._sender_persona``), not a second one. That is what makes
    the admission check below sound: if this cannot name the sender, the drain
    will not be able to either, and accepting the dispatch would mean running
    real work whose answer is guaranteed to be dropped.
    """

    try:
        from agent_runtime.dispatch_delivery import _sender_persona

        owner = _sender_persona(str(root_session_id or ""))
    except Exception:  # pragma: no cover - defensive
        return ""
    return owner[0] if owner else ""


def _dispatch_homes() -> tuple[str, str]:
    """``(ambient_home, background_work_home)`` for the child process.

    Both come from the existing authorities, and it is worth being precise about
    what the first one actually is, because the name invites a wrong reading.

    ``get_hermes_home()`` is read HERE, inside the sender's turn — which means
    inside that persona's ``persona_profile_context``. So the value is the
    SENDER PERSONA's profile home, not the operator's. That is deliberate and it
    matches the synchronous relay lane, where the target's turn has always run
    nested inside the sender's flipped environment: a dispatched turn resolves
    the same profile-scoped state whether it was awaited or detached. It is
    still a behaviour change worth naming against the ORIGINAL in-process
    dispatch lane, which inherited whatever the process-global happened to be at
    the moment the worker thread ran — a value that depended on which unrelated
    persona turn was in flight, and was therefore not reliably anything.

    Reading it here rather than in the supervisor is what makes it deterministic
    at all: by the time the supervisor thread spawns, another persona turn may
    have flipped the process-global out from under it.

    ``get_hermes_background_work_home()`` is the one resolver for where
    background work is recorded, so the child's own background writers land
    exactly where this parent, the drain and the Activity projection read.
    """

    from hermes_constants import get_hermes_home
    from agent_runtime.profile_home import get_hermes_background_work_home

    return str(get_hermes_home()), str(get_hermes_background_work_home())


def _dispatch_detached(
    *,
    spec,
    persona_id,
    target_instance_id,
    sender_session,
    sender_persona,
    message,
    title,
    notify_operator,
    chain,
    wall_budget,
    remote_target=None,
):
    """Record a detached dispatch durably, queue its child turn, return the handle.

    ORDER IS THE CONTRACT. The durable row is written BEFORE the work is handed
    to the supervisor and before the caller is told anything, so there is no
    window in which the target's turn is running (or has already finished)
    against a dispatch nothing remembers. Written after, a process that died
    early would leave work whose result had nowhere to go and no record that it
    was ever asked for; a caller told ``dispatched: true`` for a row that failed
    to persist would wait forever for a delivery that can never be attempted.
    A store failure therefore REFUSES the dispatch instead of running it blind.

    **Gateway Stage 7: the row is the same row when the target is on another
    install.** Everything above is unchanged — the row is written first, on the
    SENDER's install, and the sender's operator sees the outstanding ask in
    Activity exactly as they do for a local one. What changes is one key on the
    spec, and therefore which leg the supervisor takes: a spec carrying
    ``remote_install_id`` is performed by a peer-tier call instead of by a child
    process. There is no distributed row and no two-phase state to reconcile;
    install B records the turn it ran in its own chat store, which is its own
    business and not this row's.
    """

    from agent_runtime.config import mission_chat_dispatch_max_concurrent
    from agent_runtime.dispatch_store import mint_dispatch_id, record_dispatch
    from tools.agent_chat_dispatch import dispatch_detached_turn

    dispatch_id = mint_dispatch_id()
    # The delivery turn is deduped on this id (see dispatch_delivery), so it is
    # minted HERE, once, and travels with the row.
    spec["client_message_id"] = f"agent-dispatch-{dispatch_id}"
    ambient_home, background_home = _dispatch_homes()
    spec["hermes_home"] = ambient_home
    spec["head_home"] = background_home
    if remote_target is not None:
        # The ID, not the name. A display name is chrome two installs can share
        # (Stage 6's field note #4), and the supervisor dials by id.
        spec["remote_install_id"] = remote_target.install_id
        spec["remote_display_name"] = remote_target.display_name
        spec["remote_target"] = remote_target.target
    started_at = time.time()
    try:
        record_dispatch(
            dispatch_id=dispatch_id,
            sender_session_id=sender_session,
            # The sender's own persona, already resolved by the admission check
            # above through the SAME resolver the drain routes on. Recorded
            # rather than left blank so a store row answers "who asked for this"
            # without a second lookup.
            sender_persona_id=sender_persona,
            target_persona=persona_id,
            target_instance_id=target_instance_id or "",
            title=title or "",
            ask=message,
            notify_operator=bool(notify_operator),
            relay_chain=list(chain),
            dispatched_at=started_at,
            remote_install_id=(
                "" if remote_target is None else remote_target.install_id
            ),
        )
    except Exception as exc:
        logger.exception("agent_chat_send could not record dispatch %s", dispatch_id)
        return refusal_json(
            f"could not record the dispatch durably ({type(exc).__name__}); nothing was sent. "
            "Send it with wait=true instead.",
            error_kind="dispatch_store_unavailable",
            target_persona=persona_id,
        )

    try:
        dispatch_detached_turn(
            dispatch_id=dispatch_id,
            spec=spec,
            max_concurrent=mission_chat_dispatch_max_concurrent(),
        )
    except Exception as exc:
        from agent_runtime.dispatch_store import STATE_ERROR, record_completion

        # The row exists and can never complete on its own, so settle it here.
        # It becomes a delivered "this never started" message rather than a
        # dispatch that stays `running` in the operator's HUD forever.
        record_completion(
            dispatch_id,
            state=STATE_ERROR,
            error=f"the dispatch could not be queued: {type(exc).__name__}",
        )
        logger.exception("agent_chat_send could not queue dispatch %s", dispatch_id)
        return refusal_json(
            f"could not start the background dispatch ({type(exc).__name__}).",
            error_kind="dispatch_queue_failed",
            target_persona=persona_id,
        )

    return json.dumps(
        {
            "ok": True,
            "dispatched": True,
            "dispatch_id": dispatch_id,
            "target_persona": persona_id,
            "session_id": None,
            "started_at": started_at,
            "max_seconds": wall_budget,
            "notify_operator": bool(notify_operator),
            "relay_chain": list(chain),
            # Say plainly what happens next. An agent that thinks this call
            # failed to return a reply will re-send; an agent that knows the
            # answer is coming as its own message will move on, which is the
            # entire behaviour change this lane is for.
            "next_expected": (
                "Their reply is NOT in this result — they are working on it now. It will arrive "
                "as a new message in this conversation when they finish and you are idle. Carry "
                "on with something else; do not re-send. Use agent_chat_dispatches to check "
                "whether it is still running."
            ),
        },
        indent=2,
        default=str,
    )


def agent_chat_dispatches(*, limit=10, state=None, requested_by_session=None):
    """List the caller's background dispatches. Read-only; creates nothing."""

    if scope_off():
        return refusal_json(
            "agent_chat is disabled on this runtime (HERMES_AGENT_CHAT_SCOPE=off). "
            "Tell the operator instead of retrying."
        )

    from agent_runtime.dispatch_store import STATE_RUNNING, list_dispatches
    from tools.agent_chat_dispatch import summarize_for_caller

    scope = str(requested_by_session or "").strip()
    if not scope:
        # Scoped to the caller's own chat root. With no caller identity the
        # honest answer is "I cannot tell which are yours", NOT everyone's.
        return json.dumps(
            {
                "ok": True,
                "count": 0,
                "dispatches": [],
                "next_expected": (
                    "this lane carries no chat session, so there are no dispatches of yours to list"
                ),
            }
        )

    wanted = str(state or "").strip().lower()
    try:
        bounded = max(1, min(int(limit or 10), 100))
    except (TypeError, ValueError):
        bounded = 10

    rows = list_dispatches(sender_session_id=scope, limit=bounded)
    keep = DISPATCH_FILTERS.get(wanted)
    if keep is not None:
        rows = [row for row in rows if keep(row)]

    summaries = [summarize_for_caller(row) for row in rows]
    running = sum(1 for row in summaries if row["state"] == STATE_RUNNING)
    return json.dumps(
        {
            "ok": True,
            "count": len(summaries),
            "running": running,
            "dispatches": summaries,
            "next_expected": (
                "still running — their full reply will be delivered to you as a new message when "
                "they finish; nothing to do"
                if running
                else "nothing in flight"
            ),
        },
        indent=2,
        default=str,
    )


def _is_running(row: dict) -> bool:
    from agent_runtime.dispatch_store import STATE_RUNNING

    return row.get("state") == STATE_RUNNING


#: This tool's ``state`` argument — ITS vocabulary, read by name here and in
#: the schema's enum, not the dispatch store's states (``running`` is spelled
#: alike and is a different question: a filter over rows, not a row's state).
FILTER_RUNNING = "running"
FILTER_DONE = "done"

#: ``state`` filter -> which rows it keeps. An unknown or absent filter keeps
#: every row, as it always has.
DISPATCH_FILTERS: Mapping[str, Callable[[dict], bool]] = MappingProxyType({
    FILTER_RUNNING: _is_running,
    FILTER_DONE: lambda row: not _is_running(row),
})
