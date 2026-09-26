"""Text curation for one chat message: scaffolding, decision summaries, secrets, display bodies.

Separate because it is the leaf every row shaper calls, and reads nothing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..serde import safe_assignment_text, safe_assignment_token
from ..redaction import mask_secret_lines
from ..redaction_mode import redaction_observe_enabled
from .vocabulary import PERSONA_CHAT_MESSAGE_TEXT_LIMIT, _SECRET_RE

__layer__ = "stores"
__all__ = [
    "_INTERNAL_SCAFFOLDING_MARKERS",
    "_curate_chat_message_text",
    "_safe_display_text",
    "_safe_display_body_text",
]


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
    return mask_secret_lines(str(value or "")).strip()[:limit].rstrip()


def _safe_chat_body_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized[:limit].rstrip()

