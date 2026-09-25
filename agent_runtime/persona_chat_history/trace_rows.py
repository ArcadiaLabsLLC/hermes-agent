"""One trace event projected to a redaction-safe operator row.

Separate because it is pure shaping over one event; nothing here reads a store.
"""

from __future__ import annotations

import re
from typing import Any

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..transcript_order import TURN_SEQ_CONTENT
from .vocabulary import (
    DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
    MAX_PERSONA_CHAT_MESSAGE_TAIL,
    _SECRET_RE,
    _TRACE_FETCH_CEILING,
    _TRACE_FETCH_HEADROOM,
)

__layer__ = "policy"
__all__ = [
    "_trace_entry",
    "_bounded_message_tail",
    "_trace_fetch_limit",
]


def _trace_entry(event: Any) -> dict[str, Any] | None:
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        payload = {}
    event_type = safe_assignment_text(getattr(event, "type", None), limit=80)
    trace_event = {
        "run.tool.started": "tool_started",
        "run.tool.finished": "tool_finished",
        "run.progress": "progress",
        "task.transition": "progress",
        "persona_assignment.created": "assignment_created",
        "persona_assignment.closed": "assignment_closed",
    }.get(event_type)
    if trace_event is None:
        return None

    tool_name = _safe_trace_text(payload.get("tool_name") or payload.get("tool"), limit=120)
    summary = _trace_summary(event_type, payload)
    status = _safe_trace_text(payload.get("status") or payload.get("to") or payload.get("exit_code"), limit=80)
    files = _safe_trace_file_labels(payload.get("changed_files") or payload.get("files_touched"))
    turn_id = safe_assignment_text(
        getattr(event, "turn_id", None) or payload.get("turn_id"), limit=160
    )
    return {
        "kind": "harness_trace",
        "task_id": safe_assignment_text(getattr(event, "task_id", None), limit=160),
        "persona_id": safe_assignment_token(getattr(event, "persona_id", None)) or "unknown",
        "run_id": safe_assignment_text(getattr(event, "run_id", None), limit=160),
        "turn_id": turn_id,
        # C8 ordering key: turn-anchored trace content sits in the content band
        # (after the turn's operator row, before its terminal reply) so the
        # launcher's history+trace merge sorts on the key, never on the skew
        # between SessionDB stamps and this trace clock (F17).
        **({"turn_seq": TURN_SEQ_CONTENT} if turn_id else {}),
        "stage_id": _safe_trace_text(payload.get("stage_id"), limit=120),
        "event": trace_event,
        "tool_name": tool_name,
        "summary": summary,
        "files": files,
        "status": status,
        "ts": getattr(event, "ts", None),
        # Operator-console detail lane (Mission Control only): real command,
        # tool target, bounded output tail, and full changed paths — the
        # per-line secret scrub already ran at the progress sink. Key names
        # mirror what the launcher's trace item parser already reads.
        "command": _safe_trace_operator_line(
            payload.get("command_full") or payload.get("command_label"), limit=500
        ),
        # Per-step reasoning from the thinking callback. "_thinking" is the
        # legacy placeholder some historical events recorded — never content.
        "reasoning_summary": (
            None
            if payload.get("reasoning_summary") == "_thinking"
            else _safe_trace_operator_line(payload.get("reasoning_summary"), limit=500)
        ),
        "target": _safe_trace_operator_line(payload.get("target_label"), limit=300),
        # First-class agent-to-agent dispatch (G2): structured target persona +
        # the FULL order, carried straight from the agent_chat_send progress
        # payload. dispatch_order keeps its newline structure (block scrub), so
        # the console renders the whole briefing, not the 90-char target excerpt.
        "dispatch_target": _safe_trace_operator_line(payload.get("dispatch_target"), limit=120),
        "dispatch_order": _safe_trace_operator_block(payload.get("dispatch_order"), limit=1500),
        # Where the relay landed (finished event, WAITING lane only). This makes
        # the dispatch tile navigable — the console opens this thread rather than
        # re-deriving one from the order prose. A detached dispatch carries none,
        # and the tile stays a read-only record.
        "dispatch_target_session_id": _safe_trace_operator_line(
            payload.get("dispatch_target_session_id"), limit=240
        ),
        # ...and the ANSWER (finished event, WAITING lane only): the teammate's
        # reply plus the display name of the agent who sent it, so the console
        # renders the exchange rather than only the order. 1600 sits ABOVE the
        # producer's 1500 for the same reason the tool_input/tool_result limits
        # below sit above theirs — the sink's truncation marker can inflate the
        # producer bound, and a re-truncation here would cut the head, which is
        # this record's operator signal.
        "dispatch_reply": _safe_trace_operator_block(payload.get("dispatch_reply"), limit=1600),
        "dispatch_reply_from": _safe_trace_operator_line(
            payload.get("dispatch_reply_from"), limit=120
        ),
        # Patch observability: the local diff artifact's PATH (operator-line
        # scrub — paths ALLOWED, secret-bearing values still dropped; the
        # pathish-dropping `_safe_trace_text` would be wrong here and is right
        # for the mode token below), plus the +/− counts and the grammar used.
        # The diff BODY is not here and is not anywhere on this wire.
        "patch_artifact": _safe_trace_operator_line(payload.get("patch_artifact"), limit=500),
        "patch_adds": _safe_trace_int(payload.get("patch_adds")),
        "patch_dels": _safe_trace_int(payload.get("patch_dels")),
        "patch_mode": _safe_trace_text(payload.get("patch_mode"), limit=20),
        "detail": _safe_trace_operator_line(payload.get("detail"), limit=500),
        "output": _safe_trace_operator_block(payload.get("output"), limit=1600),
        # Generic tool input/result record (tools with no dedicated field):
        # key-per-line blocks; block scrub keeps line structure so the console
        # dropdown renders one key per line. Limits sit ABOVE the progress-sink
        # ceiling (1100/1700 + its truncation marker, which can inflate the
        # producer bound by re-redacting lines with the broader marker set) so
        # this tail-bounded scrub never truncates — a truncation here would cut
        # the HEAD, which is this record's operator signal.
        "tool_input": _safe_trace_operator_block(payload.get("tool_input"), limit=1200),
        "tool_result": _safe_trace_operator_block(payload.get("tool_result"), limit=1800),
        "paths": _safe_trace_operator_paths(payload.get("changed_paths")),
        "duration_ms": _safe_trace_int(payload.get("duration_ms")),
        "exit_code": _safe_trace_int(payload.get("exit_code")),
        "skill_id": _safe_trace_text(payload.get("skill_name"), limit=120),
        "assignment_id": _safe_trace_text(payload.get("assignment_id"), limit=160),
        "persona_instance_id": _safe_trace_text(payload.get("persona_instance_id"), limit=160),
        "title": _safe_trace_text(payload.get("title"), limit=240),
        "message": _safe_trace_text(payload.get("message"), limit=1200),
        "repo": _safe_trace_text(payload.get("repo"), limit=160),
        "affected_paths": _safe_trace_file_labels(payload.get("affected_paths")),
        "proof_targets": _safe_trace_list_text(payload.get("proof_targets"), limit=240),
        "acceptance": _safe_trace_list_text(payload.get("acceptance"), limit=500),
        "non_goals": _safe_trace_list_text(payload.get("non_goals"), limit=500),
        "allowed_decisions": _safe_trace_list_text(payload.get("allowed_decisions"), limit=80),
    }


