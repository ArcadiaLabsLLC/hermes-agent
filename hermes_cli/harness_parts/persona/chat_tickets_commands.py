"""Clarify tickets and delivery repair verbs: tickets, dispatch redeliver, turn resolve.

Separate because these act on a turn after the fact, never start one.
"""

from __future__ import annotations

import time
from agent_runtime.cli_format import emit_json
from agent_runtime.config import mission_chat_clarify_token_binding
from agent_runtime.persona_assignments import (
    safe_assignment_text,
    safe_assignment_token,
)
from agent_runtime.persona_chat_continuity import (
    CLARIFY_TICKET_TTL_SECONDS,
    PersonaChatClarifyTicketStore,
)
from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import _list_envelope, _print_stage42, _sort_rows

__layer__ = "lanes"
__all__ = [
    "_cmd_mission_chat_clarify_tickets",
    "_cmd_mission_chat_dispatch_redeliver",
    "_cmd_mission_chat_turn_resolve",
]


#: The three ways a clarify question's answer can have reached its thread, plus
#: the bucket for a question that has not been answered at all. ORDERED, because
#: the histogram is read as a ladder: `clarify_token` is the runtime owning the
#: binding, `session_id` is a caller that complied with the prompt, `none` is the
#: bug still happening, and `unsettled` is a question nobody answered yet.
CLARIFY_BOUND_VIA_BUCKETS = ("clarify_token", "session_id", "none", "unsettled")


def _clarify_ticket_row(record: dict, *, now: float, ttl_seconds: float) -> dict:
    created_at = float(record.get("created_at") or 0.0)
    answered_at = record.get("answered_at")
    return {
        # The token is a LOOKUP KEY validated against a stored record, never a
        # capability secret (see PersonaChatClarifyTicketStore), so printing it
        # is what makes this readout actionable: an operator can hand a stuck
        # agent the token its answer should have carried.
        "id": safe_assignment_text(record.get("clarify_token"), limit=240) or None,
        "state": str(record.get("state") or "") or None,
        "bound_via": record.get("bound_via") or None,
        "age_seconds": round(max(now - created_at, 0.0), 3) if created_at else None,
        # Orthogonal to state, and deliberately so: TTL governs GC only, so an
        # expired ticket is one the sweep MAY prune — it still binds until the
        # file is actually gone. Reporting it as a state would claim a cliff the
        # store does not have.
        "expired": bool(created_at and (now - created_at) > ttl_seconds),
        "chat_session_id": safe_assignment_text(record.get("chat_session_id"), limit=240)
        or None,
        "persona_id": record.get("persona_id") or None,
        "persona_instance_id": record.get("persona_instance_id") or None,
        "asked_by_client_message_id": record.get("asked_by_client_message_id") or None,
        "answered_by_client_message_id": record.get("answered_by_client_message_id") or None,
        "requested_by_session": record.get("requested_by_session") or None,
        "answered_age_seconds": (
            round(max(now - float(answered_at), 0.0), 3) if answered_at else None
        ),
    }


#: What the redeliver verb tells the operator to do about each refusal. Beside
#: the outcomes rather than inside the handler so a new outcome cannot ship
#: without an answer to "so what do I do".
_DISPATCH_REDELIVER_NEXT_EXPECTED = {
    "not_found": "check the dispatch id; only rows still inside the store's retention window exist",
    "already_delivered": "nothing to do — the sender already received this reply",
    "not_dropped": "the row is still queued; the drain will deliver it on its next pass",
}


