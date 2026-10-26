"""Bounded next-message context through native membership and existing curation.

The turn journal already retains committed operator/final-reply pairs. Native
membership fences that evidence after rewinds; no shadow transcript is written.
"""
from __future__ import annotations

from datetime import datetime, UTC
import hashlib
import json
import time

from agent_runtime.mission_chat_turns.reads import mission_chat_turn_records
from agent_runtime.mission_chat_turns.states import TURN_STATE_PROJECTED, INFLIGHT_TURN_STATES, SETTLING_TURN_STATES
from agent_runtime.operator_session_inspection import operator_session_read, inspection_identity
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from .operator_envelopes import strip_operator_envelopes
from .text import _curate_chat_message_text
from .vocabulary import logical_persona_chat_client_message_id, MessageRole
from agent.redact import redact_for_egress
from agent_runtime.relay_policy import parse_relay_sender_marker, parse_harness_delivery_marker, parse_lens_episode_marker

__layer__ = "lanes"


def clip_context(text: str) -> str:
    return text if len(text) <= 1200 else text[:300] + "\n…\n" + text[-900:]


def _logical(row):
    return logical_persona_chat_client_message_id(row.get("platform_message_id") or row.get("client_message_id") or row.get("message_id"))


def _native_tail(db, tip):
    rows, seen = [], set()
    while tip and tip not in seen and len(seen) < 8 and len(rows) < 256:
        seen.add(tip)
        rows = db.get_messages(tip, limit=256 - len(rows), latest=True, include_compacted=True) + rows
        tip = (db.get_session(tip) or {}).get("parent_session_id")
    return [row for row in rows if row.get("display_kind") != "hidden"]


def suggestion_context(params: dict, window: int, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with operator_session_read(params) as (_, session):
        identity = inspection_identity(params, session.owner)
        db = session.db
        tip = db.resolve_resume_session_id(params["session_id"])
        current = db.get_session(tip)
        if current is None or db.session_turn_is_active(params["session_id"]):
            return {"identity": identity, "reason": "turn_active"}
        if PersonaChatClarifyTicketStore().open_ticket_for_session(params["session_id"]):
            return {"identity": identity, "reason": "manual_confirmation_required"}
        records = mission_chat_turn_records(session_id=params["session_id"])
        if not records or any(row["state"] in INFLIGHT_TURN_STATES | SETTLING_TURN_STATES for row in records):
            return {"identity": identity, "reason": "turn_active"}
        # One indexed native tail, with a hard scan budget independent of chat age.
        raw = _native_tail(db, tip)
        logical_ids = {_logical(row) for row in raw}
        visible = [record for record in records if record["client_message_id"] in logical_ids]
        if not visible:
            return {"identity": identity, "reason": "context_unavailable"}
        latest = visible[-1]
        operator_roles = {MessageRole.OPERATOR: True}
        native_users = [row for row in raw if operator_roles.get(MessageRole.from_wire(row.get("role")), False)]
        if not native_users or _logical(native_users[-1]) != latest["client_message_id"]:
            return {"identity": identity, "reason": "source_ineligible"}
        if (latest["state"] != TURN_STATE_PROJECTED or not latest.get("projection_committed")
                or not latest.get("stored_reply") or not latest.get("pending_user_message")):
            return {"identity": identity, "reason": "source_ineligible"}
        timestamp = datetime.fromisoformat(latest["updated_at"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if not 0 <= now - timestamp.timestamp() <= 86400:
            return {"identity": identity, "reason": "expired"}
        members = [row for row in raw if _logical(row) == latest["client_message_id"]]
        if any(parser(row.get("finish_reason")) is not None for row in members
               for parser in (parse_relay_sender_marker, parse_harness_delivery_marker, parse_lens_episode_marker)):
            return {"identity": identity, "reason": "source_ineligible"}
        messages = []
        for record in visible[-max(1, window // 2):]:
            if record["state"] != TURN_STATE_PROJECTED:
                continue
            user = strip_operator_envelopes(record.get("pending_user_message", ""), include_media=False)[0]
            pair = [("operator", user), ("agent", record.get("stored_reply", ""))]
            curated = [_curate_chat_message_text(role, text) for role, text in pair]
            if not all(curated):
                if record is latest:
                    return {"identity": identity, "reason": "context_unavailable"}
                continue
            messages.extend({"role": role, "content": clip_context(redact_for_egress(text))}
                            for role, text in zip(("user", "assistant"), curated))
        if not messages:
            return {"identity": identity, "reason": "context_unavailable"}
        # Only bounded native state is hashed. A new turn, redo, compression or
        # membership change invalidates publication without rereading all history.
        revision = hashlib.sha256(json.dumps([tip, current.get("message_count"),
            [(row.get("id"), row.get("platform_message_id"), row.get("content")) for row in raw],
            latest.get("native_revision")], default=str).encode()).hexdigest()
        return {"identity": identity, "source_turn_id": latest["turn_id"], "source_revision": revision,
                "source_time": timestamp.timestamp(), "messages": messages}