def _first_safe_trace_text(*values: Any, limit: int) -> str | None:
    for value in values:
        safe = _safe_trace_text(value, limit=limit)
        if safe:
            return safe
    return None


def _trace_summary(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type.startswith("run.tool."):
        return _first_safe_trace_text(
            payload.get("command_label"),
            payload.get("file_summary"),
            payload.get("patch_summary"),
            payload.get("code_summary"),
            payload.get("summary"),
            limit=500,
        )
    if event_type == "run.progress":
        summary = _safe_trace_text(payload.get("summary"), limit=500)
        if summary in {"Run progress update.", "Run progress update"}:
            return None
        return summary
    return _first_safe_trace_text(
        payload.get("reason") if event_type == "task.transition" else None,
        payload.get("summary"),
        payload.get("patch_summary"),
        payload.get("code_summary"),
        payload.get("command_label"),
        payload.get("file_summary"),
        limit=500,
    )


def _safe_trace_text(value: Any, *, limit: int) -> str | None:
    text = safe_assignment_text(value, limit=limit)
    if not text:
        return None
    if _SECRET_RE.search(text) or _looks_pathish(text):
        return None
    return text


def _safe_trace_operator_line(value: Any, *, limit: int) -> str | None:
    """Operator-console single line: paths allowed, secrets blocked, bounded."""

    text = " ".join(str(value or "").strip().split())
    if not text or _SECRET_RE.search(text):
        return None
    return f"{text[: limit - 1]}…" if len(text) > limit else text


def _safe_trace_operator_block(value: Any, *, limit: int) -> str | None:
    """Operator-console multi-line block (command output): keeps line structure,
    redacts secret-bearing lines, tail-bounded."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    lines = [
        "[redacted line — contained a secret]" if _SECRET_RE.search(line) else line
        for line in text.split("\n")
    ]
    text = "\n".join(lines)
    if len(text) > limit:
        text = f"…(earlier output truncated)…\n{text[-limit:]}"
    return text


def _safe_trace_operator_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    for item in value:
        text = " ".join(str(item or "").strip().split()).replace("\\", "/")
        if not text or _SECRET_RE.search(text):
            continue
        if len(text) > 200:
            text = f"…{text[-199:]}"
        if text not in paths:
            paths.append(text)
        if len(paths) >= 12:
            break
    return paths


def _safe_trace_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_trace_file_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        text = safe_assignment_text(item, limit=120)
        if not text:
            continue
        if _SECRET_RE.search(text) or _looks_pathish(text):
            continue
        label = text.replace("\\", "/").rsplit("/", 1)[-1]
        if not label or _SECRET_RE.search(label) or _looks_pathish(label):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", label):
            continue
        labels.append(label)
    return labels[:12]


def _safe_trace_list_text(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = safe_assignment_text(item, limit=limit)
        if not text or _SECRET_RE.search(text):
            continue
        items.append(text)
    return items[:12]


def _looks_pathish(value: str) -> bool:
    if ":/" in value or "\\" in value or value.startswith(("/", "~")):
        return True
    return bool(re.search(r"(^|\s)([A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+", value))


def _bounded_message_tail(value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = DEFAULT_PERSONA_CHAT_MESSAGE_TAIL
    return min(max(parsed, 1), MAX_PERSONA_CHAT_MESSAGE_TAIL)


def _trace_fetch_limit(tail: int, member_count: int) -> int:
    """Size the per-task event fetch so each agent can reach ``tail`` trace rows.

    The task's EventLog interleaves every agent's events plus non-trace rows
    (worker_session.*, heartbeats, …), so a flat window starves quiet agents.
    Scale by the agent count with headroom for that dilution, then hard-cap so
    the reverse file scan stays bounded.
    """

    agents = max(int(member_count or 0), 1)
    return min(max(tail * agents * _TRACE_FETCH_HEADROOM, tail), _TRACE_FETCH_CEILING)
