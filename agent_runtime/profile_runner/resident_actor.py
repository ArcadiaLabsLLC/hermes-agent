"""The resident persona chat actor's prepare/finish around a run, and the user
row marker a chat turn stages.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_runtime._upstream_doors import sanitize_surrogates
from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "lanes"

__all__ = [
    "log_turn_effort",
    "turn_reasoning_config",
    "_finish_resident_persona_chat_agent",
    "_prepare_resident_persona_chat_agent",
    "_sanitized_user_message_text",
    "stage_persona_chat_user_row_marker",
]


def _prepare_resident_persona_chat_agent(agent: Any, turn_state: dict[str, Any]) -> None:
    """Refresh turn-scoped state without erasing native compressor memory.

    ``turn_state`` is the per-turn values resolved from the REQUEST (see
    ``_execute_agent_run``), not read back off a freshly constructed agent. That
    distinction is the whole of T3: the seven values below are the only thing a
    resident actor ever wanted from the candidate, and building a ~1.5 s agent to
    carry them across — then discarding it — was the cost of the warm lane.
    """

    for name, value in turn_state.items():
        if hasattr(agent, name):
            setattr(agent, name, value)
    for name in (
        "session_prompt_tokens", "session_completion_tokens", "session_total_tokens",
        "session_api_calls", "session_input_tokens", "session_output_tokens",
        "session_cache_read_tokens", "session_cache_write_tokens",
        "session_reasoning_tokens", "session_estimated_cost_usd", "_api_call_count",
    ):
        if hasattr(agent, name):
            setattr(agent, name, 0.0 if name.endswith("cost_usd") else 0)
    for name, value in (
        ("_stream_callback", None), ("_interrupt_requested", False),
        ("_interrupt_reason", None), ("_current_api_request_id", ""),
        ("_current_turn_id", None), ("_current_task_id", None),
    ):
        if hasattr(agent, name):
            setattr(agent, name, value)


def _finish_resident_persona_chat_agent(agent: Any) -> None:
    """Detach every turn-local handle while preserving conversation state."""

    for name in (
        "status_callback",
        "tool_progress_callback",
        "tool_start_callback",
        "tool_complete_callback",
        "clarify_callback",
        "_stream_callback",
    ):
        if hasattr(agent, name):
            setattr(agent, name, None)
    for name, value in (
        ("_interrupt_requested", False),
        ("_interrupt_reason", None),
        ("_current_api_request_id", ""),
        ("_current_turn_id", None),
        ("_current_task_id", None),
        ("_persona_chat_client_message_id", None),
        ("_persona_chat_turn_id", None),
        ("_pending_cli_user_message", None),
    ):
        if hasattr(agent, name):
            setattr(agent, name, value)


def _sanitized_user_message_text(text: str) -> str:
    """The prologue's own view of this turn's clean user text.

    ``build_turn_context`` sanitizes surrogates BEFORE comparing the staged
    message below, so an unsanitized copy of a surrogate-bearing message would
    silently fail the match and drop the marker. Falls back to the raw text if
    the upstream helper ever moves — a no-op for every non-surrogate message.
    """

    try:
        return sanitize_surrogates(text)
    except Exception:  # pragma: no cover - upstream helper relocated, or defensive
        return text


def stage_persona_chat_user_row_marker(
    agent: Any, request: "AgentRunRequest"
) -> dict[str, Any] | None:
    """Stage this turn's user-message dict so its NATIVE row carries a marker.

    Since native session continuity landed, the mission-chat lane no longer
    appends the incoming operator row itself — the runtime persists it as part
    of the turn. ``build_turn_context`` adopts an already-staged
    ``_pending_cli_user_message`` whose clean text matches this turn's message,
    appends THAT dict as the turn's user message, and preserves every extra key
    on it; the session flush then writes ``finish_reason=msg.get(
    "finish_reason")`` onto the persisted row. Staging here is therefore the one
    seam where a fork-owned lane can TYPE the row the runtime writes — no second
    write, no duplicate row, and the model's prompt is untouched.

    Always writes the attribute: a stale dict left on a RESIDENT chat agent
    would otherwise be adopted by a later turn. No marker (every operator/CLI
    send) clears it, and the turn behaves exactly as it did before attribution
    existed. Returns the staged dict, or ``None`` when nothing was staged.
    """

    marker = getattr(request, "persona_chat_user_finish_reason", None)
    if (
        not marker
        # The retry lane reuses a row that is already durable (and already
        # carries the marker from the attempt that wrote it); re-staging would
        # be a no-op the prologue never reads.
        or request.reuse_current_user_message
        or not isinstance(request.user_message, str)
    ):
        agent._pending_cli_user_message = None
        return None
    staged = {
        "role": "user",
        "content": _sanitized_user_message_text(request.user_message),
        "finish_reason": str(marker),
    }
    agent._pending_cli_user_message = staged
    return staged


_logger = logging.getLogger(__name__)


def turn_reasoning_config(request: AgentRunRequest, model: str | None) -> dict | None:
    """The instance's effort when the request carries one, else the ACTIVE profile's
    ``agent.reasoning_effort`` (per-model override first) — the chokepoint every
    upstream surface uses. Before this, a run without an instance effort passed
    nothing and the codex transport sent its own ``medium`` whatever the profile said.
    Runs inside the persona's profile scope, so ``load_config`` is that profile's.
    The resolution itself is :func:`agent_runtime.persona_chat_session.reasoning_config_for`
    (the stores layer, which the effective-model payload reads too)."""

    from agent_runtime.persona_chat_session import reasoning_config_for

    return reasoning_config_for(request.reasoning_effort, model)


def log_turn_effort(request: AgentRunRequest, agent: Any, *, reused: bool) -> None:
    """Receipt the reasoning effort this run's agent will send, and where it came from."""

    from agent_runtime.persona_chat_session import TURN_EFFORT_RECEIPT, reasoning_effort_label

    model = getattr(agent, "model", None) or request.model
    effort = reasoning_effort_label(getattr(agent, "reasoning_config", None))
    source = "instance" if request.reasoning_effort else ("profile" if effort else "default")
    actor = "prewarm" if request.prewarm_only else ("reused" if reused else "built")
    _logger.info(TURN_EFFORT_RECEIPT, request.root_chat_session_id or request.session_id or "-",
                 request.turn_id or "-", model or "-", request.reasoning_effort or "-",
                 effort or "-", source, actor)
