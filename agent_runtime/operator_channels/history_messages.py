"""A curated history row -> a conversation message.

``_conversation_history_message`` is one :class:`HistoryMessage`, read as its
phases: ``gates`` (text, role, redaction) -> ``marker`` (a terminal turn marker
renders as its own presentation) -> ``shape`` (:data:`HISTORY_ROW_SHAPES`, the
first rule that matches the row's role and typed kind) -> ``message`` ->
``annotate`` (runtime context, the delivery block, the relay sender's name, the
turn identity, the ordering key, the run budget).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..persona_chat_history.vocabulary import (
    PERSONA_HARNESS_DELIVERY_KIND,
    PERSONA_PRE_TRACE_ACK_KIND,
    PERSONA_RELAYED_MESSAGE_KIND,
    MessageRole,
    canonical_persona_chat_turn_id,
)
from ..relay_policy import HARNESS_DELIVERY_UNKNOWN_STATE
from ..run_budget import ACCOUNTING_KEY as RUN_BUDGET_ACCOUNTING_KEY
from ..serde import safe_assignment_text, safe_assignment_token

from .vocabulary import _TERMINAL_TURN_MARKER_PRESENTATION, _safe_conversation_text

__layer__ = "policy"


# S47 removed ``_conversation_goal_input`` (the synthetic "Goal:" operator
# message) with the ``task`` parameter that was its only input.

#: The redaction statuses that hide a row's text behind the boundary notice.
HIDDEN_REDACTION_STATUSES = frozenset({"redacted", "unsafe"})
HIDDEN_TEXT = "Message hidden by redaction boundary."

OPERATOR = str(MessageRole.OPERATOR)
AGENT = str(MessageRole.AGENT)
SYSTEM = str(MessageRole.SYSTEM)


@dataclass(frozen=True)
class RowShape:
    """What a history row renders as: its typed kind and the actor it names."""

    kind: str
    actor_persona_id: str | None
    actor_instance_id: str | None


#: ``(row, persona_id, persona_instance_id) -> RowShape``.
ShapeBuilder = Callable[[dict[str, Any], str, "str | None"], RowShape]


def _harness_delivery_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    # A dispatch delivery is a role="operator" row the HARNESS forged into the
    # sender's own thread. Same shape as the relay case and the same reason for
    # keeping role="operator" (lane semantics; a consumer that ignores the typed
    # kind degrades to today's render) — but the actor is the runtime itself,
    # not an agent, so there is no sender persona to name and none is invented.
    return RowShape(PERSONA_HARNESS_DELIVERY_KIND, "harness", None)


def _relayed_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    # A relayed incoming message is a role="operator" row that persona_chat_history
    # tagged with the SENDING agent's identity (finish_reason marker). Attribute
    # it to that agent, but keep role="operator" so the lane semantics — and any
    # consumer that ignores the typed kind — degrade to today's operator render.
    return RowShape(
        PERSONA_RELAYED_MESSAGE_KIND,
        safe_assignment_text(row.get("relay_sender_persona_id"), limit=160) or "agent",
        _relay_sender_instance_id(row) or None,
    )


def _pre_trace_ack_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    # A canned pre-trace ack keeps its typed kind end-to-end so the Launcher
    # collapses/drops it structurally (never as a settled reply bubble ahead of
    # the real tool run), instead of matching the tool-specific ack prose.
    return RowShape(PERSONA_PRE_TRACE_ACK_KIND, persona_id, instance_id)


def _reply_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    return RowShape("reply", persona_id, instance_id)


def _operator_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    return RowShape("operator_message", "operator", None)


def _system_shape(row: dict[str, Any], persona_id: str, instance_id: str | None) -> RowShape:
    return RowShape("system_message", persona_id, instance_id)


#: ``(role, typed kind) -> RowShape``, matched first-hit in the order the
#: decision was always taken in. A row no rule matches is a system message.
HISTORY_ROW_SHAPES: tuple[tuple[Callable[[str, str], bool], ShapeBuilder], ...] = (
    (lambda role, kind: role == OPERATOR and kind == PERSONA_HARNESS_DELIVERY_KIND, _harness_delivery_shape),
    (lambda role, kind: role == OPERATOR and kind == PERSONA_RELAYED_MESSAGE_KIND, _relayed_shape),
    (lambda role, kind: role == AGENT and kind == PERSONA_PRE_TRACE_ACK_KIND, _pre_trace_ack_shape),
    (lambda role, kind: role == AGENT, _reply_shape),
    (lambda role, kind: role == OPERATOR, _operator_shape),
)


def history_row_shape(row: dict[str, Any], role: str, persona_id: str, instance_id: str | None) -> RowShape:
    kind = safe_assignment_token(row.get("kind")) or ""
    build = next((shape for matches, shape in HISTORY_ROW_SHAPES if matches(role, kind)), _system_shape)
    return build(row, persona_id, instance_id)


def _relay_sender_instance_id(row: dict[str, Any]) -> str:
    return safe_assignment_text(row.get("relay_sender_instance_id"), limit=160)


def _conversation_history_message(
    row: dict[str, Any],
    *,
    channel_id: str,
    index: int,
    persona_id: str,
    persona_instance_id: str | None,
    display_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    return HistoryMessage(
        row,
        channel_id=channel_id,
        index=index,
        persona_id=persona_id,
        persona_instance_id=persona_instance_id,
        display_names=display_names,
    ).build()


class HistoryMessage:
    """One curated history row, projected. Fields are what the phases share."""

    def __init__(
        self,
        row: dict[str, Any],
        *,
        channel_id: str,
        index: int,
        persona_id: str,
        persona_instance_id: str | None,
        display_names: dict[str, str] | None,
    ) -> None:
        self.row = row
        self.channel_id = channel_id
        self.index = index
        self.persona_id = persona_id
        self.persona_instance_id = persona_instance_id
        self.display_names = display_names
        self.text = ""
        self.role = SYSTEM
        self.redaction_status = "safe"
        self.client_message_id = safe_assignment_text(row.get("client_message_id"), limit=240)

    def build(self) -> dict[str, Any] | None:
        if not self.gates():
            return None
        marker = self.marker()
        if marker is not None:
            return marker
        shape = history_row_shape(self.row, self.role, self.persona_id, self.persona_instance_id)
        message = self.message(shape)
        self.annotate(message, shape)
        return message

    def gates(self) -> bool:
        text = _safe_conversation_text(self.row.get("text"), limit=20000)
        if not text:
            return False
        # The wire roles map through the ONE table (``persona_chat_history``'s
        # ``WIRE_ROLES``); a role it does not know renders as a system message.
        wire_role = safe_assignment_token(self.row.get("role")) or SYSTEM
        self.role = str(MessageRole.from_wire(wire_role) or MessageRole.SYSTEM)
        self.redaction_status = safe_assignment_token(self.row.get("redaction_status")) or "safe"
        self.text = HIDDEN_TEXT if self.redaction_status in HIDDEN_REDACTION_STATUSES else text
        return True

    def _base(self) -> dict[str, Any]:
        return {
            "id": safe_assignment_text(self.row.get("id"), limit=180) or f"{self.channel_id}:history:{self.index}",
            "seq": 0,
            "timestamp": self.row.get("timestamp"),
        }

    def _redaction(self) -> str:
        return "redacted" if self.redaction_status in HIDDEN_REDACTION_STATUSES else "safe"

    def marker(self) -> dict[str, Any] | None:
        """A terminal turn marker synthesized by persona_chat_history, or ``None``.

        For a turn that ended without a recorded reply — killed
        (``turn_interrupted``) or landed at the wall-budget checkpoint
        (``budget_exhausted``). Keep the typed kind + turn identity so the
        Launcher renders the right affordance (retry vs. graceful checkpoint)
        and so the still-"running" tool rows of the same turn get settled.
        """

        marker_kind = safe_assignment_token(self.row.get("kind")) or ""
        presentation = _TERMINAL_TURN_MARKER_PRESENTATION.get(marker_kind)
        if presentation is None:
            return None
        turn_id = canonical_persona_chat_turn_id(self.client_message_id) or safe_assignment_token(
            self.row.get("turn_id")
        )
        message = {
            **self._base(),
            "actor_persona_id": self.persona_id,
            "actor_instance_id": self.persona_instance_id,
            "role": SYSTEM,
            "kind": marker_kind,
            "status": presentation["status"],
            "display_title": presentation["display_title"],
            "display_text": self.text,
            "redaction_status": self._redaction(),
            "refs": {"source": "persona_chat_history"},
        }
        settled_state = safe_assignment_token(self.row.get("settled_state"))
        if settled_state:
            message["settled_state"] = settled_state
        if self.client_message_id:
            message["client_message_id"] = self.client_message_id
        if turn_id:
            message["turn_id"] = turn_id
        _carry_turn_seq(message, self.row)
        _carry_history_run_budget(message, self.row)
        return message

    def message(self, shape: RowShape) -> dict[str, Any]:
        return {
            **self._base(),
            "actor_persona_id": shape.actor_persona_id,
            "actor_instance_id": shape.actor_instance_id,
            "role": self.role,
            "kind": shape.kind,
            "status": "delivered",
            "display_title": "",
            "display_text": self.text,
            "redaction_status": self._redaction(),
            "refs": {"source": "persona_chat_history"},
        }

    def annotate(self, message: dict[str, Any], shape: RowShape) -> None:
        row = self.row
        runtime_context = row.get("runtime_context")
        if self.role == OPERATOR and isinstance(runtime_context, dict):
            message["runtime_context"] = {
                key: value
                for key in ("context_id", "revision", "delivery")
                if (value := safe_assignment_text(runtime_context.get(key), limit=200))
            }
        if shape.kind == PERSONA_HARNESS_DELIVERY_KIND:
            message["delivery"] = _delivery_block(row)
        # Name the sending agent ONLY when its instance id resolves in the roster —
        # never fabricate a name for an instance we cannot see.
        sender = _relay_sender_instance_id(row) if shape.kind == PERSONA_RELAYED_MESSAGE_KIND else ""
        resolved_name = (self.display_names or {}).get(sender) if sender else None
        if resolved_name:
            message["actor_display_name"] = resolved_name
        self._turn_identity(message)
        # C8 ordering key: the history projection stamps the intra-turn position
        # (operator opens, terminal reply/interrupt closes); carry it through this
        # contract unchanged so every representation sorts on the same key.
        _carry_turn_seq(message, row)
        _carry_history_run_budget(message, row)

    def _turn_identity(self, message: dict[str, Any]) -> None:
        if not self.client_message_id:
            return
        if self.role == OPERATOR:
            message["client_message_id"] = self.client_message_id
            message["turn_id"] = canonical_persona_chat_turn_id(self.client_message_id)
        elif self.role == AGENT:
            message["turn_id"] = canonical_persona_chat_turn_id(
                self.client_message_id
            ) or safe_assignment_token(self.row.get("turn_id"))
            message["client_message_id"] = self.client_message_id


def _delivery_block(row: dict[str, Any]) -> dict[str, Any]:
    """The delivery's own facts, as a typed sub-block rather than loose keys.

    A consumer needs ALL THREE to act, and a field that can go missing
    independently of the id it belongs to eventually gets read against the
    wrong dispatch. `notify_operator` and `state` are always present — "the
    agent did not flag this" and "nobody knows how it ended" are answers, not
    absences.

    `state` is why this block is not just an id: ``pending_deliveries`` selects
    ``state != running``, so a FAILED dispatch is delivered exactly like a
    successful one and only the prose body says which. A consumer without this
    would have to read that prose to phrase its own notification, which is the
    sentence-matching the typed marker exists to retire.
    """

    return {
        "dispatch_id": safe_assignment_text(row.get("delivery_dispatch_id"), limit=200) or "",
        "notify_operator": bool(row.get("delivery_notify_operator")),
        "state": safe_assignment_token(row.get("delivery_state")) or HARNESS_DELIVERY_UNKNOWN_STATE,
    }


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
