"""The forge and the message it forges: provenance, the delivered block, idle gating, forge_delivery_turn."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from ..mission_chat_door import run_mission_chat_turn
from .accounting import IdleProbe, _LAST_IDLE_PROBE
from .vocabulary import (
    IDLE_JOURNAL_INFLIGHT,
    IDLE_JOURNAL_UNREADABLE,
    IDLE_LEASE_BUSY_OWNED,
    IDLE_LEASE_BUSY_OWNERLESS,
    IDLE_LEASE_PROBE_ERROR,
    REPLY_LIMIT,
    delivery_requested_by,
)

__layer__ = "lanes"


def format_elapsed(seconds: float) -> str:
    """Seconds as the delivered block's prose ("3m12s"); not :func:`clock.elapsed_ms`'s arithmetic."""

    seconds = int(max(0.0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if rest == 0 else f"{minutes}m{rest}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h" if minutes == 0 else f"{hours}h{minutes}m"


def format_dispatch_delivery(row: dict[str, Any]) -> str:
    """The self-contained block a delivery turn carries.

    Modelled on ``process_registry._format_async_delegation`` and for the same
    reason: by the time this re-enters the conversation the sender may be deep
    in unrelated context and will not remember why the dispatch existed. So the
    block stands entirely on its own — who was asked, what they were asked, what
    came back, where the thread is, and how long it took — enough to either use
    the result or re-dispatch because the world moved on.
    """

    from ..persona_assignments import persona_instance_display_name

    result = row.get("result") or {}
    status = str(row.get("state") or "unknown")
    reply = str(result.get("reply") or "")[:REPLY_LIMIT]
    error = str(result.get("error") or "")
    persona = str(row.get("target_persona") or "")
    instance = str(row.get("target_instance_id") or "")
    # WHO REPLIED, in the words an operator uses for them.
    #
    # The row records a persona id and an instance handle, and neither is what
    # anyone calls this agent: the block used to open with a bare dispatch id and
    # then say "You dispatched neko_supervisor_agent", so the sender's model and
    # the operator reading over its shoulder both had to map a handle back to a
    # teammate themselves (operator ruling, 2026-08-24).
    #
    # The resolution is fail-safe by construction — see
    # :func:`persona_assignments.persona_instance_display_name` — because THIS
    # function runs inside the forge, whose exceptions burn one of eight delivery
    # attempts. A name that will not resolve degrades to the id, never to a lost
    # delivery, and never to a guessed name.
    display_name = persona_instance_display_name(instance)
    # Most-to-least specific, and every tier is something the reader can act on:
    # the name they know, else the exact instance, else the persona, else the
    # honest placeholder the block has always used.
    target = display_name or persona or "the teammate"
    # The header's attribution segment. Omitted entirely when nothing identifies
    # the target, so a row that can name nobody keeps the exact header it has
    # always had rather than gaining an empty "reply from".
    attribution = ""
    if display_name:
        attribution = (
            f"reply from {display_name} ({instance})" if instance
            else f"reply from {display_name}"
        )
    elif instance or persona:
        attribution = f"reply from {instance or persona}"
    ask = str(row.get("ask") or "")
    dispatched_at = float(row.get("dispatched_at") or 0.0)
    completed_at = float(row.get("completed_at") or time.time())

    lines = [
        "[BACKGROUND DISPATCH COMPLETE — "
        + (f"{attribution} — " if attribution else "")
        + f"{row.get('dispatch_id')}]",
        (
            f"You dispatched {target} in the background earlier and kept working. "
            "They have finished; their answer is below. You may have moved on since "
            "then — use this, or re-dispatch if things have changed."
        ),
        "",
        # The name leads, but the persona id and the instance handle both stay:
        # a name is what a human reads and an id is what a tool call needs, and
        # the block is the sender's only copy of either. When no name resolved
        # this line is byte-identical to what it has always been.
        f"Dispatched to: {target}"
        + (f" — {persona}" if display_name and persona else "")
        + (f" ({instance})" if instance else ""),
    ]
    if dispatched_at:
        lines.append(
            "Dispatched: "
            + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(dispatched_at))
            + f" ({format_elapsed(completed_at - dispatched_at)} ago)"
        )
    if ask:
        lines.append("")
        lines.append("What you asked them:")
        lines.append(ask[:2000])
    lines.append("")
    lines.append(f"Status: {status}")
    if row.get("target_session_id"):
        # Thread pointer, not a transcript: the full exchange lives there and
        # agent_chat_open / agent_chat_log_path can read it on demand.
        lines.append(
            f"Their thread: {row['target_session_id']} "
            "(agent_chat_open with this session_id to read the whole exchange)"
        )
    lines.append("")
    if reply:
        lines.append("--- THEIR REPLY ---")
        lines.append(reply)
    if error:
        lines.append("--- ERROR ---")
        lines.append(error[:600])
    if not reply and not error:
        # The generic line was the only one available before the supervisor
        # recorded WHY, and it left the sender to guess between two very
        # different situations: a teammate who answered with nothing, and an
        # answer that never made it back. Re-dispatching is right for one of
        # them and pointless for the other, so the block says which when it
        # knows and keeps the honest shrug when it does not.
        from ..turn_visibility import TurnVisibility

        visibility = TurnVisibility.from_dict((result or {}).get("visibility"))
        if visibility.is_silent:
            lines.append(f"No reply text — {visibility.describe()}.")
            lines.append(
                "Their turn ENDED IN SILENCE; the answer was not lost in transit, so "
                "re-dispatching runs the same turn again. Read the thread above."
            )
        else:
            lines.append(
                "They returned no reply text. Read the thread above, or re-dispatch."
            )
    if row.get("notify_operator"):
        lines.append("")
        lines.append(
            "OPERATOR IS WAITING ON THIS: you flagged this dispatch to notify the operator. "
            "Tell them the result now, in this conversation, in your own words — what you "
            "asked for, what came back, and what you are doing about it."
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# idle gating
# --------------------------------------------------------------------------


def _probe_sender_idle(root_session_id: str) -> IdleProbe:
    """Whether the sender's chat root has a turn in flight, AND why not.

    Two independent signals, and BOTH are needed. The lease answers "is a turn
    holding this root right now" — but only while its holder is alive, so a
    turn whose executor died leaves the lease free while the journal still shows
    it in flight. The journal answers "does the record say a turn is running" —
    but it is written by whichever process ran the turn and lags a live
    acquisition. Trusting either one alone delivers into a thread that is mid-turn.

    Pure: it reads the same two sources in the same order and takes the same
    zero-timeout, release-immediately lease probe as before — no extra lock
    traffic. What is new is the typed reason on each way out, because four
    distinct causes collapsing into one silent ``False`` is exactly why the
    2026-08-11 stall could not be classified. The busy sub-reasons:

    * ``journal_inflight`` — a turn record says a turn is running.
    * ``journal_unreadable`` — the journal store itself could not be read
      (fail-closed: a delayed delivery costs nothing, a spliced one corrupts a
      conversation).
    * ``lease_busy_owned`` — the lease is held and the owner file names its
      holder. Normal contention.
    * ``lease_busy_ownerless`` — the lease is held and NO owner file is
      readable. Release order is unlink-owner-then-unlock, so one sample can be
      a releasing holder caught mid-window; REPEATS across consecutive passes
      are the stale-byte-range-lock fingerprint.
    * ``lease_probe_error`` — anything else the probe raised.
    """

    from ..mission_chat_turns.reads import mission_chat_turn_records
    from ..mission_chat_turns.states import INFLIGHT_TURN_STATES
    from ..persona_chat_continuity import PersonaChatBusyError, persona_chat_root_lease

    try:
        records = mission_chat_turn_records(session_id=root_session_id)
    except Exception as exc:
        # Cannot read the journal ⇒ cannot prove idle. Fail closed: a delayed
        # delivery costs nothing, a spliced one corrupts a conversation.
        return IdleProbe(False, IDLE_JOURNAL_UNREADABLE, repr(exc))
    for record in records or []:
        state = str((record or {}).get("state") or "")
        if state in INFLIGHT_TURN_STATES:
            return IdleProbe(
                False,
                IDLE_JOURNAL_INFLIGHT,
                f"client_message_id={(record or {}).get('client_message_id')!r} state={state}",
            )

    try:
        # Probe ONLY: acquire with no wait and release immediately. Holding it
        # across the forge would deadlock against the handler's own acquisition
        # of the same root.
        with persona_chat_root_lease(
            root_session_id, owner_id="dispatch-delivery-probe", observer_kind="serve"
        ):
            pass
    except PersonaChatBusyError as exc:
        # `owner` is populated from `<stem>.owner.json` by the lease itself; an
        # empty payload means the lock is held with no readable owner.
        owner = dict(getattr(exc, "owner", None) or {})
        if owner:
            return IdleProbe(False, IDLE_LEASE_BUSY_OWNED, f"owner={owner}")
        return IdleProbe(
            False, IDLE_LEASE_BUSY_OWNERLESS, "lease held with no readable owner file"
        )
    except Exception as exc:
        return IdleProbe(False, IDLE_LEASE_PROBE_ERROR, repr(exc))
    return IdleProbe.idle()


def _sender_is_idle(root_session_id: str) -> bool:
    """True when the sender's chat root has no turn in flight.

    THE DECISION, and the only function the drain's decision consults. It keeps
    its name, signature and semantics deliberately: the drain's tests override
    this exact attribute, and routing the decision through anything else would
    silently stop those overrides from biting while the suite still printed
    green. Accounting reads the stash below AFTER the fact; it never replaces
    this call.
    """

    probe = _probe_sender_idle(root_session_id)
    _LAST_IDLE_PROBE.set(probe)  # A — accounting stash; see _record_sender_busy
    return probe.is_idle  # D — unchanged meaning, unchanged truth table


def _sender_persona(root_session_id: str) -> tuple[str, str] | None:
    """``(persona_id, persona_instance_id)`` that owns a chat root, or None.

    This is the POSITIVE OWNERSHIP proof a restored completion needs (#64484):
    a row recovered from a previous process names a chat root, and delivery only
    proceeds if that root still resolves to a real persona instance in THIS
    runtime. Absence of the instance is not "deliver anyway", it is "do not".

    The derivation itself lives in
    :func:`agent_runtime.persona_assignments.chat_session_owner_persona`, the
    runtime's ONE answer to "whose work is this" — shared with the running-work
    projection, which used to ship a null owner on every delegation row rather
    than reach for it. This name stays as the delivery lane's local vocabulary
    and must never grow a second derivation.
    """

    from ..persona_assignments import chat_session_owner_persona

    return chat_session_owner_persona(root_session_id)


# --------------------------------------------------------------------------
# the forge
# --------------------------------------------------------------------------


def forge_delivery_turn(
    *,
    root_session_id: str,
    persona_id: str,
    persona_instance_id: str,
    message: str,
    client_message_id: str,
    dispatch_id: str = "",
    notify_operator: bool = False,
    state: str | None = None,
    max_seconds: float | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Run one delivery as a real mission-chat turn. Returns ``(ok, payload)``.

    Goes through the mission-chat turn door (:mod:`agent_runtime.mission_chat_door`),
    which the CLI binds to the canonical handler at plugin registration and at
    serve boot; the door takes the payload off the handler's ``payload_sink``
    seam, so nothing is printed into the serve frame protocol. An unbound door
    raises ``MissionChatDoorUnbound`` — a forge exception, which the drain
    records as ``forge_failed:exception`` and retries within its budget.
    """

    from ..config import mission_chat_default_max_seconds

    args = SimpleNamespace(
        persona_id=persona_id,
        persona_instance_id=persona_instance_id,
        session_id=root_session_id,
        clarify_token=None,
        # NEVER a fresh thread: the delivery belongs in the conversation the
        # dispatch was sent from, which is the whole point of delivering it.
        new_session=False,
        task_id=None,
        goal_id=None,
        title=None,
        message=message,
        provider=None,
        model=None,
        use_agent_default=False,
        surface_prompt="",
        intent_hint="chat",
        # Structured provenance: the handler decodes this into the typed marker
        # the persisted user row carries, which is the ONLY reason a consumer
        # can tell a delivered result from something the operator typed.
        requested_by=delivery_requested_by(
            dispatch_id, notify_operator=notify_operator, state=state
        ),
        client_message_id=client_message_id,
        stream=False,
        max_seconds=float(max_seconds or mission_chat_default_max_seconds()),
        json=True,
        requested_by_session=root_session_id,
        # A delivery is a NEW CHAIN ROOT: it is not a hop of the original relay
        # (that chain ended when the target answered), and giving it the old
        # chain would make the sender's own follow-up sends look like depth-3
        # hops of a conversation that is already over.
        relay_chain=[],
        relay_deadline_epoch=None,
    )
    exit_code, payload = run_mission_chat_turn(args)
    ok = exit_code == 0 and bool((payload or {}).get("ok"))
    return ok, payload
