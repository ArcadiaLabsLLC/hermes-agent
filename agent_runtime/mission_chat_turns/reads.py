"""The journal's reads — one element list, one record, a session's records, the in-flight scans.

Read-only: each goes through ``records._safe_record`` / ``_safe_elements`` so a
caller sees the bounded projection, never raw journal contents.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.serde import safe_assignment_text, safe_assignment_token

from agent_runtime.mission_chat_turns.records import _safe_elements, _safe_record
from agent_runtime.mission_chat_turns.states import INFLIGHT_TURN_STATES, TURN_STATE_ABANDONED, _record_state
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
    return session_turn_elements(session_id=session_id)(client_message_id)


def session_turn_elements(*, session_id: str | None) -> Callable[[str | None], list[dict[str, Any]]]:
    """One read of the session's journal, answering :func:`mission_chat_turn_elements` per turn.

    For a reader that asks about many turns of one chat (the curated transcript): it
    parsed the whole journal file once PER TURN, 318 times for the owner's Neko chat on
    2026-11-23 (1.8 s of a 4.8 s read,
    RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT)."""

    session_key = safe_assignment_text(session_id, limit=240)
    session = _read_session(session_key) if session_key else {}

    def elements(client_message_id: str | None) -> list[dict[str, Any]]:
        message_key = safe_assignment_text(client_message_id, limit=240)
        record = session.get(message_key) if message_key else None
        if not isinstance(record, dict):
            return []
        return _safe_elements(record.get("elements"))

    return elements


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


def abandoned_mission_chat_message_ids(*, session_id: str | None) -> frozenset[str]:
    """Validated abandoned IDs without projecting elements or sorting turn records."""
    session_key = safe_assignment_text(session_id, limit=240)
    if not session_key:
        return frozenset()
    records = _read_session(session_key)
    if not isinstance(records, dict):
        return frozenset()
    return frozenset(
        safe_key
        for key, record in records.items()
        if isinstance(record, dict) and _record_state(record) == TURN_STATE_ABANDONED
        and (safe_key := safe_assignment_text(key, limit=240))
        and (safe_assignment_token(record.get("turn_id")) or safe_assignment_token(safe_key))
    )


def is_abandoned_mission_chat_message(message_id: str, abandoned_ids: frozenset[str]) -> bool:
    """Match exact IDs and every colon prefix, including overlapping/legacy IDs."""
    return message_id in abandoned_ids or any(
        message_id[:index] in abandoned_ids
        for index, char in enumerate(message_id) if char == ":"
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

    return sorted(
        _projected_turn_rows(lambda record: _record_state(record) in INFLIGHT_TURN_STATES),
        key=lambda item: (
            str(item.get("started_at") or item.get("updated_at") or ""),
            str(item.get("client_message_id") or ""),
        ),
    )


def running_work_turn_rows(
    *, settled_states: frozenset[str], settled_since: float, settled_limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(in flight, settled)`` in ONE journal walk: :func:`inflight_turn_rows`' rows in its order, and
    the records in ``settled_states`` that settled at or after ``settled_since`` (epoch), newest first, at
    most ``settled_limit``.

    ``running_work``'s ended rows (RT-FU-RUNNING-WORK-KEEPS-ENDED-AGENT-WORK-FOR-A-WHILE): a record's
    ``updated_at`` is its settle stamp once it leaves the in-flight set. A record with no readable
    stamp is not listed as settled. One walk, because the projection is polled and the walk reads
    every session file.
    """

    from agent_runtime.clock import parse_iso_utc

    def _keep(record: dict[str, Any]) -> bool:
        state = _record_state(record)
        if state in INFLIGHT_TURN_STATES:
            return True
        if state not in settled_states:
            return False
        stamp = parse_iso_utc(safe_assignment_text(record.get("updated_at"), limit=80))
        return stamp is not None and stamp.timestamp() >= settled_since

    inflight: list[dict[str, Any]] = []
    settled: list[dict[str, Any]] = []
    for row in _projected_turn_rows(_keep):
        (inflight if row.get("state") in INFLIGHT_TURN_STATES else settled).append(row)
    inflight.sort(key=lambda item: (str(item.get("started_at") or item.get("updated_at") or ""),
                                    str(item.get("client_message_id") or "")))
    settled.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("client_message_id") or "")),
                 reverse=True)
    return inflight, settled[: max(0, int(settled_limit))]


def _projected_turn_rows(keep) -> list[dict[str, Any]]:
    """Every journal record ``keep`` accepts, bounded and safe, with its root/active ``session_id``."""

    _migrate_legacy_if_present()
    rows: list[dict[str, Any]] = []
    for path in _iter_session_files():
        for message_key, record in _read_session_map(path).items():
            if not isinstance(record, dict):
                continue
            if not keep(record):
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
    return rows


def last_turn_started_by_instance() -> dict[str, str]:
    """The newest turn start per persona instance, ``{instance_id: started_at}`` (the directory's ``last_used_at``).

    RT-AGENT-INSTANCE-SAYS-WHEN-IT-WAS-LAST-USED: the journal is the one record of a chat turn on an
    instance, so "last used" is derived here, never stored twice. A turn counts from its admission
    (``started_at``, else ``updated_at`` for a pre-C8 record), whatever state it reached. Stamps are
    the journal's own ``now_iso_micro`` strings, which order lexically. An instance whose sessions were
    all archived by the retention GC has no entry. Read-only; a torn file is skipped.
    """

    _migrate_legacy_if_present()
    newest: dict[str, str] = {}
    for path in _iter_session_files():
        for record in _read_session_map(path).values():
            if not isinstance(record, dict):
                continue
            instance_id = safe_assignment_text(record.get("persona_instance_id"), limit=200)
            stamp = safe_assignment_text(record.get("started_at") or record.get("updated_at"), limit=80)
            if instance_id and stamp and stamp > newest.get(instance_id, ""):
                newest[instance_id] = stamp
    return newest


def all_mission_chat_turn_records() -> list[dict[str, Any]]:
    """Every turn record across every session file, bounded and safe (the audit read).

    RT-TURN-AUDIT-ENTRY: ``chat_verbs.turn_audit`` filters these by persona instance or chat. A
    session file's stem is a one-way digest, so the filter runs on record metadata, never on file
    names. Read-only; a torn or unreadable file is skipped, never repaired.
    """

    _migrate_legacy_if_present()
    rows: list[dict[str, Any]] = []
    for path in _iter_session_files():
        for message_key, record in _read_session_map(path).items():
            if not isinstance(record, dict):
                continue
            safe_key = safe_assignment_text(message_key, limit=240)
            safe = _safe_record(record, client_message_id=safe_key) if safe_key else None
            if safe is not None:
                rows.append(safe)
    return rows
