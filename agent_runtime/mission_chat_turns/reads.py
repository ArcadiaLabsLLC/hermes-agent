"""The journal's reads — one element list, one record, a session's records, the in-flight scans.

Read-only: each goes through ``records._safe_record`` / ``_safe_elements`` so a
caller sees the bounded projection, never raw journal contents.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.serde import safe_assignment_text

from agent_runtime.mission_chat_turns.records import _safe_elements, _safe_record
from agent_runtime.mission_chat_turns.states import INFLIGHT_TURN_STATES, _record_state
from agent_runtime.mission_chat_turns.storage import (
    _iter_session_files,
    _migrate_legacy_if_present,
    _read_session,
    _read_session_map,
)

__layer__ = "stores"


def mission_chat_turn_elements(
    *,
    session_id: str | None,
    client_message_id: str | None,
) -> list[dict[str, Any]]:
    session_key = safe_assignment_text(session_id, limit=240)
    message_key = safe_assignment_text(client_message_id, limit=240)
    if not session_key or not message_key:
        return []
    record = _read_session(session_key).get(message_key)
    if not isinstance(record, dict):
        return []
    return _safe_elements(record.get("elements"))


def mission_chat_turn_record(
    *,
    session_id: str | None,
    client_message_id: str | None,
) -> dict[str, Any] | None:
    session_key = safe_assignment_text(session_id, limit=240)
    message_key = safe_assignment_text(client_message_id, limit=240)
    if not session_key or not message_key:
        return None
    record = _read_session(session_key).get(message_key)
    if not isinstance(record, dict):
        return None
    return _safe_record(record, client_message_id=message_key)


def mission_chat_turn_records(
    *,
    session_id: str | None,
) -> list[dict[str, Any]]:
    session_key = safe_assignment_text(session_id, limit=240)
    if not session_key:
        return []
    raw_session = _read_session(session_key)
    if not isinstance(raw_session, dict):
        return []
    records: list[dict[str, Any]] = []
    for message_key, record in raw_session.items():
        if not isinstance(record, dict):
            continue
        safe_key = safe_assignment_text(message_key, limit=240)
        if not safe_key:
            continue
        safe_record = _safe_record(record, client_message_id=safe_key)
        if safe_record is not None:
            records.append(safe_record)
    # C8 replay order: turn START, not `updated_at` settle time — a long turn
    # that settles after a quick later one must not replay after it (F17 seam
    # d). `started_at` is stamped at write-ahead; records that predate the
    # anchor fall back to their settle time (pre-C8 behavior, honest fallback).
    return sorted(
        records,
        key=lambda item: (
            str(item.get("started_at") or item.get("updated_at") or ""),
            str(item.get("client_message_id") or ""),
        ),
    )


def inflight_chat_session_roots() -> list[str]:
    """Root chat session ids of sessions holding at least one in-flight record.

    Read-only scan feeding the serve-boot orphan sweep. The root id comes from
    record metadata (``root_chat_session_id``, then ``active_session_id``) —
    the session file stem is a one-way digest and cannot be reversed, so a
    record that predates the metadata stays invisible here and keeps relying
    on the next-send repair. Torn/unreadable files are skipped; the sweep is
    best-effort and retries on the next boot.
    """

    _migrate_legacy_if_present()
    roots: list[str] = []
    seen: set[str] = set()
    for path in _iter_session_files():
        for record in _read_session_map(path).values():
            if not isinstance(record, dict):
                continue
            if _record_state(record) not in INFLIGHT_TURN_STATES:
                continue
            root = safe_assignment_text(
                record.get("root_chat_session_id") or record.get("active_session_id"),
                limit=240,
            )
            if root and root not in seen:
                seen.add(root)
                roots.append(root)
    return roots


def inflight_turn_rows() -> list[dict[str, Any]]:
    """Every in-flight turn RECORD across every session, bounded and safe.

    ``inflight_chat_session_roots`` answers "which sessions owe a sweep?" — a
    set of ids. The ``running_work`` projection asks a different question:
    "which turns are in flight right now, and since when?", which needs the
    records themselves. Deriving that from the roots is not possible: the
    session FILE stem is a one-way digest of the session KEY, while the root id
    lives in record metadata and the two are not interchangeable, so a caller
    holding only a root cannot get back to the records it came from.

    Same scan discipline as the roots walk: read-only, torn/unreadable files
    skipped, every record passed through ``_safe_record`` so callers see the
    bounded, redaction-safe projection rather than raw journal contents. The
    ``session_id`` carried on each row is the record's own root/active id — the
    same field the roots walk reads — so a record predating that metadata
    reports an empty session rather than a fabricated one.

    Ordered by turn start (``started_at``, falling back to ``updated_at``) so
    the oldest in-flight work sorts first, matching the C8 replay ordering
    ``mission_chat_turn_records`` already uses.
    """

    _migrate_legacy_if_present()
    rows: list[dict[str, Any]] = []
    for path in _iter_session_files():
        for message_key, record in _read_session_map(path).items():
            if not isinstance(record, dict):
                continue
            if _record_state(record) not in INFLIGHT_TURN_STATES:
                continue
            safe_key = safe_assignment_text(message_key, limit=240)
            if not safe_key:
                continue
            safe_record = _safe_record(record, client_message_id=safe_key)
            if safe_record is None:
                continue
            # Elements are the turn's projected message content; the projection
            # only needs identity + timing, and carrying them would put chat
            # text on a HUD wire that has no reader for it.
            safe_record.pop("elements", None)
            safe_record["session_id"] = safe_assignment_text(
                record.get("root_chat_session_id") or record.get("active_session_id"),
                limit=240,
            )
            rows.append(safe_record)
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("started_at") or item.get("updated_at") or ""),
            str(item.get("client_message_id") or ""),
        ),
    )
