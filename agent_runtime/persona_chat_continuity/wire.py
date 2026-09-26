"""THE persona-chat wire boundary: what the model receives on this lane, and its accounting."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ..serde import safe_assignment_text

from .bounds import BOUND_PART_TOOL_ARGUMENTS, CONTENT_BOUND_PARTS, ContentBoundNote, _MAX_ARGUMENTS, _bounded_free_text, bound_composed_user_content

__layer__ = "policy"

logger = logging.getLogger(__name__)


#: Name of the boundary, for logs and typed drift rows. One spelling, so a
#: search for "who decided what the model sees on this lane" lands in one place.
WIRE_BOUNDARY = "persona_chat.native_wire_row"

#: The provider wire's message roles — a BOUNDARY vocabulary (the OpenAI message
#: shape this lane submits), read by name at the boundary checks below. Not
#: ``persona_chat_history``'s ``WIRE_ROLES``, which maps roles onto the
#: projection's ``MessageRole``: that is a different question.
WIRE_ROLE_SYSTEM = "system"
WIRE_ROLE_USER = "user"
WIRE_ROLE_ASSISTANT = "assistant"
WIRE_ROLE_TOOL = "tool"
WIRE_ROLE_NAMES = frozenset({WIRE_ROLE_SYSTEM, WIRE_ROLE_USER, WIRE_ROLE_ASSISTANT, WIRE_ROLE_TOOL})


@dataclass(frozen=True, slots=True)
class WireBoundaryRow:
    """What the persona-chat boundary put ON THE WIRE, and what it cost.

    ``row`` is the value the flush writes back into the LIVE actor's message
    list, so it is what the next provider call submits — not merely what gets
    persisted. The remaining fields exist so that claim is checkable rather than
    asserted in a comment.
    """

    row: dict[str, Any]
    notes: tuple[ContentBoundNote, ...] = ()
    #: Length of the content handed to the boundary, before redaction.
    submitted_chars: int = 0
    #: Length after redaction — the input the BOUND was actually applied to.
    #: Redaction is a separate, intended transform; separating the two keeps a
    #: redacted secret from masquerading as an unaccounted bound loss.
    redacted_chars: int = 0
    #: Length of what goes to the model.
    wire_chars: int = 0

    @property
    def bounded(self) -> bool:
        return bool(self.notes)

    @property
    def accounted_loss(self) -> int:
        """Characters the notes explain, counting only the CONTENT parts.

        Tool-call arguments are bounded and noted too, but they live in a
        different field of the row and are NOT part of the content arithmetic.
        Summing them here would let an argument truncation cancel out a real
        content residue and drive :attr:`unaccounted_loss` to zero — a check
        that hides the thing it exists to find.
        """

        return sum(
            max(0, note.original_chars - note.bounded_chars)
            for note in self.notes
            if note.part in CONTENT_BOUND_PARTS
        )

    @property
    def argument_loss(self) -> int:
        """Characters removed from tool-call argument blobs. Reported, not netted."""

        return sum(
            max(0, note.original_chars - note.bounded_chars)
            for note in self.notes
            if note.part == BOUND_PART_TOOL_ARGUMENTS
        )

    @property
    def unaccounted_loss(self) -> int:
        """Characters that left between submission and the wire with NOTHING naming them.

        THE INVARIANT. Every character the boundary removes must be explained by
        a typed note or by redaction. A non-zero residue means content is
        reaching the model in a shape no receipt describes — the 2026-08-09
        class, where a bound that read as persistence-only silently governed the
        prompt and the receipt could only report it after the fact.
        """

        return max(0, self.redacted_chars - self.wire_chars - self.accounted_loss)

    @property
    def holds(self) -> bool:
        return self.unaccounted_loss == 0

    def drift_row(self) -> dict[str, Any] | None:
        """The fail-loud typed row, or ``None`` when the invariant holds.

        A ROW rather than a raised assertion, deliberately — see
        :func:`record_wire_boundary_drift`.
        """

        if self.holds:
            return None
        return {
            "boundary": WIRE_BOUNDARY,
            "role": str(self.row.get("role") or ""),
            "submitted_chars": self.submitted_chars,
            "redacted_chars": self.redacted_chars,
            "wire_chars": self.wire_chars,
            "accounted_loss": self.accounted_loss,
            "argument_loss": self.argument_loss,
            "unaccounted_loss": self.unaccounted_loss,
            "notes": [
                {
                    "part": note.part,
                    "action": note.action,
                    "original_chars": note.original_chars,
                    "bounded_chars": note.bounded_chars,
                    "limit": note.limit,
                }
                for note in self.notes
            ],
        }


def record_wire_boundary_drift(bound: WireBoundaryRow) -> dict[str, Any] | None:
    """Report an unaccounted wire loss loudly, and keep the turn alive.

    WHY A TYPED ROW AND NOT AN ASSERTION. This runs inside the crash-resilience
    persist, on the live agent turn loop, BEFORE the first provider call of the
    turn. Raising here would convert an accounting bug into a lost turn on a
    conversation that is otherwise fine — strictly worse than the drift being
    reported, and it would do so in the one place a user cannot retry cheaply.
    The hard equality assertion lives where it is free: the unit tests over the
    pure boundary, which is the seam the invariant actually belongs to.

    The row is also the honest shape for the check. The boundary is SUPPOSED to
    shorten content; the invariant is not "wire == submitted" but "every
    character of the difference is named". A bare assert could only express the
    former, which is why the previous receipt could report drift and never
    prevent it.
    """

    row = bound.drift_row()
    if row is None:
        return None
    logger.error(
        "persona chat wire boundary lost %d unaccounted chars on a %s row "
        "(submitted=%d redacted=%d wire=%d accounted=%d) — the model is being "
        "sent content no receipt describes",
        row["unaccounted_loss"],
        row["role"] or "?",
        row["submitted_chars"],
        row["redacted_chars"],
        row["wire_chars"],
        row["accounted_loss"],
    )
    return row


def native_wire_row(message: dict[str, Any]) -> WireBoundaryRow:
    """THE persona-chat wire boundary.

    Named for what it decides rather than where it is called from. The flush in
    ``run_agent`` writes this result back into the live actor's message list, so
    this function — not the provider call, not the composition step — is what
    settles the bytes the model receives on this lane. That coupling is the
    reason the module's bounds are wire bounds (see :data:`_MAX_CONTENT`), and
    it used to be recorded only in a comment at the call site.

    Tool structure and ordering identifiers survive, while raw/unbounded
    payloads and provider-specific residue do not. Applying this more than once
    is stable, which lets warm memory and cold persistence share the same
    boundary without representation drift.
    """

    role = str(message.get("role") or "").strip().lower()
    if role not in WIRE_ROLE_NAMES:
        role = WIRE_ROLE_ASSISTANT
    # Named `submitted`, not `raw`: the loop over `tool_calls` below rebinds
    # `raw` per call, and the two must not be the same name.
    submitted = message.get("content")
    # The operator user row is the ONE composed row on this lane — a join of
    # three parts with three different contracts — so it is bounded per part
    # (see :func:`bound_composed_user_content`). Every other role is opaque free
    # text and keeps the flat bound it always had — but now reports it.
    bounded = (
        bound_composed_user_content(submitted)
        if role == WIRE_ROLE_USER
        else _bounded_free_text(submitted)
    )
    content = bounded.text
    result: dict[str, Any] = {"role": role, "content": content}
    for key in (
        "tool_call_id",
        "tool_name",
        "finish_reason",
        "platform_message_id",
        "client_message_id",
        "turn_id",
        "root_chat_session_id",
    ):
        raw_value = message.get(key)
        if key == "platform_message_id" and raw_value is None:
            raw_value = message.get("message_id")
        value = safe_assignment_text(raw_value, limit=240)
        if value:
            result[key] = value
    notes: list[ContentBoundNote] = list(bounded.notes)
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        safe_calls: list[dict[str, Any]] = []
        for raw in calls[:64]:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            call_id = safe_assignment_text(raw.get("id"), limit=240)
            name = safe_assignment_text(function.get("name") or raw.get("name"), limit=240)
            if not call_id or not name:
                continue
            # Accounted for the same reason the row content is: this rides back
            # into the live actor and reaches the model.
            arguments = _bounded_free_text(
                function.get("arguments"),
                limit=_MAX_ARGUMENTS,
                part=BOUND_PART_TOOL_ARGUMENTS,
            )
            notes += arguments.notes
            safe_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments.text},
                }
            )
        if safe_calls:
            result["tool_calls"] = safe_calls
    return WireBoundaryRow(
        row=result,
        notes=tuple(notes),
        submitted_chars=len(submitted) if isinstance(submitted, str) else 0,
        redacted_chars=bounded.source_chars,
        wire_chars=len(content),
    )


def safe_native_message(message: dict[str, Any]) -> dict[str, Any]:
    """The boundary's row, for callers that do not need the accounting.

    Kept as the name every existing call site already uses; the accounting lives
    on :func:`native_wire_row`. Callers that write this result back into a LIVE
    message list — which makes it the wire, not merely the record — should use
    the typed form and report drift.
    """

    return native_wire_row(message).row


def safe_native_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    abandoned = {
        str(item.get("client_message_id"))
        for item in messages
        if isinstance(item, dict) and item.get("abandoned")
    }
    normalized = [
        safe_native_message(raw)
        for raw in messages
        if isinstance(raw, dict)
        and str(raw.get("client_message_id") or "") not in abandoned
    ]
    # Compression children contain the protected current turn as well as the
    # preserved parent transcript. Folding a multi-pass lineage can therefore
    # surface byte-identical copies of one logical user/reply row. Collapse
    # only rows that share the stable client/role/payload identity; distinct
    # compaction summaries and tool-call messages remain intact.
    deduped: list[dict[str, Any]] = []
    seen_logical_rows: set[tuple[str, str, str]] = set()
    for item in normalized:
        client_message_id = str(item.get("client_message_id") or "")
        if client_message_id:
            logical_client_id = re.sub(r":assistant:\d+$", "", client_message_id)
            payload = json.dumps(
                {
                    "content": item.get("content"),
                    "tool_calls": item.get("tool_calls"),
                    "tool_call_id": item.get("tool_call_id"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            key = (item["role"], logical_client_id, payload)
            if key in seen_logical_rows:
                continue
            seen_logical_rows.add(key)
        deduped.append(item)
    normalized = deduped
    available_results = {
        str(item.get("tool_call_id"))
        for item in normalized
        if item.get("role") == WIRE_ROLE_TOOL and item.get("tool_call_id")
    }
    safe: list[dict[str, Any]] = []
    live_tool_ids: set[str] = set()
    for item in normalized:
        if item["role"] == WIRE_ROLE_ASSISTANT:
            paired_calls = [
                call
                for call in item.get("tool_calls", [])
                if str(call.get("id") or "") in available_results
            ]
            if paired_calls:
                item["tool_calls"] = paired_calls
                live_tool_ids.update(str(call["id"]) for call in paired_calls)
            else:
                item.pop("tool_calls", None)
        if item["role"] == WIRE_ROLE_TOOL and item.get("tool_call_id") not in live_tool_ids:
            continue
        safe.append(item)
    return safe


def native_lineage_summary(session_db: Any, root_session_id: str) -> dict[str, Any]:
    """Resolve a root's current native tip and validated compression depth."""

    root = safe_assignment_text(root_session_id, limit=240)
    tip = session_db.resolve_resume_session_id(root)
    current = tip
    depth = 0
    seen: set[str] = set()
    while current and current != root:
        if current in seen:
            raise ValueError(f"cyclic persona chat lineage for {root}")
        seen.add(current)
        row = session_db.get_session(current)
        if not isinstance(row, dict):
            raise ValueError(f"missing persona chat lineage node {current}")
        parent = safe_assignment_text(row.get("parent_session_id"), limit=240)
        if not parent:
            raise ValueError(f"persona chat tip {tip} does not descend from {root}")
        current = parent
        depth += 1
    return {"active_session_id": tip, "continuation_depth": depth}


def native_history_revision(session_db: Any, root_session_id: str) -> str:
    tip = session_db.resolve_resume_session_id(root_session_id)
    history = session_db.get_messages_as_conversation(tip, include_ancestors=True)
    payload = json.dumps(safe_native_history(history or []), sort_keys=True, separators=(",", ":"))
    return f"{tip}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
