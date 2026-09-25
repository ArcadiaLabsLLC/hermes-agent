"""The journal's four writes — persist, transition, abandon, mark stale.

Every write goes through ``_mutate_session``, the ONE write chokepoint: the
session's lock held for the whole read-modify-write, the turn cap applied, and a
lock timeout returned as a typed outcome instead of a hang.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from agent_runtime.mission_chat_phases import TURN_RECORD_SCHEMA_VERSION
from agent_runtime.serde import safe_assignment_text, safe_assignment_token

from agent_runtime.mission_chat_turns.records import (
    _safe_elements,
    _safe_journal_metadata,
    _utc_now_iso,
)
from agent_runtime.mission_chat_turns.states import (
    INFLIGHT_TURN_STATES,
    JOURNAL_TURN_STATES,
    LEGACY_TURN_STATES,
    OPERATOR_RESOLVABLE_TURN_STATES,
    TURN_STATE_ABANDONED,
    TURN_STATE_INTERRUPTED,
    _JOURNAL_TRANSITIONS,
    _LEGACY_TO_JOURNAL_STATE,
    MissionChatTurnPersistOutcome,
    _record_state,
    _safe_turn_state,
    next_turn_state,
)
from agent_runtime.mission_chat_turns.storage import (
    _apply_session_turn_cap,
    _file_lock,
    _gc_session_files,
    _migrate_legacy_if_present,
    _read_session_map,
    _session_file_path,
    _session_lock_path,
    _write_session_file,
)

__layer__ = "lanes"


_T = TypeVar("_T")


def persist_mission_chat_turn(
    *,
    session_id: str | None,
    client_message_id: str | None,
    turn_id: str | None,
    elements: list[dict[str, Any]] | None,
    state: str | None = None,
    write_ahead: bool = False,
    metadata: dict[str, Any] | None = None,
) -> MissionChatTurnPersistOutcome:
    session_key = safe_assignment_text(session_id, limit=240)
    message_key = safe_assignment_text(client_message_id, limit=240)
    if not session_key or not message_key:
        return MissionChatTurnPersistOutcome.SKIPPED_NO_KEYS
    requested_state = _safe_turn_state(state) if state is not None else None
    if state is not None and requested_state is None:
        return MissionChatTurnPersistOutcome.REJECTED_INVALID_STATE
    if state is None and not elements:
        return MissionChatTurnPersistOutcome.SKIPPED_EMPTY_LEGACY
    safe_elements = _safe_elements(elements)
    if state is None and not safe_elements:
        return MissionChatTurnPersistOutcome.SKIPPED_EMPTY_LEGACY

    def _mutate(session: dict[str, Any]) -> tuple[bool, MissionChatTurnPersistOutcome]:
        existing = session.get(message_key)
        resolved_state = next_turn_state(
            _record_state(existing),
            requested_state,
            write_ahead=write_ahead,
        )
        if resolved_state is None:
            return False, MissionChatTurnPersistOutcome.REJECTED_STALE_TRANSITION
        # C8 turn-start anchor: stamped ONCE at write-ahead (the moment the turn
        # begins) and carried unchanged through every later flush/terminal
        # persist, so replay can order turns by when they STARTED instead of
        # when they settled. Records that predate the anchor never get one
        # retro-stamped — they fall back to settle-time order (honest fallback,
        # no fabricated keys).
        started_at = (
            safe_assignment_text((existing or {}).get("started_at"), limit=80)
            if isinstance(existing, dict)
            else None
        )
        if write_ahead and not started_at:
            started_at = _utc_now_iso()
        prior = dict(existing) if isinstance(existing, dict) else {}
        session[message_key] = {
            **prior,
            "schema_version": TURN_RECORD_SCHEMA_VERSION,
            "turn_id": safe_assignment_token(turn_id) or safe_assignment_token(message_key),
            "state": resolved_state,
            "updated_at": _utc_now_iso(),
            **({"started_at": started_at} if started_at else {}),
            "elements": safe_elements,
            **_safe_journal_metadata(metadata),
        }
        return True, MissionChatTurnPersistOutcome.PERSISTED

    return _mutate_session(
        session_key,
        _mutate,
        timeout_result=MissionChatTurnPersistOutcome.SKIPPED_LOCK_TIMEOUT,
        protected_message=message_key,
    )


def transition_mission_chat_turn(
    *,
    session_id: str | None,
    client_message_id: str | None,
    turn_id: str | None,
    state: str,
    metadata: dict[str, Any] | None = None,
    elements: list[dict[str, Any]] | None = None,
) -> MissionChatTurnPersistOutcome:
    """Durably advance the exactly-once persona-chat journal.

    The record is keyed by stable root plus client id and also carries the turn
    id.  Invalid/backwards transitions fail closed; callers may safely repeat a
    transition to its current state after a crash.
    """

    session_key = safe_assignment_text(session_id, limit=240)
    message_key = safe_assignment_text(client_message_id, limit=240)
    requested = _safe_turn_state(state)
    if not session_key or not message_key:
        return MissionChatTurnPersistOutcome.SKIPPED_NO_KEYS
    if requested not in JOURNAL_TURN_STATES:
        return MissionChatTurnPersistOutcome.REJECTED_INVALID_STATE

    def _mutate(session: dict[str, Any]) -> tuple[bool, MissionChatTurnPersistOutcome]:
        existing = session.get(message_key)
        current = _record_state(existing) if isinstance(existing, dict) else None
        if current in LEGACY_TURN_STATES:
            current = _LEGACY_TO_JOURNAL_STATE.get(current)
        if requested not in _JOURNAL_TRANSITIONS.get(current, set()):
            return False, MissionChatTurnPersistOutcome.REJECTED_STALE_TRANSITION
        now_iso = _utc_now_iso()
        record = dict(existing) if isinstance(existing, dict) else {}
        if not record.get("started_at"):
            record["started_at"] = now_iso
        record.update(
            {
                "schema_version": TURN_RECORD_SCHEMA_VERSION,
                "turn_id": safe_assignment_token(turn_id) or safe_assignment_token(message_key),
                "state": requested,
                "updated_at": now_iso,
            }
        )
        if elements is not None:
            record["elements"] = _safe_elements(elements)
        else:
            record.setdefault("elements", [])
        record.update(_safe_journal_metadata(metadata))
        session[message_key] = record
        return True, MissionChatTurnPersistOutcome.PERSISTED

    return _mutate_session(
        session_key,
        _mutate,
        timeout_result=MissionChatTurnPersistOutcome.SKIPPED_LOCK_TIMEOUT,
        protected_message=message_key,
    )


def abandon_mission_chat_turn(
    *,
    session_id: str | None,
    client_message_id: str | None,
    turn_id: str | None,
    resolution_actor: str | None = None,
    resolution_reason: str | None = None,
) -> MissionChatTurnPersistOutcome:
    session_key = safe_assignment_text(session_id, limit=240)
    message_key = safe_assignment_text(client_message_id, limit=240)
    exact_turn = safe_assignment_token(turn_id)
    if not session_key or not message_key or not exact_turn:
        return MissionChatTurnPersistOutcome.SKIPPED_NO_KEYS

    def _mutate(session: dict[str, Any]) -> tuple[bool, MissionChatTurnPersistOutcome]:
        existing = session.get(message_key)
        if not isinstance(existing, dict):
            return False, MissionChatTurnPersistOutcome.REJECTED_STALE_TRANSITION
        if (
            _record_state(existing) not in OPERATOR_RESOLVABLE_TURN_STATES
            or safe_assignment_token(existing.get("turn_id")) != exact_turn
        ):
            return False, MissionChatTurnPersistOutcome.REJECTED_STALE_TRANSITION
        record = dict(existing)
        record.update(
            {
                "state": TURN_STATE_ABANDONED,
                "updated_at": _utc_now_iso(),
                "resolved_at": _utc_now_iso(),
                "resolution": "abandon",
                "resolution_actor": safe_assignment_text(
                    resolution_actor, limit=160
                )
                or "operator",
                "resolution_reason": safe_assignment_text(
                    resolution_reason, limit=320
                )
                or "explicit abandon",
            }
        )
        session[message_key] = record
        return True, MissionChatTurnPersistOutcome.PERSISTED

    return _mutate_session(
        session_key,
        _mutate,
        timeout_result=MissionChatTurnPersistOutcome.SKIPPED_LOCK_TIMEOUT,
        protected_message=message_key,
    )


def mark_stale_inflight_turns_interrupted(
    *,
    session_id: str | None,
    active_client_message_id: str | None,
) -> list[str]:
    """Flip a session's dead in-flight turn records to ``interrupted``.

    Callers MUST guarantee no live executor on the session: hold its root
    lease (``persona_chat_root_lease`` — held for a native turn's entire
    execution and released by the kernel when the executor dies), or run from
    a lane that already serializes sends per session. Under that guarantee
    every OTHER in-flight record —
    journal ``pending``/``executing``/``outcome_unknown`` as much as legacy
    ``running`` — is a corpse that can no longer settle itself (live incident
    2026-07-25: a reaped Launcher took its serve child down mid-turn and the
    QA relay record froze at ``executing`` forever, a permanently "running"
    console). ``interrupted`` is the one repair state the history projection
    renders as a typed ``turn_interrupted`` marker row.
    """

    session_key = safe_assignment_text(session_id, limit=240)
    active_key = safe_assignment_text(active_client_message_id, limit=240)
    if not session_key:
        return []

    def _mutate(session: dict[str, Any]) -> tuple[bool, list[str]]:
        flipped: list[str] = []
        now_iso = _utc_now_iso()
        for message_key, record in session.items():
            safe_key = safe_assignment_text(message_key, limit=240)
            if not safe_key or safe_key == active_key or not isinstance(record, dict):
                continue
            if _record_state(record) not in INFLIGHT_TURN_STATES:
                continue
            record["state"] = TURN_STATE_INTERRUPTED
            record["updated_at"] = now_iso
            flipped.append(safe_key)
        return bool(flipped), flipped

    # Lock timeout returns [] — this repair is opportunistic by design
    # (repair-on-next-write); the next send in the session retries it.
    return _mutate_session(
        session_key,
        _mutate,
        timeout_result=[],
        protected_message=active_key,
    )


def _mutate_session(
    session_key: str,
    mutator: Callable[[dict[str, Any]], tuple[bool, _T]],
    *,
    timeout_result: _T,
    protected_message: str | None = None,
) -> _T:
    """Single write chokepoint for one chat session's turn file.

    Holds that session's exclusive cross-process file lock for the whole
    read-modify-write window so concurrent CLI turns in the SAME chat can never
    lose each other's records — while turns in DIFFERENT chats take different
    locks and never contend. On lock timeout the mutation is skipped and
    ``timeout_result`` is returned — a chat turn must never hang on a stuck
    lock; the skip is surfaced through the typed persist outcome.

    Every changed write applies the per-session turn cap (same lock, same
    atomic tmp-replace). When the write CREATES a new session file, a
    best-effort directory GC bounds the session count (see
    ``_gc_session_files``). Retention never evicts ``running`` records or the
    protected record being written, and it is invisible to the mutator result.
    """

    _migrate_legacy_if_present()
    path = _session_file_path(session_key)
    changed = False
    created = False
    with _file_lock(_session_lock_path(session_key)) as acquired:
        if not acquired:
            return timeout_result
        created = not path.exists()
        session = _read_session_map(path)
        changed, result = mutator(session)
        if changed:
            _apply_session_turn_cap(session, protected_message=protected_message)
            _write_session_file(path, session)
    # Bound the session-file count only when a new session file appeared — the
    # only moment the directory can grow. Runs OUTSIDE the session lock (it
    # takes the GC lock + non-blocking per-candidate locks; the just-written
    # session is protected), so the hot per-flush path (rewrites of an existing
    # session file) never pays for a directory scan.
    if changed and created:
        _gc_session_files(protected_session_key=session_key)
    return result
