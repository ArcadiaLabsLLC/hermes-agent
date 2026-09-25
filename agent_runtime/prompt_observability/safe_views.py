"""Bounded, redacted views of what the model was sent and what it cost.

Separate because every field here validates a foreign dict once, at the
boundary, and nothing here reads a store.
"""

from __future__ import annotations

import re
from typing import Any

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..serde import non_negative_int
from ..redaction import TEXT_SECRET_VALUE_ASSIGNMENT_RE

__layer__ = "policy"
__all__ = [
    "SAFE_PREVIEW_LIMIT",
    "DEFAULT_CHAT_HISTORY_LIMIT",
    "_safe_final_model_input",
    "_safe_user_message_wire",
    "_safe_system_prompt_sections",
    "_safe_cache_routing",
    "_safe_turn_usage",
    "turn_usage_from_result",
    "_chat_history_context",
    "_safe_preview",
]


SAFE_PREVIEW_LIMIT = 1200


DEFAULT_CHAT_HISTORY_LIMIT = 8


def _safe_final_model_input(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    messages = value.get("messages") if isinstance(value.get("messages"), list) else []
    safe_messages = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = _safe_prompt_body(message.get("content"), limit=65000)
        safe_messages.append(
            {
                "role": safe_assignment_token(message.get("role")) or "message",
                "source": safe_assignment_token(message.get("source")) or "model_input",
                "content": content,
                "truncated": bool(message.get("truncated")),
                "bytes": non_negative_int(message.get("bytes")),
                "sha256": safe_assignment_token(message.get("sha256")),
            }
        )
    return {
        "schema_version": non_negative_int(value.get("schema_version")) or 1,
        "kind": safe_assignment_token(value.get("kind")) or "redaction_safe_final_model_input",
        "platform": safe_assignment_token(value.get("platform")),
        "profile": safe_assignment_token(value.get("profile")),
        "session_id": safe_assignment_text(value.get("session_id"), limit=200),
        "task_id": safe_assignment_token(value.get("task_id")),
        "skip_context_files": bool(value.get("skip_context_files")),
        "skip_memory": bool(value.get("skip_memory")),
        "system_message_supplied": bool(value.get("system_message_supplied")),
        "message_count": non_negative_int(value.get("message_count")) or len(safe_messages),
        "messages": safe_messages,
        "system_prompt_sections": _safe_system_prompt_sections(
            value.get("system_prompt_sections")
        ),
        # Tool schemas ship in full on every API call and are the largest fixed
        # slice of the prompt after the system prompt. This whitelist previously
        # dropped them, which is why the context budget could not see (or
        # estimate) them at all.
        "tool_schema": _safe_tool_schema(value.get("tool_schema")),
        "cache_routing": _safe_cache_routing(value.get("cache_routing")),
        # T4: the wire-vs-composed receipt for this turn's user row. Tiny, typed,
        # and load-bearing — without it a reader cannot tell whether the captured
        # user message is what the model received or only what the turn composed.
        "user_message_wire": _safe_user_message_wire(value.get("user_message_wire")),
        # T5: the live compaction threshold. Whitelisted (not merely passed
        # through) because the deferred-refresh path at
        # `_context_budget_needs_refresh` re-derives the budget from the SAFE
        # row — dropping it here would make a refreshed budget silently fall
        # back to the static window x ratio number the lane cap overrides.
        "context_compaction": _safe_context_compaction(value.get("context_compaction")),
    }


def _safe_context_compaction(value: Any) -> dict[str, Any] | None:
    """Redaction-safe copy of the live-compressor compaction row. Ints only."""

    if not isinstance(value, dict):
        return None
    effective = non_negative_int(value.get("effective_threshold_tokens"))
    if not effective or effective <= 0:
        return None
    row: dict[str, Any] = {
        "schema_version": non_negative_int(value.get("schema_version")) or 1,
        "effective_threshold_tokens": effective,
    }
    for key in ("threshold_tokens_cap", "context_length"):
        number = non_negative_int(value.get(key))
        if number:
            row[key] = number
    if "compression_in_place" in value:
        row["compression_in_place"] = bool(value.get("compression_in_place"))
    return row


def _safe_user_message_wire(value: Any) -> dict[str, Any] | None:
    """Bounded projection of the T4 wire receipt. ``None`` for an absent one.

    Absent means the producer did not record it (an older row, a non-runner
    lane) — an honest absence the reader renders as "unknown", never a
    fabricated ``bounded: False`` that would read as proof the wire matched.
    """

    if not isinstance(value, dict):
        return None
    receipt: dict[str, Any] = {
        "schema_version": non_negative_int(value.get("schema_version")) or 1,
        "source": safe_assignment_token(value.get("source")) or "unknown",
        "composed_chars": non_negative_int(value.get("composed_chars")),
        "wire_chars": non_negative_int(value.get("wire_chars")),
        "bounded": bool(value.get("bounded")),
    }
    reason = safe_assignment_token(value.get("unavailable_reason"))
    if reason:
        receipt["unavailable_reason"] = reason
    return receipt


# The assignment rule is single-homed in ``agent_runtime.redaction`` (see the
# header there for the JSON blind spot every local spelling shared). Two-group
# contract preserved — the substitution below branches on ``lastindex >= 2``.
_OBSERVABILITY_PROMPT_SECRET_PATTERNS = [
    TEXT_SECRET_VALUE_ASSIGNMENT_RE,
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)\b(xox[baprs]-[A-Za-z0-9-]{12,})\b"),
]


