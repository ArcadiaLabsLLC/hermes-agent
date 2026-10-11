"""The settle-push outbox: every settled chat turn, until the launcher acks it.

Owner ruling 2026-10-09: hermes PUSHES each chat-turn settle (exit code, refusal
class, ``fix_hint``) to the launcher and verifies the push landed; the launcher
never polls. Contract: ``docs/agent-runtime-harness/planned/settle-push-2026-10-10.md``.

This module is the durable half. A record is written ``pending`` BEFORE the turn's
``exit`` frame (so a serve restart loses no settle), re-sent by the serve's pusher
on a bounded backoff, moved to ``acked`` by the launcher's ``settle_ack``, and moved
to ``undelivered`` — a typed, reasoned terminal state — when the budget runs out.

It is NOT a turn-outcome authority. The mission-chat journal owns what a turn did;
this file owns only whether the launcher has been TOLD.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable

from hermes_time import now
from utils import atomic_json_write

from . import paths
from .locks import chat_turn_settle_lock
from .serde import read_versioned_receipt

__layer__ = "stores"

_SCHEMA_VERSION = 1

STATE_PENDING = "pending"
STATE_ACKED = "acked"
STATE_UNDELIVERED = "undelivered"
_VALID_STATES = frozenset({STATE_PENDING, STATE_ACKED, STATE_UNDELIVERED})

#: Why a settle stopped being re-sent without an ack.
UNDELIVERED_RETRY_BUDGET = "retry_budget_exhausted"
UNDELIVERED_NO_LISTENER = "no_listener"

#: Counted attempts (a frame some sink took) before ``retry_budget_exhausted``.
MAX_ATTEMPTS = 6
#: Seconds after attempt N before attempt N+1: 2, 4, 8, 16, 32.
BACKOFF_BASE_SECONDS = 2.0
#: A settle no client was ever attached to take, after this long, is undelivered.
NO_LISTENER_SECONDS = 3600.0

#: Refusal classes that are NOT a settle of the turn: another worker owns it and
#: its own settle is the one the launcher needs.
NON_TERMINAL_REFUSALS = frozenset({"chat_turn_duplicate_in_flight"})

#: How many trailing stdout lines are scanned for the turn's result line.
RESULT_TAIL_LINES = 64
_MAX_RESULT_LINE_CHARS = 256 * 1024
_MAX_TEXT_CHARS = 2000

SETTLE_EVENT = "turn_settled"
SETTLE_LANE = "settle"


class RearmResult(StrEnum):
    """What :func:`rearm_settle` did (D2.05)."""

    #: ``undelivered -> pending``: due on the pusher's next tick.
    REARMED = "rearmed"
    #: Already ``pending``: nothing to do, the record is returned as it is.
    ALREADY_PENDING = "already_pending"
    #: ``acked``: refused — the launcher already took this settle.
    ACKED = "acked"
    NOT_FOUND = "not_found"


class SettleRefusal(StrEnum):
    """``reason`` for a refused settle read or re-arm, on both doors (RPC and argv)."""

    STATE_INVALID = "state_invalid"
    SETTLE_REF_REQUIRED = "settle_ref_required"
    SETTLE_NOT_FOUND = "settle_not_found"
    SETTLE_ACKED = "settle_acked"


@dataclass(frozen=True)
class TurnOutcome:
    """What the turn's own result line says, normalized."""

    session_id: str | None = None
    turn_id: str | None = None
    refusal_class: str | None = None
    fix_hint: str | None = None
    summary: str | None = None
    #: The answer was "accepted and queued" (a busy root): the turn has not run,
    #: so this is not its settle. Its settle is recorded when it runs.
    queued: bool = False


