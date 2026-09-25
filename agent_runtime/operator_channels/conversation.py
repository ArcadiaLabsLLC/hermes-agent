"""One channel's conversation contract: projection, terminal-tool settling, order, dedupe, cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ..persona_chat_history.vocabulary import (
    canonical_persona_chat_turn_id,
    logical_persona_chat_client_message_id,
)
from ..serde import safe_assignment_text, safe_assignment_token
from ..transcript_order import order_transcript_rows

from .history_messages import AGENT, _conversation_history_message
from .trace_messages import _conversation_tool_call_messages, _conversation_trace_message
from .vocabulary import (
    TOOL_CALL_RUNNING,
    OPERATOR_CONVERSATION_SCHEMA_VERSION,
    _CONVERSATION_MESSAGE_CAP,
    _CONVERSATION_TRIMMABLE_KINDS,
    _SETTLED_TOOL_CALL_STATUS,
    _TERMINAL_TURN_MARKER_PRESENTATION,
    _conversation_message_sort_key,
)

__layer__ = "policy"


def _turn_identity_dropped(entries: list[Any], messages: list[Any]) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if safe_assignment_token(message.get("kind")) not in {"tool_call", "thinking_summary"}:
            continue
        refs = message.get("refs")
        if not isinstance(refs, dict) or refs.get("source") != "persona_chat_trace":
            continue
        if safe_assignment_text(message.get("turn_id"), limit=160):
            continue
        timestamp = safe_assignment_text(message.get("timestamp"), limit=200)
        tool_name = safe_assignment_text(refs.get("tool_name"), limit=160)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if safe_assignment_text(entry.get("ts"), limit=200) != timestamp:
                continue
            if tool_name and safe_assignment_text(entry.get("tool_name"), limit=160) != tool_name:
                continue
            if safe_assignment_text(entry.get("turn_id"), limit=160):
                return True
            break
    return False


def _turn_identity_mismatched(messages: list[Any]) -> bool:
    """Detect a projector regression without relying on reply body matching."""

    for message in messages:
        if not isinstance(message, dict):
            continue
        if safe_assignment_token(message.get("role")) != AGENT:
            continue
        client_message_id = safe_assignment_text(
            message.get("client_message_id"), limit=240
        )
        expected_turn_id = canonical_persona_chat_turn_id(client_message_id)
        if (
            not expected_turn_id
            or client_message_id
            == logical_persona_chat_client_message_id(client_message_id)
        ):
            continue
        actual_turn_id = safe_assignment_token(message.get("turn_id"))
        if actual_turn_id != expected_turn_id:
            return True
    return False


def _conversation_contract(
    *,
    channel_id: str,
    persona_id: str,
    persona_instance_id: str | None,
    session_id: str | None,
    task_id: str | None,
    goal_id: str | None,
    title: str,
    state: str | None,
    history: dict[str, Any] | None,
    trace: dict[str, Any] | None,
    accountant: Any = None,
    display_names: dict[str, str] | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
) -> dict[str, Any]:
    # S47: the leading synthetic "Goal:" input message went with the ``task``
    # parameter — no caller could ever supply a task to mint it from.
    messages: list[dict[str, Any]] = []
    for index, row in enumerate(list((history or {}).get("messages") or [])):
        if isinstance(row, dict):
            message = _conversation_history_message(
                row,
                channel_id=channel_id,
                index=index,
                persona_id=persona_id,
                persona_instance_id=persona_instance_id,
                display_names=display_names,
            )
            if message is not None:
                messages.append(message)
    for index, entry in enumerate(list((trace or {}).get("entries") or [])):
        if isinstance(entry, dict):
            message = _conversation_trace_message(
                entry,
                channel_id=channel_id,
                index=index,
                persona_id=persona_id,
                persona_instance_id=persona_instance_id,
            )
            if message is not None:
                messages.append(message)
    messages.extend(
        _conversation_tool_call_messages(
            list((trace or {}).get("entries") or []),
            channel_id=channel_id,
            persona_id=persona_id,
            persona_instance_id=persona_instance_id,
            accountant=accountant,
        )
    )

    _settle_terminal_tool_calls(messages, history=history)

    messages = _order_conversation_messages(messages)
    messages = _dedupe_conversation_messages(messages)
    messages = _apply_conversation_cap(messages, channel_id=channel_id, accountant=accountant)
    for seq, message in enumerate(messages, start=1):
        message["seq"] = seq

    # "incomplete" is a contract breach: source rows existed but nothing
    # projected. A brand-new chat with no sources at all is simply "empty" —
    # it must NOT surface an intervention row in Mission Control.
    had_sources = bool(
        (history or {}).get("messages")
        or (trace or {}).get("entries")
    )
    if messages:
        status = "complete"
    elif had_sources:
        status = "incomplete"
    else:
        status = "empty"
    reason = None
    if status == "incomplete":
        reason = "No canonical conversation messages were projected for this operator channel."
    return {
        "schema_version": OPERATOR_CONVERSATION_SCHEMA_VERSION,
        "thread_id": channel_id,
        "goal_id": goal_id,
        "task_id": task_id,
        "owner_persona_id": persona_id,
        "persona_instance_id": persona_instance_id,
        "session_id": session_id,
        "root_thread_id": root_thread_id or channel_id,
        "parent_thread_id": parent_thread_id,
        "title": title,
        "state": state or "unknown",
        "updated_at": _latest_message_timestamp(messages) or (history or {}).get("updated_at"),
        "status": status,
        "incomplete_reason": reason,
        "messages": messages,
    }


def _settle_terminal_tool_calls(
    messages: list[dict[str, Any]],
    *,
    history: dict[str, Any] | None,
) -> None:
    """Settle still-``running`` tool_call rows of TERMINALLY-ended turns.

    A turn that ends mid-flight — killed (``turn_interrupted``) or landed at the
    wall-budget checkpoint (``budget_exhausted``) — leaves ``tool_started``
    trace entries with no finish row, so the paired tool_call projects
    ``running`` forever. The turn store's terminal marker is the truth that
    those calls will never finish; settle them at the contract source so every
    consumer stops rendering a live spinner.

    This keyed on ``turn_interrupted`` ALONE until 2026-07-26, which is exactly
    why a wall-budget turn spun in the cockpit after it was over: a second
    terminal state existed and only one marker was consumed. The recognised set
    is now driven by ``_TERMINAL_TURN_MARKER_PRESENTATION``, so a new terminal
    marker settles its tools by construction.

    Terminal turn ids come from the history SOURCE rows, not the projected
    messages, so a capped/deduped marker still settles its tools. The settled
    status is uniform (``interrupted`` — the call was cut off); ``settled_reason``
    carries WHICH terminal state ended the turn, typed, on both the message and
    its tool payload.
    """

    settled_reason_by_turn: dict[str, str] = {}
    for row in (history or {}).get("messages") or []:
        if not isinstance(row, dict):
            continue
        kind = safe_assignment_token(row.get("kind"))
        if kind not in _TERMINAL_TURN_MARKER_PRESENTATION:
            continue
        turn_id = safe_assignment_token(row.get("turn_id")) or safe_assignment_token(
            row.get("client_message_id")
        )
        if not turn_id:
            continue
        # The turn-store state the marker settled at, with the marker kind as
        # the fallback for a pre-``settled_state`` row (archive-never-delete).
        settled_reason_by_turn[turn_id] = (
            safe_assignment_token(row.get("settled_state")) or kind
        )
    if not settled_reason_by_turn:
        return
    for message in messages:
        if message.get("kind") != "tool_call" or message.get("status") != TOOL_CALL_RUNNING:
            continue
        reason = settled_reason_by_turn.get(
            safe_assignment_token(message.get("turn_id")) or ""
        )
        if reason is None:
            continue
        message["status"] = _SETTLED_TOOL_CALL_STATUS
        message["settled_reason"] = reason
        tool = message.get("tool")
        if isinstance(tool, dict):
            tool["status"] = _SETTLED_TOOL_CALL_STATUS
            tool["settled_reason"] = reason


def _apply_conversation_cap(
    messages: list[dict[str, Any]],
    *,
    channel_id: str,
    accountant: Any = None,
) -> list[dict[str, Any]]:
    """Bound the per-channel message count without dropping load-bearing rows.

    Flow kinds trim oldest-first; goal_input / operator / reply / proof /
    blocker / handoff / final always survive. A ``turns_collapsed`` marker
    replaces the trimmed span so the launcher can render an honest divider.
    """

    if len(messages) <= _CONVERSATION_MESSAGE_CAP:
        return messages
    protected = [m for m in messages if m.get("kind") not in _CONVERSATION_TRIMMABLE_KINDS]
    trimmable = [m for m in messages if m.get("kind") in _CONVERSATION_TRIMMABLE_KINDS]
    budget = max(_CONVERSATION_MESSAGE_CAP - len(protected) - 1, 0)
    dropped = trimmable[: len(trimmable) - budget] if budget else trimmable
    kept = trimmable[len(trimmable) - budget :] if budget else []
    if not dropped:
        return messages
    marker = {
        "id": f"{channel_id}:turns_collapsed",
        "seq": 0,
        "timestamp": dropped[-1].get("timestamp"),
        "actor_persona_id": "system",
        "actor_instance_id": None,
        "role": "system",
        "kind": "turns_collapsed",
        "status": "delivered",
        "display_title": "Earlier activity collapsed",
        "display_text": f"Earlier activity collapsed ({len(dropped)} messages). Newest turns are shown.",
        "redaction_status": "safe",
        "refs": {"collapsed_count": len(dropped)},
    }
    if accountant is not None:
        # Deliberate bound: the channel keeps the newest turns and the trimmed
        # span is disclosed in-band by the ``turns_collapsed`` marker above.
        accountant.drop(
            "turn_cap_trimmed",
            count=len(dropped),
            entity_id=channel_id,
            by_design=True,
        )
        accountant.mark_truncated()
    return _order_conversation_messages([*protected, marker, *kept])


def _order_conversation_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """C8: order the conversation by the ONE turn-scoped key.

    Turn-anchored rows (anchor = token(turn_id | logical client_message_id), position =
    ``turn_seq``) sort inside their turn by the stamped position — operator row
    first, content band between, terminal reply/interrupt last — immune to the
    two-clock skew between SessionDB stamps and trace ``ts`` values (F17). Rows
    without the key (pre-C8 history, goal_input, warnings) keep the pre-C8
    timestamp fallback, which also anchors where each turn sits among them.
    """

    return order_transcript_rows(
        messages,
        anchor=lambda message: (
            safe_assignment_token(message.get("turn_id"))
            or canonical_persona_chat_turn_id(message.get("client_message_id"))
        ),
        turn_seq=lambda message: message.get("turn_seq")
        if isinstance(message.get("turn_seq"), int)
        and not isinstance(message.get("turn_seq"), bool)
        else None,
        fallback_key=lambda message, _index: _conversation_message_sort_key(message),
    )


@dataclass
class DedupeState:
    """What the dedupe pass has seen, and the two text sets it reads by kind."""

    flow_texts: set[Any]
    reply_texts: set[str]
    seen_assignments: set[str] = field(default_factory=set)
    seen_thinking_texts: set[Any] = field(default_factory=set)

    @classmethod
    def of(cls, messages: list[dict[str, Any]]) -> "DedupeState":
        return cls(
            # A run's reasoning often lands twice: once as the run-summary flow
            # message (thinking_summary/turn) and once as a trace progress row
            # (agent_update). The flow message wins; the duplicate progress row
            # is curated out.
            flow_texts={
                message.get("display_text")
                for message in messages
                if message.get("kind") in DEDUPE_FLOW_KINDS and message.get("display_text")
            },
            # The model's final text segment is often captured as a trailing
            # "thinking" step whose text IS the reply verbatim. Rendering both
            # paints the reply twice (an untimestamped Thinking bubble above the
            # real one) — the reply wins, the echo is curated out.
            reply_texts={
                str(message.get("display_text") or "").strip()
                for message in messages
                if message.get("kind") == "reply" and message.get("display_text")
            },
        )


#: The flow kinds whose text an ``agent_update`` progress row duplicates.
DEDUPE_FLOW_KINDS = frozenset({"thinking_summary", "turn"})


def _drop_repeated_subagent_prompt(message: dict[str, Any], state: DedupeState) -> bool:
    refs = message.get("refs")
    assignment_id = (
        safe_assignment_text(refs.get("assignment_id"), limit=160) if isinstance(refs, dict) else None
    )
    if not assignment_id or message.get("display_title") != "Subagent prompt":
        return False
    if assignment_id in state.seen_assignments:
        return True
    state.seen_assignments.add(assignment_id)
    return False


def _drop_flow_echo(message: dict[str, Any], state: DedupeState) -> bool:
    return message.get("display_text") in state.flow_texts


def _drop_thinking_repeat(message: dict[str, Any], state: DedupeState) -> bool:
    # Per-step trace thinking and the per-run summary can carry the same text
    # (the final reasoning step often IS the decision rationale). Keep the first
    # occurrence in timeline order; drop later repeats — and any that echo a
    # reply.
    text = message.get("display_text")
    if text and str(text).strip() in state.reply_texts:
        return True
    if text and text in state.seen_thinking_texts:
        return True
    if text:
        state.seen_thinking_texts.add(text)
    return False


#: A message's kind -> the rule that decides whether it is a duplicate. A kind
#: with no rule is always kept.
DEDUPE_RULES: Mapping[str, Callable[[dict[str, Any], DedupeState], bool]] = MappingProxyType(
    {
        "handoff": _drop_repeated_subagent_prompt,
        "agent_update": _drop_flow_echo,
        "thinking_summary": _drop_thinking_repeat,
    }
)


def _dedupe_conversation_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state = DedupeState.of(messages)
    deduped: list[dict[str, Any]] = []
    for message in messages:
        rule = DEDUPE_RULES.get(message.get("kind"))
        if rule is not None and rule(message, state):
            continue
        deduped.append(message)
    return deduped


def _latest_message_timestamp(messages: list[dict[str, Any]]) -> Any:
    dated = [message.get("timestamp") for message in messages if message.get("timestamp")]
    return dated[-1] if dated else None


# S47 removed ``_task_time`` — the conversation's ``updated_at`` fallback of
# last resort, reachable only through a task no caller could supply.