def _safe_prompt_body(value: Any, *, limit: int) -> str:
    """Redact prompt text while preserving its readable line structure."""

    text = str(value or "").replace("\x00", " ")
    for pattern in _OBSERVABILITY_PROMPT_SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (
                f"{match.group(1)}=<redacted>"
                if match.lastindex and match.lastindex >= 2
                else "<redacted>"
            ),
            text,
        )
    return text[:limit]


def _safe_system_prompt_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        start = non_negative_int(item.get("start_char"))
        end = non_negative_int(item.get("end_char"))
        chars = non_negative_int(item.get("chars"))
        if start is None or end is None or start < 0 or end < start:
            continue
        result.append(
            {
                "kind": safe_assignment_token(item.get("kind")) or "section",
                "name": safe_assignment_text(item.get("name"), limit=80)
                or "Prompt section",
                "start_char": start,
                "end_char": end,
                "chars": chars,
                "truncated": item.get("truncated") is True,
            }
        )
    return result


def _safe_cache_routing(value: Any) -> dict[str, Any] | None:
    """Whitelist the one-way cache-routing diagnostics.

    No raw cache key, session id, or header value is accepted by this boundary;
    only transport-produced fingerprints, presence bits, and typed provenance
    survive into SessionDB-reachable prompt observability.
    """

    if not isinstance(value, dict):
        return None
    return {
        "schema_version": non_negative_int(value.get("schema_version")) or 1,
        "backend": safe_assignment_token(value.get("backend")),
        "prompt_cache_key_present": value.get("prompt_cache_key_present") is True,
        "prompt_cache_key_source": safe_assignment_token(
            value.get("prompt_cache_key_source")
        ),
        "prompt_cache_key_fingerprint": _safe_cache_fingerprint(
            value.get("prompt_cache_key_fingerprint")
        ),
        "cache_scope_source": safe_assignment_token(value.get("cache_scope_source")),
        "session_header_present": value.get("session_header_present") is True,
        "session_header_fingerprint": _safe_cache_fingerprint(
            value.get("session_header_fingerprint")
        ),
        "client_request_header_present": value.get("client_request_header_present")
        is True,
        "client_request_header_fingerprint": _safe_cache_fingerprint(
            value.get("client_request_header_fingerprint")
        ),
        "scope_headers_match": value.get("scope_headers_match")
        if isinstance(value.get("scope_headers_match"), bool)
        else None,
        "raw_values_omitted": True,
    }