@dataclass(frozen=True)
class SettleRecord:
    settle_id: str
    client_message_id: str
    session_id: str | None
    turn_id: str | None
    request_id: str
    exit_code: int
    refusal_class: str | None
    fix_hint: str | None
    summary: str | None
    settled_at: str
    state: str = STATE_PENDING
    attempts: int = 0
    last_attempt_at: str | None = None
    next_attempt_at: str | None = None
    acked_at: str | None = None
    undelivered_reason: str | None = None
    updated_at: str = ""
    #: D2.05: how many times an operator re-armed this record, and when last.
    #: A record written before these existed reads 0 / None (additive fields;
    #: the schema version does not move, so an older serve still reads it).
    rearm_count: int = 0
    rearmed_at: str | None = None

    def as_row(self) -> dict[str, Any]:
        """The stored record as one listing row (the operator verbs' shape)."""

        return asdict(self)

    def frame(self) -> dict[str, Any]:
        """The ``turn_settled`` frame for the NEXT attempt."""

        return {
            "event": SETTLE_EVENT,
            "lane": SETTLE_LANE,
            "settle_id": self.settle_id,
            "client_message_id": self.client_message_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "request_id": self.request_id,
            "exit_code": self.exit_code,
            "refusal_class": self.refusal_class,
            "fix_hint": self.fix_hint,
            "summary": self.summary,
            "settled_at": self.settled_at,
            "attempt": self.attempts + 1,
        }


def settle_id_for(session_id: str | None, client_message_id: str) -> str:
    """The record key: one settle per (session, client message id)."""

    raw = f"{session_id or ''}\x00{client_message_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def outcome_from_result_lines(lines: Iterable[str]) -> TurnOutcome:
    """Read the LAST JSON-object line a chat turn printed.

    Mission chat prints one result object (``ok``/``error_kind``/``error``/
    ``next_expected``/``session_id``/``turn_id``); a harness refusal prints the
    stage-42 envelope (``kind: error``, ``error: {code, message, hint}``). Both
    are read; anything else contributes nothing.
    """

    for line in reversed(list(lines)):
        text = str(line or "").strip()
        if not text.startswith("{") or len(text) > _MAX_RESULT_LINE_CHARS:
            continue
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return _outcome_from(data)
    return TurnOutcome()


def outcome_from_payload(data: Any) -> TurnOutcome:
    """The same reading as :func:`outcome_from_result_lines`, over a payload dict.

    For a turn run in-process through the mission-chat door (the queued-send
    runner), whose result never reaches a stdout capture.
    """

    return _outcome_from(data) if isinstance(data, dict) else TurnOutcome()


def _outcome_from(data: dict[str, Any]) -> TurnOutcome:
    error = data.get("error")
    envelope = error if isinstance(error, dict) else {}
    refusal = _settle_text(data.get("error_kind")) or _settle_text(envelope.get("code"))
    if refusal is None and data.get("ok") is False:
        refusal = _settle_text(data.get("code"))
    fix_hint = (
        _settle_text(data.get("fix_hint"))
        or _settle_text(envelope.get("hint"))
        or (_settle_text(data.get("next_expected")) if refusal else None)
    )
    summary = _settle_text(data.get("summary")) or _settle_text(envelope.get("message"))
    if summary is None and isinstance(error, str):
        summary = _settle_text(error)
    return TurnOutcome(
        session_id=_settle_text(data.get("session_id")) or _settle_text(data.get("root_chat_session_id")),
        turn_id=_settle_text(data.get("turn_id")),
        refusal_class=refusal,
        fix_hint=_scrubbed(fix_hint),
        summary=_scrubbed(summary),
        queued=data.get("queued") is True,
    )


def _scrubbed(value: str | None) -> str | None:
    """Redact free text before it reaches the durable record and the push.

    ``summary`` / ``fix_hint`` are free text a provider error can carry a key in,
    and the settle record is a NEW durable surface (written to disk, re-broadcast
    for up to an hour). A safety boundary, so ``force=True``, and fail CLOSED: if
    redaction itself fails the text is dropped, never written raw.
    """

    if value is None:
        return None
    try:
        from agent.redact import redact_sensitive_text

        return _settle_text(redact_sensitive_text(value, force=True, redact_url_credentials=True))
    except Exception:
        return None


