"""The hot lane: every mirror write, and the file's cheap-or-deliberate creation.

``mirrored_persona_chat_append`` (THE seam a durable append wraps),
``record_chat_message``, ``record_chat_tool`` and ``ensure_chat_live_log``.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Iterator

from agent_runtime.chat_live_log.backfill import _complete_backfill, _create_log
from agent_runtime.chat_live_log.files import (
    _already_recorded,
    _append_line,
    _backfill_pending,
    _exists,
    _mark_recorded,
    _with_claim,
    chat_live_log_path,
)
from agent_runtime.chat_live_log.lines import (
    _logical_client_key,
    _mirror_text,
    _normalized_role,
    _now_iso,
    _relay_sender_fields,
    _safe_session_token,
    _safe_token,
)

__layer__ = "lanes"



# ── writes (hot lane) ───────────────────────────────────────────────────────


@contextlib.contextmanager
def mirrored_persona_chat_append(
    *,
    session_db: Any = None,
    session_id: Any,
    role: Any,
    text: Any,
    client_message_id: Any = None,
    turn_id: Any = None,
    relay_marker: Any = None,
) -> Iterator[None]:
    """Wrap a durable persona-chat append so its mirror line rides the write.

    THE seam for "a row was explicitly appended to a persona-chat session".
    Every such site wraps its ``session_db.append_message`` in this, so a new
    append site cannot land a row that is invisible in the live log — which is
    exactly what happened to the child return-summary lane
    (``agent_runtime.continuity``) while the mirror was hooked by call-site
    convention instead of by a seam.

    Records only on a clean exit: a failed durable write leaves the mirror
    silent, because the mirror must never claim a message the transcript of
    record rejected.
    """

    yield
    record_chat_message(
        session_id=session_id,
        role=role,
        text=text,
        turn_id=turn_id,
        client_message_id=client_message_id,
        relay_marker=relay_marker,
        session_db=session_db,
    )


def record_chat_message(
    *,
    session_id: Any,
    role: Any,
    text: Any,
    turn_id: Any = None,
    client_message_id: Any = None,
    relay_marker: Any = None,
    steered: bool = False,
    session_db: Any = None,
) -> bool:
    """Append one persisted chat message to the live mirror.

    Idempotent for a given ``(role, logical client_message_id)`` pair, which is
    what makes the replay / resend lanes safe to route through here without
    doubling rows. The key is the LOGICAL turn id: the runtime's native flush
    stamps assistant rows ``<client_message_id>:assistant:<n>`` while the live
    hooks carry the bare id, so a raw comparison would let a materialized file
    and a live append both claim the same reply.
    """

    token = _safe_session_token(session_id)
    if not token:
        return False
    safe_text = _mirror_text(text)
    if not safe_text:
        return False
    path = ensure_chat_live_log(token, session_db=session_db)
    if path is None:
        return False

    normalized_role = _normalized_role(role)
    client_key = _logical_client_key(client_message_id)
    if client_key and _already_recorded(token, path, (normalized_role, client_key)):
        return True

    payload: dict[str, Any] = {
        "ts": _now_iso(),
        "kind": "message",
        "role": normalized_role,
        "text": safe_text,
    }
    turn_token = _safe_token(turn_id, limit=240)
    if turn_token:
        payload["turn_id"] = turn_token
    if client_key:
        payload["client_message_id"] = client_key
    if steered:
        # Typed, not inferred from position: a steer is text injected into a
        # turn ALREADY RUNNING, so a reader must be able to tell it from the
        # order that opened the turn.
        payload["steered"] = True
    payload.update(_relay_sender_fields(relay_marker))
    if not _append_line(path, payload):
        return False
    if client_key:
        _mark_recorded(token, (normalized_role, client_key))
    return True


def record_chat_tool(
    *,
    session_id: Any,
    tool: Any,
    status: Any,
    turn_id: Any = None,
    session_db: Any = None,
) -> bool:
    """Append one compact tool-activity line.

    This is what makes the mirror answer "what is it doing RIGHT NOW" instead of
    only "what did it say" — a head agent tailing the file during a long
    teammate turn sees tool starts/finishes land as they happen.
    """

    token = _safe_session_token(session_id)
    if not token:
        return False
    tool_name = _safe_token(tool, limit=120)
    if not tool_name:
        return False
    path = ensure_chat_live_log(token, session_db=session_db)
    if path is None:
        return False
    payload: dict[str, Any] = {
        "ts": _now_iso(),
        "kind": "tool",
        "tool": tool_name,
        "status": _safe_token(status, limit=60) or "unknown",
    }
    turn_token = _safe_token(turn_id, limit=240)
    if turn_token:
        payload["turn_id"] = turn_token
    return _append_line(path, payload)


# ── file lifecycle: create cheap, materialize deliberately ──────────────────


def ensure_chat_live_log(
    session_id: Any, *, session_db: Any = None, materialize: bool = False
) -> Path | None:
    """Return the mirror path, creating (and optionally materializing) it.

    ``materialize=False`` is the CHAT HOT PATH: a missing file is created with
    nothing but a ``backfill_pending`` header. O(1) — no projection read, no
    turn-journal parsing — so a chat turn is never taxed by the size of the
    thread it belongs to.

    ``materialize=True`` is the TOOL lane (``agent_chat_log_path``): a missing
    file is built from the SAME projection ``agent_chat_open`` reads
    (``persona_chat_session_messages``, which redacts at read), and a file whose
    header still says ``backfill_pending`` gets its history filled in — once —
    ahead of the live lines it already holds.

    Both paths publish through a claim file + ``os.replace``, so a concurrent
    appender sees either no file or a complete one and never has its own line
    overwritten by a creator's later buffered flush.
    """

    path = chat_live_log_path(session_id, session_db=session_db)
    if path is None:
        return None
    token = _safe_session_token(session_id) or ""

    if _exists(path):
        if not materialize or not _backfill_pending(path):
            return path
        completed = _with_claim(
            path,
            lambda claim: _complete_backfill(
                path, claim, session_id=token, session_db=session_db
            ),
        )
        return completed or path

    published = _with_claim(
        path,
        lambda claim: _create_log(
            path, claim, session_id=token, session_db=session_db, materialize=materialize
        ),
    )
    if published is not None:
        return published
    return path if _exists(path) else None