def _safe_cache_fingerprint(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    prefix = "sha256:"
    digest = text[len(prefix) :] if text.startswith(prefix) else ""
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return None
    return f"{prefix}{digest}"


_TURN_USAGE_FIELDS = (
    "api_calls",
    "prompt_tokens",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "first_call_prompt_tokens",
)


def _safe_turn_usage(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Key-whitelisted, int-coerced turn usage. All ints — nothing to redact."""
    if not isinstance(value, dict):
        return None
    safe = {field: non_negative_int(value.get(field)) for field in _TURN_USAGE_FIELDS}
    if all(number is None for number in safe.values()):
        return None
    return safe


def turn_usage_from_result(result: Any) -> dict[str, int] | None:
    """Shape an ``AgentRunResult`` into the envelope's ``turn_usage`` block.

    Mission Control builds a fresh runtime per turn, so the result's totals ARE
    this turn's totals, and ``usage_ledger[0]`` is the turn's FIRST API call —
    the one whose prompt is exactly the assembled context (system + user + tool
    schemas) with no tool-result loop growth yet. That single number is what the
    context budget must show; the sums are what the message cost.

    Lives here, beside the envelope contract it feeds, rather than in the CLI
    lane (`hermes_cli/harness_parts/persona/`), which only reads it.
    """
    if result is None:
        return None
    ledger = getattr(result, "usage_ledger", None)
    first_call_prompt: int | None = None
    if isinstance(ledger, list) and ledger and isinstance(ledger[0], dict):
        candidate = ledger[0].get("prompt_tokens")
        if isinstance(candidate, int) and candidate > 0:
            first_call_prompt = candidate

    def _count(name: str) -> int:
        value = getattr(result, name, None)
        return value if isinstance(value, int) and value > 0 else 0

    input_tokens = _count("input_tokens")
    cache_read_tokens = _count("cache_read_tokens")
    cache_write_tokens = _count("cache_write_tokens")
    usage = {
        "api_calls": _count("api_calls"),
        # prompt = input + cache_read + cache_write (CanonicalUsage's own
        # definition — input_tokens is already the uncached remainder).
        "prompt_tokens": input_tokens + cache_read_tokens + cache_write_tokens,
        "input_tokens": input_tokens,
        "output_tokens": _count("output_tokens"),
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": _count("reasoning_tokens"),
        "first_call_prompt_tokens": first_call_prompt,
    }
    if not any(value for value in usage.values()):
        return None
    return usage


_SAFE_TOOL_NAME_LIMIT = 120


def _safe_tool_schema(value: Any) -> dict[str, Any] | None:
    """Redaction-safe tool-schema summary: names + count + wire size.

    Never carries the schema bodies (they can embed paths/enums); the byte size
    is what the context budget needs.
    """
    if not isinstance(value, dict):
        return None
    names: list[str] = []
    raw_names = value.get("final_model_tools")
    if isinstance(raw_names, list):
        for entry in raw_names[:_SAFE_TOOL_NAME_LIMIT]:
            token = safe_assignment_token(entry)
            if token:
                names.append(token)
    return {
        "schema_version": non_negative_int(value.get("schema_version")) or 1,
        "kind": safe_assignment_token(value.get("kind")) or "actual_model_tools",
        "final_model_tools": names,
        "tool_count": non_negative_int(value.get("tool_count")),
        "json_bytes": non_negative_int(value.get("json_bytes")),
    }


def _chat_history_context(*, session_db: Any | None, session_id: str | None) -> list[dict[str, Any]]:
    if session_db is None or not session_id:
        return []
    try:
        messages = session_db.get_messages(session_id)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for item in (messages or [])[-DEFAULT_CHAT_HISTORY_LIMIT:]:
        if not isinstance(item, dict):
            continue
        role = safe_assignment_token(item.get("role")) or "message"
        content = safe_assignment_text(item.get("content"), limit=SAFE_PREVIEW_LIMIT)
        if not content:
            continue
        rows.append(
            {
                "role": "operator" if role == "user" else role,
                "text": _safe_preview(content),
                "timestamp": safe_assignment_text(item.get("created_at") or item.get("timestamp"), limit=80),
                "source": "persona_chat_history",
            }
        )
    return rows


def _safe_preview(text: str) -> str:
    safe = safe_assignment_text(text, limit=SAFE_PREVIEW_LIMIT) or ""
    safe = safe.replace("\r\n", "\n").replace("\r", "\n")
    return safe[:SAFE_PREVIEW_LIMIT]