def record_settle(
    *,
    client_message_id: str,
    session_id: str | None,
    request_id: str,
    exit_code: int,
    outcome: TurnOutcome,
) -> SettleRecord | None:
    """Durable BEFORE the exit frame. ``None`` when there is nothing to push.

    A "queued" answer is not a settle (the turn has not run) and records nothing.

    Idempotent on (session, client message id): a record that already exists is
    returned unchanged — the first settle of a turn is its settle, and a replayed
    presentation of a committed turn reports the same outcome.
    """

    cmid = str(client_message_id or "").strip()
    if not cmid or outcome.queued or outcome.refusal_class in NON_TERMINAL_REFUSALS:
        return None
    session = _settle_text(session_id) or outcome.session_id
    settle_id = settle_id_for(session, cmid)
    with chat_turn_settle_lock(settle_id):
        existing = _read_or_none(settle_id)
        if existing is not None:
            return existing
        stamp = _timestamp()
        record = SettleRecord(
            settle_id=settle_id,
            client_message_id=cmid,
            session_id=session,
            turn_id=outcome.turn_id,
            request_id=str(request_id),
            exit_code=int(exit_code),
            refusal_class=outcome.refusal_class,
            fix_hint=outcome.fix_hint,
            summary=outcome.summary,
            settled_at=stamp,
            next_attempt_at=stamp,
            updated_at=stamp,
        )
        _write(record)
        return record


def due_settles(at: datetime | None = None) -> list[SettleRecord]:
    """Pending records whose next attempt is due, oldest first."""

    moment = at or now()
    due = [
        record
        for record in list_settles(state=STATE_PENDING)
        if record.next_attempt_at is None or _parse(record.next_attempt_at) <= moment
    ]
    return sorted(due, key=lambda record: record.settled_at)


def note_push(settle_id: str, *, delivered_to: int, at: datetime | None = None) -> SettleRecord | None:
    """Account one push of a pending record; may move it to ``undelivered``.

    ``delivered_to`` is how many sinks took the frame. Zero is not an attempt —
    nobody was listening — and only ages the record toward ``no_listener``.
    """

    moment = at or now()
    with chat_turn_settle_lock(settle_id):
        record = _read_or_none(settle_id)
        if record is None or record.state != STATE_PENDING:
            return record
        stamp = _iso(moment)
        if delivered_to > 0:
            attempts = record.attempts + 1
            if attempts >= MAX_ATTEMPTS:
                updated = replace(
                    record, attempts=attempts, last_attempt_at=stamp,
                    next_attempt_at=None, state=STATE_UNDELIVERED,
                    undelivered_reason=UNDELIVERED_RETRY_BUDGET, updated_at=stamp,
                )
            else:
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
                updated = replace(
                    record, attempts=attempts, last_attempt_at=stamp,
                    next_attempt_at=_iso(moment + timedelta(seconds=delay)), updated_at=stamp,
                )
        elif (moment - _listener_clock(record)).total_seconds() >= NO_LISTENER_SECONDS:
            updated = replace(
                record, next_attempt_at=None, state=STATE_UNDELIVERED,
                undelivered_reason=UNDELIVERED_NO_LISTENER, updated_at=stamp,
            )
        else:
            return record
        _write(updated)
        return updated


def _listener_clock(record: SettleRecord) -> datetime:
    """Where the no-listener hour is counted from: the latest attempt or re-arm, else the settle."""

    stamps = [_parse(stamp) for stamp in (record.last_attempt_at, record.rearmed_at) if stamp]
    return max(stamps) if stamps else _parse(record.settled_at)


def rearm_settle(settle_id: str, *, at: datetime | None = None) -> tuple[RearmResult, SettleRecord | None]:
    """``undelivered -> pending`` with a fresh budget; the ONE writer of that move (D2.05).

    ``attempts`` resets to 0 and ``next_attempt_at`` to now, so the record is due
    under the pusher's own rule (a re-arm that kept the spent budget would be
    undelivered again on the first push). Same ``settle_id``: one settle per turn,
    and the launcher acks by ``client_message_id``. History is ``rearm_count``.
    """

    clean = str(settle_id or "").strip()
    if not clean or not paths.chat_turn_settle_path(clean).is_file():
        return RearmResult.NOT_FOUND, None
    with chat_turn_settle_lock(clean):
        record = _read_or_none(clean)
        if record is None:
            return RearmResult.NOT_FOUND, None
        if record.state == STATE_ACKED:
            return RearmResult.ACKED, record
        if record.state == STATE_PENDING:
            return RearmResult.ALREADY_PENDING, record
        stamp = _iso(at or now())
        updated = replace(
            record, state=STATE_PENDING, attempts=0, next_attempt_at=stamp,
            undelivered_reason=None, rearm_count=record.rearm_count + 1,
            rearmed_at=stamp, updated_at=stamp,
        )
        _write(updated)
        return RearmResult.REARMED, updated