def _cmd_mission_chat_dispatch_redeliver(args) -> int:
    """Re-arm one DROPPED dispatch reply for another delivery pass.

    The operator's way back from a terminal give-up. A dropped row still holds a
    real answer that its sender was never told — the 2026-08-24
    ``foreign_chat_session`` outage produced a queue full of exactly these — and
    once the reason the delivery was refused is fixed and a serve restart has
    picked the fix up, the row deserves another pass rather than a hand-written
    re-send that loses the dispatch's provenance.

    Refusals are TYPED, not silent: re-arming a delivered row would deliver a
    second copy, and re-arming a pending one would tell an operator something
    happened when nothing did.

    Never prints message bodies. The ask and the reply live on the row, the row
    is a queue record and not a transcript, and an operator repairing a delivery
    queue does not need to read either — the thread this re-arms into is where
    the text belongs.
    """

    # Function-local, like the rest of this file. Neither vocabulary is
    # re-spelled — the admission kind is the enum member, and the queue's own
    # refusals are read off ``dispatch_store``, which owns them.
    from agent_runtime import dispatch_store
    from agent_runtime.mission_chat_outcome import ChatErrorKind

    dispatch_id = safe_assignment_text(getattr(args, "dispatch_id", None), limit=200)
    if not dispatch_id:
        data = attach_root_observability(
            {
                "ok": False,
                "capability_id": "mission.chat.dispatch.redeliver",
                "error_kind": ChatErrorKind.INVALID_REQUEST,
                "error": "dispatch_id is required",
            }
        )
        print(emit_json(data) if args.json else data["error"])
        return 2

    try:
        outcome, row = dispatch_store.rearm_delivery(dispatch_id)
    except Exception as exc:
        data = attach_root_observability(
            {
                "ok": False,
                "capability_id": "mission.chat.dispatch.redeliver",
                "error_kind": dispatch_store.ERROR_KIND_DISPATCH_STORE_UNAVAILABLE,
                "error": safe_assignment_text(str(exc), limit=320),
                "dispatch_id": dispatch_id,
            }
        )
        print(emit_json(data) if args.json else data["error"])
        return 2

    record = row if isinstance(row, dict) else {}
    # The queue-record fields ONLY. `ask` / `reply` are deliberately absent.
    state = {
        "dispatch_id": dispatch_id,
        "state": record.get("state") or "",
        "delivery_state": record.get("delivery_state") or "",
        "delivery_attempts": int(record.get("delivery_attempts") or 0),
        "delivery_error": record.get("delivery_error") or None,
        "target_persona": record.get("target_persona") or "",
        "target_instance_id": record.get("target_instance_id") or "",
        "sender_session_id": record.get("sender_session_id") or "",
    }
    if outcome != dispatch_store.REARM_REARMED:
        data = attach_root_observability(
            {
                "ok": False,
                "capability_id": "mission.chat.dispatch.redeliver",
                "error_kind": dispatch_store.REARM_ERROR_KINDS.get(
                    outcome, dispatch_store.ERROR_KIND_DISPATCH_STORE_UNAVAILABLE
                ),
                "error": f"dispatch delivery cannot be re-armed: {outcome}",
                "outcome": outcome,
                **state,
                "next_expected": _DISPATCH_REDELIVER_NEXT_EXPECTED.get(
                    outcome, "inspect the dispatch row before re-arming it"
                ),
            }
        )
        print(emit_json(data) if args.json else data["error"])
        return 2

    data = attach_root_observability(
        {
            "ok": True,
            "capability_id": "mission.chat.dispatch.redeliver",
            "outcome": outcome,
            **state,
            "next_expected": (
                "the serve delivery drain picks it up on its next pass; a serve "
                "process without the fix that dropped it will drop it again"
            ),
        }
    )
    print(
        emit_json(data)
        if args.json
        else (
            f"re-armed {dispatch_id}: delivery_state="
            f"{state['delivery_state']} attempts={state['delivery_attempts']}"
        )
    )
    return 0


