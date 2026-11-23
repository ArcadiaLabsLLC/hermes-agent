"""``runtime.events.after`` — Lens-episode and agent-turn events after a durable cursor.

Row ``RT-LAUNCHER-EVENT-CURSOR``; plan
``docs/agent-runtime-harness/planned/launcher-event-cursor-2026-10-28.md``. The
launcher's webhook source reads this on attach so an event produced while no
launcher ran is sent once and never lost silently. The journal and its bounds
are ``agent_runtime/event_cursor.py``; this module owns what a caller may see:

* a CLOSED allow-list of kinds (:data:`WEBHOOK_EVENT_TYPES`) — a request may
  narrow it, never widen it, because each kind is a payload a third party's
  receiver sees;
* a PROJECTION of each payload onto its contract's declared fields
  (``decision_contract_registry``), so a key added to an event later does not
  reach a receiver until this module's contract names it;
* the reply: ``{events: [{event_id, type, at, payload}], next_cursor, at_tail,
  refused?: {reason, tail_cursor?, floor_cursor?, lost_bytes?}, skipped?:
  [{reason, from_cursor, to_cursor, bytes}]}``. A refusal is a result, not an
  error: it names the cursor to move to, and its ``next_cursor`` is the cursor
  sent (a refused page never advances anyone). ``skipped`` names each
  unreadable journal line (``journal_line_unreadable``) the page passed: the
  page still advances, and the span is the evidence of what was not read.

Tier ``read``: identity keys and states, never message text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from agent_runtime.call_authorization import TIER_READ
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "DEFAULT_LIMIT",
    "MAXIMUM_LIMIT",
    "WEBHOOK_EVENT_TYPES",
    "EventsAfterParamRefusal",
    "_runtime_events_after",
    "project_payload",
]

#: The kinds a caller may read. Adding one is a code change with its own test.
WEBHOOK_EVENT_TYPES: frozenset[str] = frozenset({
    "lens.episode.changed",
    "lens.receipt.changed",
    "persona_chat.turn_ended",
})
DEFAULT_LIMIT = 200
MAXIMUM_LIMIT = 500


class EventsAfterParamRefusal(StrEnum):
    """``data.reason`` of an ``invalid_params`` refusal of this method."""

    CURSOR_INVALID = "cursor_invalid"
    TYPES_INVALID = "types_invalid"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    LIMIT_INVALID = "limit_invalid"


class _Refused(Exception):
    def __init__(self, reason: EventsAfterParamRefusal, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def project_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` reduced to its contract's summary and detail fields, minus redacted ones."""

    from agent_runtime.decision_contract_registry import event_catalog

    contract = event_catalog().get(event_type) or {}
    redacted = set(contract.get("redacted_fields") or ())
    declared = [key for key in (*contract.get("summary_fields", ()), *contract.get("detail_fields", ()))
                if key not in redacted]
    return {key: payload[key] for key in declared if key in payload}


def _cursor_param(params: dict) -> tuple[str, int] | None:
    from agent_runtime.event_cursor import parse_cursor

    raw = params.get("cursor")
    if raw is None:
        return None
    parsed = parse_cursor(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise _Refused(EventsAfterParamRefusal.CURSOR_INVALID, "cursor must be a '<journal_id>:<offset>' string.")
    return parsed


def _types_param(params: dict) -> frozenset[str]:
    raw = params.get("types")
    if raw is None:
        return WEBHOOK_EVENT_TYPES
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise _Refused(EventsAfterParamRefusal.TYPES_INVALID, "types must be a non-empty list of strings.")
    unknown = sorted(set(raw) - WEBHOOK_EVENT_TYPES)
    if unknown:
        raise _Refused(EventsAfterParamRefusal.UNKNOWN_EVENT_TYPE,
                       f"types outside the readable kinds: {', '.join(unknown)}.")
    return frozenset(raw)


def _limit_param(params: dict) -> int:
    raw = params.get("limit", DEFAULT_LIMIT)
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= MAXIMUM_LIMIT:
        raise _Refused(EventsAfterParamRefusal.LIMIT_INVALID, f"limit must be an integer 1..{MAXIMUM_LIMIT}.")
    return raw


@method("runtime.events.after", tier=TIER_READ)
def _runtime_events_after(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Params: ``cursor?``, ``types?``, ``limit?`` (default 200, max 500). Result: see the module."""

    from agent_runtime.event_cursor import format_cursor, read_after
    from agent_runtime.serde import to_jsonable

    params = params or {}
    try:
        cursor, types, limit = _cursor_param(params), _types_param(params), _limit_param(params)
    except _Refused as refused:
        return err(rid, ERR_INVALID_PARAMS, str(refused), {"reason": refused.reason})
    page = read_after(cursor, lambda event: event.type in types, limit=limit)
    reply: dict[str, Any] = {
        "events": [
            {
                "event_id": format_cursor(page.journal, end),
                "type": event.type,
                "at": to_jsonable(event.ts),
                "payload": project_payload(event.type, event.payload),
            }
            for end, event in page.events
        ],
        "next_cursor": format_cursor(page.journal, page.next_offset),
        "at_tail": page.at_tail,
    }
    if page.skipped:
        reply["skipped"] = [
            {
                "reason": span.reason,
                "from_cursor": format_cursor(page.journal, span.start),
                "to_cursor": format_cursor(page.journal, span.end),
                "bytes": span.end - span.start,
            }
            for span in page.skipped
        ]
    if page.refused is not None:
        refused: dict[str, Any] = {"reason": page.refused.value}
        if page.resume_offset is not None:
            key = "floor_cursor" if page.lost_bytes is not None else "tail_cursor"
            refused[key] = format_cursor(page.journal, page.resume_offset)
        if page.lost_bytes is not None:
            refused["lost_bytes"] = page.lost_bytes
        reply["refused"] = refused
        # A refused page never moves the caller: ``next_cursor`` is the cursor it sent, so a client
        # that ignores ``refused`` loops on the refusal instead of silently skipping to a new position.
        reply["next_cursor"] = None if cursor is None else format_cursor(*cursor)
    return ok(rid, reply)