def resolve_settle_id(
    *, settle_id: Any = None, client_message_id: Any = None, session_id: Any = None
) -> str | None:
    """The record key from either addressing ``settle_ack`` accepts, or ``None``."""

    if isinstance(settle_id, str) and settle_id.strip():
        return settle_id.strip()
    if isinstance(client_message_id, str) and client_message_id.strip():
        session = session_id if isinstance(session_id, str) and session_id.strip() else None
        return settle_id_for(session, client_message_id.strip())
    return None


def resolve_settle_ref(ref: Any, *, session_id: Any = None) -> str | None:
    """One positional reference (the argv verb): a stored settle id, else a client message id."""

    clean = str(ref or "").strip()
    if not clean:
        return None
    if session_id is None and paths.chat_turn_settle_path(clean).is_file():
        return clean
    return resolve_settle_id(client_message_id=clean, session_id=session_id)


def settles_listing(*, state: str | None = None) -> dict[str, Any]:
    """``{counts: {pending, undelivered, acked}, settles: [row…]}`` in one directory walk.

    ``counts`` always covers every state; ``state`` filters only the rows. An
    unknown ``state`` raises ``ValueError``.
    """

    if state is not None and state not in _VALID_STATES:
        raise ValueError(f"unknown settle state {state!r}")
    records = list_settles()
    counts = {name: 0 for name in sorted(_VALID_STATES)}
    for record in records:
        counts[record.state] += 1
    rows = [record.as_row() for record in records if state is None or record.state == state]
    return {"counts": counts, "settles": rows}


def ack_settle(settle_id: str) -> bool:
    """Retire a settle. True only on the pending→acked (or undelivered→acked) move."""

    clean = str(settle_id or "").strip()
    if not clean or not paths.chat_turn_settle_path(clean).is_file():
        return False
    with chat_turn_settle_lock(clean):
        record = _read_or_none(clean)
        if record is None or record.state == STATE_ACKED:
            return False
        stamp = _timestamp()
        _write(replace(record, state=STATE_ACKED, acked_at=stamp, next_attempt_at=None, updated_at=stamp))
        return True


def prune_acked(*, older_than_seconds: float, at: datetime | None = None) -> int:
    """Delete ``acked`` records older than the idempotency window. Never raises."""

    moment = at or now()
    removed = 0
    for record in list_settles(state=STATE_ACKED):
        try:
            if (moment - _parse(record.acked_at or record.updated_at)).total_seconds() < older_than_seconds:
                continue
            with chat_turn_settle_lock(record.settle_id):
                paths.chat_turn_settle_path(record.settle_id).unlink(missing_ok=True)
            removed += 1
        except Exception:
            continue
    return removed


def read_settle(settle_id: str) -> SettleRecord | None:
    return _read_or_none(str(settle_id or "").strip())


def list_settles(*, state: str | None = None) -> list[SettleRecord]:
    """Every readable record (optionally one state). An unreadable file is skipped."""

    directory = paths.chat_turn_settles_dir()
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = _read_settle_file(path.stem)
        except Exception:
            continue
        if state is None or record.state == state:
            records.append(record)
    return records


def _read_or_none(settle_id: str) -> SettleRecord | None:
    if not settle_id or not paths.chat_turn_settle_path(settle_id).is_file():
        return None
    return _read_settle_file(settle_id)


def _read_settle_file(settle_id: str) -> SettleRecord:
    raw, state = read_versioned_receipt(
        paths.chat_turn_settle_path(settle_id),
        schema_version=_SCHEMA_VERSION,
        valid_states=_VALID_STATES,
    )
    known = set(SettleRecord.__dataclass_fields__)
    values = {name: raw.get(name) for name in known}
    values["state"] = state
    values["attempts"] = int(raw.get("attempts") or 0)
    values["rearm_count"] = int(raw.get("rearm_count") or 0)
    values["exit_code"] = int(raw.get("exit_code"))
    record = SettleRecord(**values)
    if record.settle_id != settle_id:
        raise ValueError("settle id does not match its path")
    return record


def _write(record: SettleRecord) -> None:
    payload = asdict(record)
    payload["schema_version"] = _SCHEMA_VERSION
    atomic_json_write(paths.chat_turn_settle_path(record.settle_id), payload, indent=2, sort_keys=True)


def _settle_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:_MAX_TEXT_CHARS] if cleaned else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp() -> str:
    return _iso(now())


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
