"""A curated history row -> a conversation message."""

from __future__ import annotations

from typing import Any

from ..persona_chat_history.vocabulary import (
    PERSONA_HARNESS_DELIVERY_KIND,
    PERSONA_PRE_TRACE_ACK_KIND,
    PERSONA_RELAYED_MESSAGE_KIND,
    canonical_persona_chat_turn_id,
)
from ..relay_policy import HARNESS_DELIVERY_UNKNOWN_STATE
from ..run_budget import ACCOUNTING_KEY as RUN_BUDGET_ACCOUNTING_KEY
from ..serde import safe_assignment_text, safe_assignment_token

from .vocabulary import _TERMINAL_TURN_MARKER_PRESENTATION, _safe_conversation_text

__layer__ = "policy"


# S47 removed ``_conversation_goal_input`` (the synthetic "Goal:" operator
# message) with the ``task`` parameter that was its only input.


def _conversation_history_message(
    row: dict[str, Any],
    *,
    channel_id: str,
    index: int,
    persona_id: str,
    persona_instance_id: str | None,
    display_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    text = _safe_conversation_text(row.get("text"), limit=20000)
    if not text:
        return None
    role = safe_assignment_token(row.get("role")) or "system"
    if role == "user":
        role = "operator"
    if role == "assistant":
        role = "agent"
    if role not in {"operator", "agent", "system", "proof", "blocker"}:
        role = "system"
    redaction_status = safe_assignment_token(row.get("redaction_status")) or "safe"
    if redaction_status in {"redacted", "unsafe"}:
        text = "Message hidden by redaction boundary."
    client_message_id = safe_assignment_text(row.get("client_message_id"), limit=240)
    marker_kind = safe_assignment_token(row.get("kind")) or ""
    presentation = _TERMINAL_TURN_MARKER_PRESENTATION.get(marker_kind)
    if presentation is not None:
        # Terminal turn-status marker synthesized by persona_chat_history for a
        # turn that ended without a recorded reply — killed
        # (``turn_interrupted``) or landed at the wall-budget checkpoint
        # (``budget_exhausted``). Keep the typed kind + turn identity so the
        # Launcher renders the right affordance (retry vs. graceful checkpoint)
        # and so the still-"running" tool rows of the same turn get settled.
        turn_id = canonical_persona_chat_turn_id(
            client_message_id
        ) or safe_assignment_token(row.get("turn_id"))
        message = {
            "id": safe_assignment_text(row.get("id"), limit=180) or f"{channel_id}:history:{index}",
            "seq": 0,
            "timestamp": row.get("timestamp"),
            "actor_persona_id": persona_id,
            "actor_instance_id": persona_instance_id,
            "role": "system",
            "kind": marker_kind,
            "status": presentation["status"],
            "display_title": presentation["display_title"],
            "display_text": text,
            "redaction_status": "redacted" if redaction_status in {"redacted", "unsafe"} else "safe",
            "refs": {"source": "persona_chat_history"},
        }
        settled_state = safe_assignment_token(row.get("settled_state"))
        if settled_state:
            message["settled_state"] = settled_state
        if client_message_id:
            message["client_message_id"] = client_message_id
        if turn_id:
            message["turn_id"] = turn_id
        _carry_turn_seq(message, row)
        _carry_history_run_budget(message, row)
        return message
    # A canned pre-trace ack keeps its typed kind end-to-end so the Launcher
    # collapses/drops it structurally (never as a settled reply bubble ahead of
    # the real tool run), instead of matching the tool-specific ack prose.
    is_pre_trace_ack = (
        role == "agent"
        and safe_assignment_token(row.get("kind")) == PERSONA_PRE_TRACE_ACK_KIND
    )
    # A relayed incoming message is a role="operator" row that persona_chat_history
    # tagged with the SENDING agent's identity (finish_reason marker). Attribute
    # it to that agent, but keep role="operator" so the lane semantics — and any
    # consumer that ignores the typed kind — degrade to today's operator render.
    is_relayed_message = (
        role == "operator"
        and safe_assignment_token(row.get("kind")) == PERSONA_RELAYED_MESSAGE_KIND
    )
    relay_sender_instance_id = (
        safe_assignment_text(row.get("relay_sender_instance_id"), limit=160)
        if is_relayed_message
        else None
    )
    # A dispatch delivery is a role="operator" row the HARNESS forged into the
    # sender's own thread. Same shape as the relay case and the same reason for
    # keeping role="operator" (lane semantics; a consumer that ignores the typed
    # kind degrades to today's render) — but the actor is the runtime itself,
    # not an agent, so there is no sender persona to name and none is invented.
    is_harness_delivery = (
        role == "operator"
        and safe_assignment_token(row.get("kind")) == PERSONA_HARNESS_DELIVERY_KIND
    )
    if is_harness_delivery:
        default_kind = PERSONA_HARNESS_DELIVERY_KIND
        actor_persona_id = "harness"
        actor_instance_id = None
    elif is_relayed_message:
        default_kind = PERSONA_RELAYED_MESSAGE_KIND
        actor_persona_id = (
            safe_assignment_text(row.get("relay_sender_persona_id"), limit=160) or "agent"
        )
        actor_instance_id = relay_sender_instance_id or None
    else:
        if role == "agent":
            default_kind = PERSONA_PRE_TRACE_ACK_KIND if is_pre_trace_ack else "reply"
        elif role == "operator":
            default_kind = "operator_message"
        else:
            default_kind = "system_message"
        actor_persona_id = "operator" if role == "operator" else persona_id
        actor_instance_id = None if role == "operator" else persona_instance_id
    message = {
        "id": safe_assignment_text(row.get("id"), limit=180) or f"{channel_id}:history:{index}",
        "seq": 0,
        "timestamp": row.get("timestamp"),
        "actor_persona_id": actor_persona_id,
        "actor_instance_id": actor_instance_id,
        "role": role,
        "kind": default_kind,
        "status": "delivered",
        "display_title": "",
        "display_text": text,
        "redaction_status": "redacted" if redaction_status in {"redacted", "unsafe"} else "safe",
        "refs": {"source": "persona_chat_history"},
    }
    runtime_context = row.get("runtime_context")
    if role == "operator" and isinstance(runtime_context, dict):
        message["runtime_context"] = {
            key: value
            for key in ("context_id", "revision", "delivery")
            if (value := safe_assignment_text(runtime_context.get(key), limit=200))
        }
    # The delivery's own facts, as a typed sub-block rather than loose keys: a
    # consumer needs ALL THREE to act, and a field that can go missing
    # independently of the id it belongs to eventually gets read against the
    # wrong dispatch. `notify_operator` and `state` are always present — "the
    # agent did not flag this" and "nobody knows how it ended" are answers, not
    # absences.
    #
    # `state` is why this block is not just an id: ``pending_deliveries``
    # selects ``state != running``, so a FAILED dispatch is delivered exactly
    # like a successful one and only the prose body says which. A consumer
    # without this would have to read that prose to phrase its own notification,
    # which is the sentence-matching the typed marker exists to retire.
    if is_harness_delivery:
        message["delivery"] = {
            "dispatch_id": safe_assignment_text(
                row.get("delivery_dispatch_id"), limit=200
            )
            or "",
            "notify_operator": bool(row.get("delivery_notify_operator")),
            "state": safe_assignment_token(row.get("delivery_state"))
            or HARNESS_DELIVERY_UNKNOWN_STATE,
        }
    # Name the sending agent ONLY when its instance id resolves in the roster —
    # never fabricate a name for an instance we cannot see.
    if is_relayed_message and relay_sender_instance_id:
        resolved_name = (display_names or {}).get(relay_sender_instance_id)
        if resolved_name:
            message["actor_display_name"] = resolved_name
    if role == "operator" and client_message_id:
        message["client_message_id"] = client_message_id
        message["turn_id"] = canonical_persona_chat_turn_id(client_message_id)
    if role == "agent" and client_message_id:
        message["turn_id"] = canonical_persona_chat_turn_id(
            client_message_id
        ) or safe_assignment_token(row.get("turn_id"))
        message["client_message_id"] = client_message_id
    # C8 ordering key: the history projection stamps the intra-turn position
    # (operator opens, terminal reply/interrupt closes); carry it through this
    # contract unchanged so every representation sorts on the same key.
    _carry_turn_seq(message, row)
    _carry_history_run_budget(message, row)
    return message


def _carry_turn_seq(message: dict[str, Any], row: dict[str, Any]) -> None:
    turn_seq = row.get("turn_seq")
    if isinstance(turn_seq, int) and not isinstance(turn_seq, bool):
        message["turn_seq"] = turn_seq


def _carry_history_run_budget(message: dict[str, Any], row: dict[str, Any]) -> None:
    # The turn's run_budget accounting block, decorated onto the history row by
    # persona_chat_history._carry_run_budget. Verbatim and absence-preserving:
    # the store already bounded it through run_budget.safe_accounting_block,
    # and a row without the block projects without the key so "nobody
    # accounted this turn" stays distinguishable from "nothing bounded it".
    block = row.get(RUN_BUDGET_ACCOUNTING_KEY)
    if isinstance(block, dict) and block:
        message[RUN_BUDGET_ACCOUNTING_KEY] = block
