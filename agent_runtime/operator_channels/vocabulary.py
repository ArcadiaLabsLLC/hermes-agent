"""The Agent Console projection's words and the safe coercions that read them."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..models import PersonaInstance
from ..persona_chat_history.vocabulary import (
    PERSONA_TURN_BUDGET_EXHAUSTED_KIND,
    PERSONA_TURN_INTERRUPTED_KIND,
)
from ..redaction import TEXT_SECRET_ASSIGNMENT_RE
from ..serde import safe_assignment_text

__layer__ = "policy"


OPERATOR_CHANNELS_SCHEMA_VERSION = 1
# v2: goal-run turn flow — thinking_summary / turn / tool_call / turns_collapsed
# message kinds projected from run summaries + the task trace lane, so a live
# goal reads as a conversation instead of a lone goal_input bubble.
OPERATOR_CONVERSATION_SCHEMA_VERSION = 2

# Hard per-channel message budget. Flow kinds (turn/tool/thinking/progress) are
# trimmed oldest-first past this cap; operator/reply/proof/blocker/handoff/final
# and goal_input are protected. A turns_collapsed marker records the trim.
_CONVERSATION_MESSAGE_CAP = 200
_CONVERSATION_TRIMMABLE_KINDS = {"thinking_summary", "turn", "tool_call", "agent_update"}
_TOOL_OK_STATUSES = {"passed", "ok", "completed", "success", "succeeded", "done"}
_TOOL_FAILED_STATUSES = {"failed", "error", "blocked", "crashed", "timeout"}

_CHAT_INSTANCE_MODES = {"chat", "free_floating"}

# ── terminal turn markers, as the conversation contract renders them ─────────
#
# Keyed on the marker kind ``persona_chat_history`` synthesizes (see
# ``TERMINAL_TURN_MARKERS`` there — that table is the producer, this one the
# presenter). ``status`` and ``display_title`` are the wire values the Launcher
# adapter already reads (``mission_agent_chat_adapter.dart``:
# ``_turnInterruptedFlowMessage`` / ``_budgetExhaustedFlowMessage``), so no
# launcher change is required to render either marker.
_TERMINAL_TURN_MARKER_PRESENTATION = {
    PERSONA_TURN_INTERRUPTED_KIND: {
        "status": "interrupted",
        "display_title": "Turn interrupted",
    },
    PERSONA_TURN_BUDGET_EXHAUSTED_KIND: {
        "status": "budget_exhausted",
        "display_title": "Wall budget reached",
    },
}
# The status a still-``running`` tool_call is settled to when its turn ended.
# ``interrupted`` describes the CALL — it was cut off and will never finish —
# and is the only settled-tool vocabulary the Launcher's trace renderer already
# knows (``mission_trace_content_renderer.dart``: interrupted|cancelled|
# canceled|aborted → stop glyph). The turn-level reason (graceful wall-budget
# checkpoint vs. a killed turn) is carried separately as ``settled_reason``, so
# a settled call never has to lie about WHY to stop spinning.
_SETTLED_TOOL_CALL_STATUS = "interrupted"

# Single-homed in ``agent_runtime.redaction`` — see the header there for the
# JSON blind spot every local spelling shared. Detection only here (a matching
# line is dropped whole), so the shared pattern's group(2) is inert.
_SECRET_RE = TEXT_SECRET_ASSIGNMENT_RE
_TELEMETRY_SUMMARY_RE = re.compile(
    r"(?i)\b("
    r"agent init|provider client|provider responses|provider stream|provider call|"
    r"agent thinking process|agent decision process|"
    r"persona runtime|profile conversation call|profile runtime|profile agent|profile result normalize|"
    r"profile budget checks|conversation request build|conversation provider dispatch|"
    r"conversation response validate|conversation pre api hook|context build|autonomy packet|prompt render|"
    r"api mode setup|core state setup|tool setup|session setup|memory skill setup|"
    r"final state setup|decision apply"
    r")\b"
)


def _safe_conversation_text(value: Any, *, limit: int) -> str | None:
    text = str(value or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Mask secret-bearing lines in place instead of dropping the whole message —
    # a dev rationale that quotes one env assignment must not vanish wholesale.
    # Preserve intra-line whitespace on the survivors: conversation text carries
    # code blocks and aligned output whose indentation must reach the display.
    lines = [
        "[redacted line — contained a secret]"
        if _SECRET_RE.search(line)
        else line.rstrip()
        for line in text.split("\n")
    ]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    if not normalized:
        return None
    if len(normalized) > limit:
        # Truncation must be visible, never silent. Single-line marker: this
        # sanitizer also feeds single-line fields (titles, list items).
        normalized = normalized[:limit].rstrip() + " … [truncated]"
    return normalized


def _safe_conversation_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    safe: list[str] = []
    for item in value:
        text = _safe_conversation_text(item, limit=limit)
        if text:
            safe.append(text)
    return safe[:8]


def _conversation_message_sort_key(message: dict[str, Any]) -> tuple[int, str, str]:
    if message.get("kind") == "goal_input":
        return (0, "", str(message.get("id") or ""))
    parsed = _parse_time(message.get("timestamp"))
    if parsed is not None:
        return (1, parsed.isoformat(), str(message.get("id") or ""))
    return (2, str(message.get("timestamp") or ""), str(message.get("id") or ""))


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_instance_id(instance: PersonaInstance) -> str | None:
    return safe_assignment_text(getattr(instance, "id", None), limit=160)


def _safe_session(value: Any) -> str | None:
    return safe_assignment_text(value, limit=200) or None


def _display_name_from_history(history: dict[str, Any] | None) -> str | None:
    title = safe_assignment_text((history or {}).get("title"), limit=120)
    if title and title.lower().endswith(" chat"):
        return title[:-5].strip() or None
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = safe_assignment_text(value, limit=240)
        if text:
            return text
    return None
