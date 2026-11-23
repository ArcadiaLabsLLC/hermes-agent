"""Text curation for one chat message: scaffolding, decision summaries, secrets, display bodies.

Separate because it is the leaf every row shaper calls, and reads nothing.
"""

from __future__ import annotations

import json
import hashlib
import re
from typing import Any

from ..serde import safe_assignment_text, safe_assignment_token
from ..redaction import has_text_secret_assignment, mask_known_key_shapes, mask_secret_lines
from ..redaction_mode import redaction_observe_enabled

__layer__ = "stores"
__all__ = [
    "_INTERNAL_SCAFFOLDING_MARKERS",
    "_curate_chat_message_text",
    "_safe_display_body_text",
    "_safe_display_text",
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

    # Every text this returns has passed the key-shape mask exactly once, so the
    # display verdict after it (``_safe_display_body_text(..., masked=True)``) need
    # not run the scrubber a second time (w1122f-agentlist: the second pass was
    # 593 of 1,647 ``mask_known_key_shapes`` calls in a profiled roster build).
    if role == "agent":
        summary = _decision_summary_text(content)
        if summary:
            # MUTATION: return ``summary`` unmasked and
            # test_a_decision_summarys_bare_key_is_masked_in_the_curated_transcript reddens.
            return _safe_chat_body_text(summary, limit=None)
        text = _safe_chat_body_text(content, limit=None)
        if not text or text.startswith("{"):
            # Empty assistant turn or an unparseable raw dict — not presentable.
            return None
        if any(marker in text for marker in _INTERNAL_SCAFFOLDING_MARKERS):
            return None
        return text
    if role == "operator":
        text = _safe_chat_body_text(content, limit=None)
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
    limit: int | None,
    redacted_fallback: str | None = None,
) -> tuple[str, str]:
    # A bare key is hidden BEFORE the cut, so a bound never halves one past the scrubber.
    # MUTATION: pass ``value`` straight to safe_assignment_text and
    # test_a_bare_key_in_a_chat_title_and_preview_is_masked reddens.
    text = safe_assignment_text(mask_known_key_shapes(str(value or "")), limit=limit)
    if not text:
        return fallback, "safe"
    if has_text_secret_assignment(text):
        if redaction_observe_enabled():
            return _mask_secret_lines(text, limit=limit), "would_redact"
        return redacted_fallback or fallback, "redacted"
    return text, "safe"


def _safe_display_body_text(
    value: Any,
    *,
    fallback: str,
    limit: int | None,
    redacted_fallback: str | None = None,
    masked: bool = False,
) -> tuple[str, str]:
    # ``masked``: ``value`` already came out of ``_safe_chat_body_text`` (the
    # curated transcript's ``_curate_chat_message_text``); the mask is idempotent
    # (``mask_known_key_shapes``), so only the bound is applied again.
    text = (str(value or "") if limit is None else str(value or "")[:limit]) if masked else _safe_chat_body_text(
        value, limit=limit)
    if not text:
        return fallback, "safe"
    if has_text_secret_assignment(text):
        if redaction_observe_enabled():
            return _mask_secret_lines(text, limit=limit), "would_redact"
        return redacted_fallback or fallback, "redacted"
    return text, "safe"


def _mask_secret_lines(value: str, *, limit: int | None) -> str:
    return mask_secret_lines(str(value or "")).strip()[:limit].rstrip()


def _safe_chat_body_text(value: Any, *, limit: int | None) -> str:
    # MUTATION: drop mask_known_key_shapes here and
    # test_a_child_s_returned_bare_key_is_masked_in_the_chat_history reddens.
    text = mask_known_key_shapes(str(value or "").replace("\x00", " "))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text if limit is None else text[:limit]


def text_revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def message_preview(row: dict[str, Any], limit: int) -> dict[str, Any]:
    text = row["text"]
    if len(text) <= limit:
        return row
    return {**row, "text": text[:limit], "text_truncated": True,
            "text_total_chars": len(text), "content_ref": {
                "kind": "message", "id": row["id"], "revision": text_revision(text)}}
