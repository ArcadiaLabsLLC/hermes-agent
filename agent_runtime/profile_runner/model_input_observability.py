"""Chat compaction and model-input observability: the compaction threshold and
receipt, the model-input record, system-prompt section receipts, cache-routing
and skills-prompt accounting, and prompt redaction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
import re

from agent_runtime.redaction import TEXT_SECRET_VALUE_ASSIGNMENT_RE

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "stores"

__all__ = [
    "CHAT_COMPACTION_RECEIPT_KIND",
    "_PROMPT_SECRET_PATTERNS",
    "_agent_cache_routing_observability",
    "_agent_tool_names",
    "_agent_tools_json_bytes",
    "_apply_chat_compaction_threshold",
    "_attach_model_input_observability",
    "_chat_compaction_observability",
    "_current_turn_user_row",
    "_message_preview",
    "_model_input_observability",
    "_redact_prompt_text",
    "_rendered_skills_prompt_chars",
    "_system_prompt_section_receipts",
    "_wire_user_message",
]


#: Receipt kind stamped on every chat-lane compaction decision, so a reader can
#: tell an intentional threshold from a default it happened to inherit.
CHAT_COMPACTION_RECEIPT_KIND = "chat_compaction_threshold"


def _apply_chat_compaction_threshold(
    compressor: Any, threshold_tokens: int, *, source: str
) -> dict[str, Any]:
    """Decide — once — when THIS chat root compacts, and return the receipt.

    Two callers, two different contracts, one function so they cannot drift:

    * ``turn_override`` — an explicit ``--compression-threshold-tokens`` on the
      turn. It is an operator instruction and wins in BOTH directions, so it is
      written the way it always was: the live threshold plus the equivalent
      ``threshold_percent``, which is what carries the intent through a model
      switch (``update_model`` recomputes from the percent).
    * ``lane_default`` — the harness-wide
      ``agent_runtime.mission_chat.compaction_threshold_tokens``. It is a CAP,
      never a floor, so it goes through ``threshold_tokens_cap``: the compressor
      takes the LOWER of its ratio-based threshold and the cap, re-applies it on
      every ``update_model``, and clamps a cap larger than the window to a no-op.
      A small-window model therefore keeps its own (already earlier) threshold —
      the lane can only make compaction fire sooner, never later.

    ``threshold_tokens <= 0`` on the lane path is the documented "no lane cap"
    spelling: the model-derived threshold stands and the receipt says so. It is
    never an error, because the rollback for this whole feature is writing a 0.

    Never raises: a compressor that does not expose these attributes (a stub, a
    future refactor) yields an ``unavailable`` receipt rather than failing a turn
    over an accounting knob.
    """

    receipt: dict[str, Any] = {
        "kind": CHAT_COMPACTION_RECEIPT_KIND,
        "schema_version": 1,
        "source": source,
        "requested_tokens": int(threshold_tokens) if threshold_tokens else 0,
    }
    try:
        model_threshold = int(getattr(compressor, "threshold_tokens", 0) or 0)
        context_length = int(getattr(compressor, "context_length", 0) or 0)
    except Exception:  # pragma: no cover - defensive; accounting must not fail a turn
        receipt["applied"] = False
        receipt["reason"] = "unavailable"
        return receipt
    receipt["model_threshold_tokens"] = model_threshold
    receipt["context_length"] = context_length

    if source == "turn_override":
        compressor.threshold_tokens = int(threshold_tokens)
        if context_length > 0:
            compressor.threshold_percent = int(threshold_tokens) / context_length
    elif int(threshold_tokens or 0) <= 0:
        receipt["applied"] = False
        receipt["reason"] = "lane_cap_disabled"
        receipt["effective_threshold_tokens"] = model_threshold
        return receipt
    else:
        # The cap is a first-class field on the compressor, not a one-time
        # patch — writing it is what makes the bound survive a model switch.
        compressor.threshold_tokens_cap = int(threshold_tokens)
        effective_cap = int(threshold_tokens)
        if context_length > 0:
            effective_cap = min(effective_cap, context_length)
        if model_threshold > 0 and effective_cap < model_threshold:
            compressor.threshold_tokens = effective_cap

    try:
        effective = int(getattr(compressor, "threshold_tokens", 0) or 0)
    except Exception:  # pragma: no cover - defensive
        effective = model_threshold
    receipt["effective_threshold_tokens"] = effective
    if source == "turn_override":
        receipt["applied"] = effective != model_threshold
        return receipt
    # ``applied`` answers "does the lane cap govern this root", NOT "did this
    # call change a number". The distinction is load-bearing on the warm serve
    # lane: a RESIDENT actor is reused across turns (T3), so from turn 2 onward
    # the compressor already holds the capped value — and a did-it-change reading
    # would report the cap as inactive, and blame the model for it, on every turn
    # after the first. The state is the fact; the write is an implementation
    # detail of the first turn that saw this actor.
    governing = min(int(threshold_tokens), context_length or int(threshold_tokens))
    receipt["applied"] = effective == governing
    if not receipt["applied"]:
        # A cap that does not govern is the healthy small-window case, not a
        # silent failure. Name it so a reader is not left inferring.
        receipt["reason"] = "model_threshold_already_lower"
    return receipt


def _chat_compaction_observability(agent: Any) -> dict[str, Any] | None:
    """What the LIVE compressor will actually compact at, read at send time.

    Separate from the decision receipt on purpose: the receipt says what this
    turn asked for, this says what the object holds when the prompt goes out.
    They are the same number on a healthy turn — and a launcher rendering
    "compaction at 892,500" while the compressor holds 150,000 is exactly the
    kind of divergence the T4 wire-vs-record work exists to make impossible.
    """

    compressor = getattr(agent, "context_compressor", None)
    if compressor is None:
        return None
    try:
        effective = int(getattr(compressor, "threshold_tokens", 0) or 0)
    except Exception:  # pragma: no cover - defensive
        return None
    if effective <= 0:
        return None
    row: dict[str, Any] = {
        "schema_version": 1,
        "effective_threshold_tokens": effective,
    }
    try:
        cap = getattr(compressor, "threshold_tokens_cap", None)
        if cap:
            row["threshold_tokens_cap"] = int(cap)
        context_length = int(getattr(compressor, "context_length", 0) or 0)
        if context_length > 0:
            row["context_length"] = context_length
        row["compression_in_place"] = bool(getattr(agent, "compression_in_place", True))
    except Exception:  # pragma: no cover - defensive
        pass
    return row


def _attach_model_input_observability(raw_result: Any, *, agent, request: AgentRunRequest) -> None:
    if not isinstance(raw_result, dict):
        return
    raw_result.setdefault("model_input_observability", _model_input_observability(agent=agent, request=request))


def _model_input_observability(*, agent, request: AgentRunRequest) -> dict[str, Any]:
    system_prompt = getattr(agent, "_cached_system_prompt", None)
    if not system_prompt and hasattr(agent, "_build_system_prompt"):
        try:
            system_prompt = agent._build_system_prompt(request.system_message)
        except Exception:
            system_prompt = request.system_message or ""
    messages: list[dict[str, Any]] = []
    system_prompt_sections: list[dict[str, Any]] = []
    if system_prompt:
        system_preview = _message_preview(
            "system", str(system_prompt), source="hermes_system_prompt"
        )
        messages.append(system_preview)
        system_prompt_sections = _system_prompt_section_receipts(
            agent=agent,
            system_message=request.system_message,
            system_prompt=str(system_prompt),
            captured_content=system_preview["content"],
        )
    # T4 (2026-08-09): record the WIRE, not the composition. ``request.user_message``
    # is what the turn COMPOSED; the persona-chat persistence boundary
    # (``persona_chat_continuity.safe_native_message``) may bound it in place on
    # the live actor BEFORE the first provider call, so the composed text is not
    # what the model received. Recording the composition is what let the 20k-char
    # amputation (F1) run live and invisibly for weeks — the record showed a
    # 56 KB user turn the provider metered at 4.2 k tokens.
    wire_user_message, wire_receipt = _wire_user_message(agent=agent, request=request)
    messages.append(
        _message_preview("user", wire_user_message, source="mission_chat_user_message")
    )
    cache_routing = _agent_cache_routing_observability(agent)
    return {
        # Typed provenance for the row above: which copy it is, how the composed
        # and wire sizes compare, and — when they differ — that the boundary
        # bounded this turn. Never a silent fallback: an unavailable wire row
        # says so instead of quietly recording the composition as if it were the
        # wire.
        "user_message_wire": wire_receipt,
        # T5 (2026-08-09): the threshold this root will actually compact at,
        # read off the live compressor. `prompt_observability._context_budget`
        # prefers it over the static `window x compaction_ratio` derivation,
        # which does not know the lane cap exists and reported 892,500 while the
        # compressor held 150,000.
        "context_compaction": _chat_compaction_observability(agent),
        "schema_version": 1,
        "kind": "redaction_safe_final_model_input",
        "platform": request.platform,
        "profile": request.profile,
        "session_id": request.session_id,
        "task_id": request.task_id,
        "enabled_toolsets": list(request.enabled_toolsets or []),
        "disabled_toolsets": list(request.disabled_toolsets or []),
        "tool_schema": {
            "schema_version": 1,
            "kind": "actual_model_tools",
            "final_model_tools": _agent_tool_names(agent),
            "tool_count": len(_agent_tool_names(agent)),
            # Wire size of the tool schemas, which ship in FULL on every API call
            # (agent/conversation_loop.py passes tools=agent.tools each time).
            # Names alone hid the largest fixed slice of the prompt from the
            # context inspector. Same measurement as `hermes prompt-size`.
            "json_bytes": _agent_tools_json_bytes(agent),
        },
        **({"cache_routing": cache_routing} if cache_routing is not None else {}),
        "skip_context_files": bool(request.skip_context_files),
        "skip_memory": bool(request.skip_memory),
        "system_message_supplied": request.system_message is not None,
        "message_count": len(messages),
        "messages": messages,
        **(
            {"system_prompt_sections": system_prompt_sections}
            if system_prompt_sections
            else {}
        ),
        # T8 (2026-07-18): the rendered compact skills-index text's char count —
        # what ``.skills_prompt_snapshot.json`` ACTUALLY contributed to the
        # prompt this turn, distinct from the loaded-file byte estimate the
        # context-file row carries (the 41 KB snapshot renders to ~9 KB of index
        # text in the prompt). Measured against the AGENT's own resolved tool
        # set so the launcher attributes the real in-prompt cost, not the file
        # size. Omitted (never fabricated) when unmeasurable. See
        # ``_rendered_skills_prompt_chars``.
        **(
            {"skills_prompt_chars": _skills_chars}
            if (_skills_chars := _rendered_skills_prompt_chars(agent)) is not None
            else {}
        ),
    }


def _current_turn_user_row(agent: Any) -> tuple[dict[str, Any] | None, str | None]:
    """This turn's user row as the agent actually holds it, or a typed reason.

    ``_persist_user_message_idx`` is the agent's OWN pointer at the current
    turn's user message (``agent/turn_context.py``, re-anchored after preflight
    compression), so it names the exact dict every provider call for this turn
    reads — including after an in-place boundary rewrite. It is used rather than
    "the last user row" because a todo-snapshot or injected row appended after
    the turn's message would otherwise steal the capture.
    """

    messages = getattr(agent, "messages", None)
    if not isinstance(messages, list):
        return None, "no_message_list"
    index = getattr(agent, "_persist_user_message_idx", None)
    if not isinstance(index, int):
        return None, "no_turn_index"
    if index < 0 or index >= len(messages):
        return None, "index_out_of_range"
    row = messages[index]
    if not isinstance(row, dict) or str(row.get("role") or "").lower() != "user":
        return None, "row_not_a_user_row"
    return row, None


def _wire_user_message(*, agent: Any, request: AgentRunRequest) -> tuple[str, dict[str, Any]]:
    """The user text this turn actually SUBMITTED, plus a typed receipt.

    Returns ``(text, receipt)``. ``receipt["source"]`` is ``agent_wire`` when the
    text was read off the agent's own current-turn row and ``request_composed``
    when it could not be (with ``receipt["unavailable_reason"]`` naming which
    of the five typed reasons ``_current_turn_user_row`` returns applied —
    that function is the vocabulary's only producer, so it is also its only
    authority).

    ``bounded`` is the alarm this exists to raise: the composed and wire sizes
    differ, so something between composition and the wire rewrote the turn. On
    the persona-chat lane that is the per-envelope bound in
    ``persona_chat_continuity``; anywhere else it is a finding.
    """

    composed = request.user_message if isinstance(request.user_message, str) else str(
        request.user_message or ""
    )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "source": "request_composed",
        "composed_chars": len(composed),
        "wire_chars": len(composed),
        "bounded": False,
    }
    row, reason = _current_turn_user_row(agent)
    if row is None:
        receipt["unavailable_reason"] = reason
        return composed, receipt
    content = row.get("content")
    if not isinstance(content, str):
        receipt["unavailable_reason"] = "content_not_text"
        return composed, receipt
    receipt["source"] = "agent_wire"
    receipt["wire_chars"] = len(content)
    receipt["bounded"] = len(content) != len(composed)
    return content, receipt


def _system_prompt_section_receipts(
    *,
    agent: Any,
    system_message: str | None,
    system_prompt: str,
    captured_content: str,
) -> list[dict[str, Any]]:
    """Return exact offsets for Hermes' stable/context/volatile prompt tiers.

    The profile runner may restore a cached system prompt from SessionDB.  We
    therefore re-render the three canonical parts only to prove byte equality;
    if they do not join to the exact prompt sent this turn, no section metadata
    is emitted.  Offsets target the already-redacted captured message so the
    Launcher can slice it without duplicating the full prompt on the wire.
    """

    try:
        from agent.system_prompt import build_system_prompt_parts

        parts = build_system_prompt_parts(agent, system_message=system_message)
    except Exception:
        return []
    ordered = [
        ("stable", "Stable Hermes foundation", str(parts.get("stable") or "")),
        ("context", "Mission Control context", str(parts.get("context") or "")),
        ("volatile", "Volatile profile context", str(parts.get("volatile") or "")),
    ]
    nonempty = [(kind, name, value) for kind, name, value in ordered if value]
    if "\n\n".join(value for _, _, value in nonempty) != system_prompt:
        return []

    safe_parts = [
        (kind, name, _redact_prompt_text(value)) for kind, name, value in nonempty
    ]
    safe_joined = "\n\n".join(value for _, _, value in safe_parts)
    if not safe_joined.startswith(captured_content):
        return []

    receipts: list[dict[str, Any]] = []
    cursor = 0
    capture_length = len(captured_content)
    for kind, name, value in safe_parts:
        start = cursor
        end = start + len(value)
        if start < capture_length:
            captured_end = min(end, capture_length)
            receipts.append(
                {
                    "kind": kind,
                    "name": name,
                    "start_char": start,
                    "end_char": captured_end,
                    "chars": len(value),
                    "truncated": captured_end < end,
                }
            )
        cursor = end + 2
    return receipts


def _agent_cache_routing_observability(agent) -> dict[str, Any] | None:
    """Read the agent-owned redaction-safe final-request cache facts.

    The request builder copies these from the short-lived Responses transport
    only after request overrides and provider-specific header/body routing.
    Other transports and test doubles simply omit the block; absence is honest
    and never fabricated.
    """

    value = getattr(agent, "_last_cache_routing_observability", None)
    return dict(value) if isinstance(value, dict) else None


def _rendered_skills_prompt_chars(agent) -> int | None:
    """Char count of the compact skills index this turn actually rendered.

    Recomputes ``build_skills_system_prompt`` with the AGENT's own resolved tool
    set — byte-for-byte the same call ``agent/system_prompt.py`` made while
    assembling this turn's system prompt, so it is a guaranteed in-process LRU
    cache HIT: zero re-scan, zero disk I/O, zero snapshot write (this runs inside
    the persona profile-home override, so the cache key matches the turn's). The
    result is the EXACT rendered text, not a size heuristic.

    Returns ``None`` (the launcher then omits the in-prompt chip and keeps the
    loaded-file estimate) when the lane ships no skills tools, the render is
    empty, or anything is unmeasurable — never a fabricated number."""

    try:
        valid = getattr(agent, "valid_tool_names", None)
        if not valid:
            return None
        # Mirror the gate in agent/system_prompt.py: the skills index only
        # renders when the lane ships one of the skills tools.
        if not any(name in valid for name in ("skills_list", "skill_view", "skill_manage")):
            return None
        import run_agent
        from agent import prompt_builder

        avail_toolsets = {
            toolset
            for toolset in (run_agent.get_toolset_for_tool(name) for name in valid)
            if toolset
        }
        try:
            from agent.coding_context import coding_compact_skill_categories
            from agent.runtime_cwd import resolve_context_cwd

            compact = (
                coding_compact_skill_categories(
                    platform=getattr(agent, "platform", None), cwd=resolve_context_cwd()
                )
                or None
            )
        except Exception:
            compact = None
        rendered = prompt_builder.build_skills_system_prompt(
            available_tools=valid,
            available_toolsets=avail_toolsets,
            compact_categories=compact,
        )
        if not isinstance(rendered, str):
            return None
        return len(rendered)
    except Exception:
        return None


def _agent_tools_json_bytes(agent) -> int | None:
    """UTF-8 byte size of the serialized tool schemas, or None if unmeasurable."""
    try:
        tools = list(getattr(agent, "tools", None) or [])
        if not tools:
            return 0
        return len(json.dumps(tools, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return None


def _agent_tool_names(agent) -> list[str]:
    names: list[str] = []
    for tool in list(getattr(agent, "tools", []) or []):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return sorted(names)


def _message_preview(role: str, content: str, *, source: str) -> dict[str, Any]:
    raw = str(content or "")
    safe = _redact_prompt_text(raw)
    encoded = safe.encode("utf-8", errors="replace")
    limit = 60000
    preview = safe
    truncated = False
    if len(encoded) > limit:
        preview = encoded[:limit].decode("utf-8", errors="ignore")
        truncated = True
    return {
        "role": role,
        "source": source,
        "content": preview,
        "truncated": truncated,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest().upper(),
    }


# The assignment rule is single-homed in ``agent_runtime.redaction`` (see the
# header there for the JSON blind spot every local spelling shared). This lane
# captures the FINAL MODEL PROMPT for observability, so a JSON-encoded
# credential inside a prompt used to be persisted verbatim. The two-group
# contract is preserved — ``_redact_prompt_text`` branches on ``lastindex >= 2``
# to decide between ``key=<redacted>`` and a whole-match ``<redacted>``.
_PROMPT_SECRET_PATTERNS = [
    TEXT_SECRET_VALUE_ASSIGNMENT_RE,
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)\b(xox[baprs]-[A-Za-z0-9-]{12,})\b"),
]


def _redact_prompt_text(value: str) -> str:
    text = value
    for pattern in _PROMPT_SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=<redacted>" if match.lastindex and match.lastindex >= 2 else "<redacted>", text)
    return text
