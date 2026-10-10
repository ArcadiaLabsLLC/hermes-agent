"""Retain journal evidence while projecting only a chat's native membership."""
from __future__ import annotations

import json

from ..mission_chat_turns.reads import mission_chat_turn_records
from .vocabulary import logical_persona_chat_client_message_id

__layer__ = "stores"


def history_turn_records(db, session_id, raw_messages):
    visible = {_logical(row) for row in raw_messages if isinstance(row, dict)} - {None}
    records = mission_chat_turn_records(session_id=session_id)
    if not callable(getattr(db, "archived_history_message_ids", None)) or not callable(getattr(db, "get_session", None)):
        return records
    tip = db.resolve_resume_session_id(session_id)
    archived = {logical_persona_chat_client_message_id(value)
                for value in db.archived_history_message_ids(tip)} - visible - {None}
    own = [row for row in records if row.get("client_message_id") not in archived]
    inherited = []
    seen = {session_id}
    current = session_id
    # Follow explicit branch provenance, never compression ancestry or an
    # ambient default chat. Read retained source journals even if the source
    # was subsequently rewound; the copied native prefix is the membership pin.
    while True:
        row = db.get_session(current) or {}
        config = row.get("model_config") or {}
        config = json.loads(config) if isinstance(config, str) else config
        source = config.get("history_source_session")
        if not source or source in seen or len(seen) > 100:
            break
        seen.add(source)
        inherited.extend({**record, "_history_source_session": source}
                         for record in mission_chat_turn_records(session_id=source)
                         if record.get("client_message_id") in visible)
        current = source
    by_id = {record["client_message_id"]: record for record in reversed(inherited)}
    by_id.update({record["client_message_id"]: record for record in own})
    return list(by_id.values())


def _logical(row):
    return logical_persona_chat_client_message_id(
        row.get("platform_message_id") or row.get("message_id") or row.get("client_message_id"))
