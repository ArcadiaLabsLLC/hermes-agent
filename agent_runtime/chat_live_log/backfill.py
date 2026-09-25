"""The tool lane's materialization, and the read-backs over the header it writes.

``_backfill_rows`` (the paged projection walk, bounded on rows and wall),
``_create_log`` / ``_complete_backfill`` (a file built, or completed, from it
under a claim), ``chat_live_log_stats``. Only the tool lane reaches the walk —
never a chat turn.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_runtime.chat_live_log.files import (
    _exists,
    _note_failure,
    _publish,
    chat_live_log_path,
)
from agent_runtime.chat_live_log.lines import (
    _backfilled_delivery_fields,
    _decode_lines,
    _iso_or_now,
    _logical_client_key,
    _mirror_text,
    _normalized_role,
    _now_iso,
    _safe_token,
)

__layer__ = "lanes"


#: Upper bound on rows materialized by the backfill (tool lane only).
LIVE_LOG_BACKFILL_MESSAGE_CAP = 4000
#: Wall budget for that materialization. The tool lane is a deliberate agent
#: request so it can afford seconds — but never unbounded: a pathological
#: session must not hang the caller's tool call.
LIVE_LOG_BACKFILL_WALL_SECONDS = 15.0


def _create_log(
    path: Path,
    claim: Path,
    *,
    session_id: str,
    session_db: Any,
    materialize: bool,
) -> Path | None:
    if _exists(path):  # someone published while we were claiming
        return path
    rows: list[dict[str, Any]] = []
    truncated = False
    if materialize:
        rows, truncated = _backfill_rows(session_id, session_db=session_db)
    header = {
        "ts": _now_iso(),
        "kind": "log_opened",
        "session_id": session_id,
        "backfilled": len(rows),
        # The honesty flag the tool lane keys on: history has NOT been
        # materialized, so this file starts mid-conversation.
        "backfill_pending": not materialize,
    }
    if truncated:
        header["backfill_truncated"] = True
    return _publish(path, claim, [header] + rows)


def _complete_backfill(
    path: Path, claim: Path, *, session_id: str, session_db: Any
) -> Path | None:
    """Fill history in ahead of the live lines a hot-path-created file holds."""

    try:
        with open(path, "rb") as handle:
            existing = handle.read()
    except OSError as exc:
        _note_failure("read_existing", exc)
        return None
    carried = [row for row in _decode_lines(existing) if row.get("kind") != "log_opened"]
    rows, truncated = _backfill_rows(session_id, session_db=session_db)
    # A live line and a materialized row can name the same message (the row was
    # persisted, mirrored live, and is now also in the projection). The live
    # line wins — it is the one already handed to whoever is tailing the file.
    live_keys = {
        (_normalized_role(row.get("role")), str(row.get("client_message_id") or ""))
        for row in carried
        if row.get("kind") == "message" and row.get("client_message_id")
    }
    rows = [
        row
        for row in rows
        if not row.get("client_message_id")
        or (_normalized_role(row.get("role")), str(row["client_message_id"])) not in live_keys
    ]
    header = {
        "ts": _now_iso(),
        "kind": "log_opened",
        "session_id": session_id,
        "backfilled": len(rows),
        "backfill_pending": False,
    }
    if truncated:
        header["backfill_truncated"] = True
    # Second pass over anything appended while the projection was being read.
    # This shrinks the lost-append window from "however long the projection
    # takes" to "however long one seek+read takes"; it does not eliminate it,
    # and the file is regenerable either way.
    try:
        with open(path, "rb") as handle:
            handle.seek(len(existing))
            late = handle.read()
    except OSError:
        late = b""
    return _publish(path, claim, [header] + rows + carried + _decode_lines(late))


def _backfill_rows(
    session_id: str, *, session_db: Any = None
) -> tuple[list[dict[str, Any]], bool]:
    """Materialize history from the projection. Returns ``(rows, truncated)``.

    Bounded on BOTH axes. Each page re-runs the full curated projection (which
    re-parses the turn journal per row), so an unbounded walk over a long
    session is measured in seconds — affordable on a deliberate tool call, never
    on a chat turn, which is why only the tool lane reaches here.
    """

    if not session_id:
        return [], False
    try:
        from ..persona_chat_history import (
            MAX_PERSONA_CHAT_MESSAGE_TAIL,
            persona_chat_session_messages,
        )
    except Exception:  # pragma: no cover - defensive
        return [], False

    deadline = time.monotonic() + LIVE_LOG_BACKFILL_WALL_SECONDS
    pages: list[list[dict[str, Any]]] = []
    before: str | None = None
    total = 0
    truncated = False
    while True:
        if total >= LIVE_LOG_BACKFILL_MESSAGE_CAP or time.monotonic() > deadline:
            truncated = True
            break
        try:
            data = persona_chat_session_messages(
                session_id=session_id,
                limit=MAX_PERSONA_CHAT_MESSAGE_TAIL,
                before=before,
                session_db=session_db,
            )
        except Exception:
            break
        if not isinstance(data, dict) or not data.get("ok"):
            break
        page = [row for row in (data.get("messages") or []) if isinstance(row, dict)]
        if page:
            pages.append(page)
            total += len(page)
        before = data.get("next_before")
        if not data.get("has_more") or not before:
            break

    rows: list[dict[str, Any]] = []
    for page in reversed(pages):
        for message in page:
            text = _mirror_text(message.get("text"))
            if not text:
                continue
            payload: dict[str, Any] = {
                "ts": _iso_or_now(message.get("timestamp")),
                "kind": "message",
                "role": _normalized_role(message.get("role")),
                "text": text,
                "backfilled": True,
            }
            turn_token = _safe_token(message.get("turn_id"), limit=240)
            if turn_token:
                payload["turn_id"] = turn_token
            client_token = _logical_client_key(message.get("client_message_id"))
            if client_token:
                payload["client_message_id"] = client_token
            for key in ("relay_sender_persona_id", "relay_sender_instance_id"):
                value = _safe_token(message.get(key), limit=160)
                if value:
                    payload[key] = value
            # A backfilled delivery must be indistinguishable from a live one to
            # a consumer — that is the only thing that makes mixing the two
            # safe. The read projection names these facts `delivery_*` (it is
            # feeding the conversation contract); the mirror names them
            # `origin`/`dispatch_*`. TRANSLATE rather than copy: a blind
            # key-for-key copy would silently write nothing, because the two
            # vocabularies do not share a single key name.
            payload.update(_backfilled_delivery_fields(message))
            rows.append(payload)
    return rows, truncated


# ── reads ───────────────────────────────────────────────────────────────────


def chat_live_log_stats(session_id: Any, *, session_db: Any = None) -> dict[str, Any] | None:
    """Size / message-count / last-activity for one mirror, or ``None``.

    Counts only ``kind == "message"`` lines so the number is comparable to what
    ``agent_chat_open`` would report; tool lines are counted separately.
    """

    path = chat_live_log_path(session_id, session_db=session_db)
    if path is None:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    message_count = 0
    tool_count = 0
    last_activity: str | None = None
    backfill_pending = False
    backfill_truncated = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                kind = row.get("kind")
                if kind == "message":
                    message_count += 1
                elif kind == "tool":
                    tool_count += 1
                elif kind == "log_opened":
                    backfill_pending = bool(row.get("backfill_pending"))
                    backfill_truncated = bool(row.get("backfill_truncated"))
                stamp = row.get("ts")
                if isinstance(stamp, str) and stamp:
                    last_activity = stamp
    except OSError as exc:
        _note_failure("read", exc)
        return None
    rotated = path.with_name(path.name + ".1")
    return {
        "path": str(path),
        "bytes": size,
        "message_count": message_count,
        "tool_count": tool_count,
        "last_activity": last_activity,
        "backfill_pending": backfill_pending,
        # Two distinct ways history can be incomplete, kept distinct: never
        # materialized at all, versus materialized up to a declared bound.
        "backfill_truncated": backfill_truncated,
        "rotated_path": str(rotated) if _exists(rotated) else None,
    }