def _cmd_mission_chat_clarify_tickets(args) -> int:
    """Read-only adoption readout for the clarify-token binding.

    The design's rollout step: watch echo adoption climb, WITHOUT new event
    kinds (telemetry is not the EventLog here). Everything below is read from
    state the binding already records — the per-turn ``clarify_binding.bound_via``
    is mirrored onto the ticket at settle, so the ticket files alone answer it.

    ``bound_via: "none"`` is the number that matters. It counts questions whose
    answer landed in a thread the caller neither named nor bound — the original
    defect, still happening. ``clarify_token`` climbing against it is the whole
    point of the feature; ``unsettled`` is a question nobody has answered yet and
    is not evidence either way.

    Strictly read-only: no mint, no settle, and NO SWEEP. A readout that pruned
    would silently change the very population it is reporting on, and an operator
    checking adoption twice would get two different denominators."""

    store = PersonaChatClarifyTicketStore()
    now = time.time()
    ttl_seconds = float(CLARIFY_TICKET_TTL_SECONDS)
    try:
        records, unreadable = store.scan_tickets()
    except OSError:
        records, unreadable = [], 0
    wanted_session = safe_assignment_text(getattr(args, "session_id", None), limit=240)
    wanted_state = safe_assignment_token(getattr(args, "state", None))
    rows = [_clarify_ticket_row(record, now=now, ttl_seconds=ttl_seconds) for record in records]

    # Counts are computed over the WHOLE store, before --session-id/--state/
    # --limit narrow the listing. A filtered view is a lens on the population,
    # not a redefinition of it: an adoption ratio that moved because the operator
    # asked to see fewer rows would be a lying metric.
    states: dict[str, int] = {}
    bound_via: dict[str, int] = {bucket: 0 for bucket in CLARIFY_BOUND_VIA_BUCKETS}
    expired = 0
    for row in rows:
        states[str(row["state"] or "unknown")] = states.get(str(row["state"] or "unknown"), 0) + 1
        bucket = str(row["bound_via"] or "unsettled")
        bound_via[bucket] = bound_via.get(bucket, 0) + 1
        if row["expired"]:
            expired += 1

    listed = rows
    if wanted_session:
        listed = [row for row in listed if row["chat_session_id"] == wanted_session]
    if wanted_state:
        listed = [row for row in listed if row["state"] == wanted_state]
    listed = _sort_rows(listed, getattr(args, "sort", None))
    limit = getattr(args, "limit", None)
    truncated = False
    if limit is not None and limit >= 0 and len(listed) > limit:
        listed = listed[:limit]
        truncated = True

    data = _list_envelope("clarify_ticket", listed, cursor=None, truncated=truncated)
    data.update(
        {
            "ok": True,
            "capability_id": "mission.chat.clarify_tickets",
            # The gate's CURRENT setting, which is not the same question as
            # whether the tickets below were minted under it: turning the gate
            # off stops minting but leaves the store readable, and those tickets
            # are exactly what an operator wants to see after a rollback.
            "binding_enabled": bool(mission_chat_clarify_token_binding()),
            "ttl_seconds": ttl_seconds,
            "total": len(rows),
            # Additive, and it belongs beside ``total`` because it is the same
            # question: how many tickets is this readout actually about. A file
            # that would not decode is missing from every count above, including
            # the denominator of the adoption ratio the block below tells the
            # operator to watch. Stating it is the difference between a metric
            # that is narrower than the store and one that lies about it.
            "unreadable": unreadable,
            "states": states,
            "bound_via": bound_via,
            "expired": expired,
            "next_expected": (
                "watch bound_via.none — every one of those is a clarify answer that "
                "opened a fresh thread instead of returning to the question"
            ),
        }
    )
    _print_stage42(data, args=args, default_output="json")
    return 0


def _cmd_mission_chat_turn_resolve(args) -> int:
    """The argv door; the decision is ``agent_runtime.chat_verbs.turn_resolve``."""
    from agent_runtime.chat_verbs.turn_resolve import resolve_chat_turn

    data = resolve_chat_turn(
        session_id=getattr(args, "session_id", None),
        client_message_id=getattr(args, "client_message_id", None),
        turn_id=getattr(args, "turn_id", None),
        action=getattr(args, "action", None),
        persona_instance_id=getattr(args, "persona_instance_id", None),
        reason=getattr(args, "reason", None),
    )
    if "resolution" not in data:
        print(emit_json(data) if args.json else data["error"])
        return 2
    print(emit_json(data) if args.json else "abandoned ambiguous chat turn")
    return 0 if data["ok"] else 2
