"""Text curation for one chat message: scaffolding, decision summaries, secrets, display bodies.

Separate because it is the leaf every row shaper calls, and reads nothing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..redaction_mode import redaction_observe_enabled
from .vocabulary import PERSONA_CHAT_MESSAGE_TEXT_LIMIT, _SECRET_RE

__layer__ = "policy"
__all__ = [
    "_iso_timestamp",
    "_INTERNAL_SCAFFOLDING_MARKERS",
    "_curate_chat_message_text",
    "_safe_message_role",
    "_safe_display_text",
    "_safe_display_body_text",
    "_safe_int",
]


def _iso_timestamp(value: Any) -> str | None:
    """Normalize SessionDB timestamps to the same ISO-8601 ``Z`` form as traces.

    SessionDB stores message timestamps as epoch-seconds floats (``time.time()``),
    while harness-trace rows carry ISO strings (``Event.ts`` via ``to_jsonable``).
    The Launcher merges the two channels by parsing each ``ts`` with
    ``DateTime.tryParse`` and orders them — an epoch float is unparseable there, so
    without this the curated rows lose their time and the trace block jumps
    ahead of them. Project message and session timestamps in one comparable UTC
    format, and never pass raw unparseable values through the snapshot contract.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    from datetime import datetime, timezone

    def _format(moment: datetime) -> str:
        return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return _format(moment)
    if isinstance(value, (int, float)):
        epoch = float(value)
        if epoch > 1e12:  # tolerate millisecond clocks
            epoch /= 1000.0
        try:
            return _format(datetime.fromtimestamp(epoch, tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            epoch = float(text)
        except ValueError:
            pass
        else:
            if epoch > 1e12:  # tolerate millisecond clocks
                epoch /= 1000.0
            try:
                return _format(datetime.fromtimestamp(epoch, tz=timezone.utc))
            except (OverflowError, OSError, ValueError):
                return None
        parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(parse_text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _format(parsed)
    return None


# Markers that identify the agent's internal scaffolding (never operator-facing).
_INTERNAL_SCAFFOLDING_MARKERS = (
    "# Agent Runtime Tick Context",
    "## Task Snapshot",
    "Repo-Grounded Execution",
    "Prior persona chat context",
    "[CONTEXT COMPACTION — REFERENCE ONLY]",
)


def _curate_chat_message_text(role: str, content: Any) -> str | None:
    """Project a raw agent-session row into clean operator-facing text.

    Agent rows that are serialized decision dicts collapse to their summary
    (+ rationale); operator rows that are internal tick-context scaffolding are
    dropped (the clean operator message is shown via the optimistic UI path).
    Returns ``None`` for rows that should not appear in the operator transcript.
    """

    if role == "agent":
        summary = _decision_summary_text(content)
        if summary:
            return summary
        text = _safe_chat_body_text(content, limit=PERSONA_CHAT_MESSAGE_TEXT_LIMIT)
        if not text or text.startswith("{"):
            # Empty assistant turn or an unparseable raw dict — not presentable.
            return None
        if any(marker in text for marker in _INTERNAL_SCAFFOLDING_MARKERS):
            return None
        return text
    if role == "operator":
        text = _safe_chat_body_text(content, limit=PERSONA_CHAT_MESSAGE_TEXT_LIMIT)
        if not text:
            return None
        if any(marker in text for marker in _INTERNAL_SCAFFOLDING_MARKERS):
            return None
        return text
    return None


def _decision_summary_text(content: Any) -> str | None:
    raw = content if isinstance(content, str) else str(content or "")
    raw = raw.strip()
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    parts = [
        str(data[key]).strip()
        for key in ("summary", "rationale")
        if isinstance(data.get(key), str) and str(data.get(key)).strip()
    ]
    if not parts:
        return None
    return "\n\n".join(parts)


def _safe_message_role(value: Any) -> str | None:
    role = safe_assignment_token(value)
    if role in {"user", "operator"}:
        return "operator"
    if role in {"assistant", "agent"}:
        return "agent"
    if role == "system":
        return "system"
    return None


def _safe_display_text(
    value: Any,
    *,
    fallback: str,
    limit: int,
    redacted_fallback: str | None = None,
) -> tuple[str, str]:
    text = safe_assignment_text(value, limit=limit)
    if not text:
        return fallback, "safe"
    if _SECRET_RE.search(text):
        if redaction_observe_enabled():
            return _mask_secret_lines(text, limit=limit), "would_redact"
        return redacted_fallback or fallback, "redacted"
    return text, "safe"


def _safe_display_body_text(
    value: Any,
    *,
    fallback: str,
    limit: int,
    redacted_fallback: str | None = None,
) -> tuple[str, str]:
    text = _safe_chat_body_text(value, limit=limit)
    if not text:
        return fallback, "safe"
    if _SECRET_RE.search(text):
        if redaction_observe_enabled():
            return _mask_secret_lines(text, limit=limit), "would_redact"
        return redacted_fallback or fallback, "redacted"
    return text, "safe"


def _mask_secret_lines(value: str, *, limit: int) -> str:
    lines = [
        "[redacted line — contained a secret]" if _SECRET_RE.search(line) else line
        for line in str(value or "").split("\n")
    ]
    text = "\n".join(lines).strip()
    return text[:limit].rstrip()


def _safe_chat_body_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized[:limit].rstrip()


def _safe_int(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(parsed, 0)
