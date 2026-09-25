"""The pieces of one agent run's execution around the conversation: agent-ready
notification and cleanup, and the usage-ledger wrapper.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "lanes"

__all__ = [
    "_cleanup_agent_ready",
    "_emit_agent_ready_callback_warning",
    "_notify_agent_ready",
    "_run_conversation_with_usage_ledger",
]


def _notify_agent_ready(request: AgentRunRequest, agent: Any) -> Callable[[], None] | None:
    callback = request.agent_ready_callback
    if callback is None:
        return None
    try:
        return callback(agent)
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="start")
        return None


def _run_conversation_with_usage_ledger(agent: Any, conversation_kwargs: dict[str, Any]) -> Any:
    """Run the turn with a per-call usage ledger and the persona agent bound for plugin
    middleware (dispatch timing, cache routing); a dict result carries the ledger as
    ``usage_ledger``."""
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from agent_runtime.usage_ledger import bind_usage_ledger

    with bind_usage_ledger() as usage_ledger, bind_persona_turn_agent(agent):
        raw_result = agent.run_conversation(**conversation_kwargs)
    if isinstance(raw_result, dict):
        raw_result["usage_ledger"] = list(usage_ledger)
    return raw_result


def _cleanup_agent_ready(cleanup: Callable[[], None] | None, request: AgentRunRequest) -> None:
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception as exc:
        _emit_agent_ready_callback_warning(request, exc, phase="cleanup")


def _emit_agent_ready_callback_warning(request: AgentRunRequest, exc: Exception, *, phase: str) -> None:
    if request.progress_callback is None:
        return
    try:
        request.progress_callback(
            {
                "type": "run.progress",
                "phase": "agent_ready_callback",
                "severity": "warning",
                "step": phase,
                "status": "failed",
                "summary": f"Agent ready callback {phase} failed: {type(exc).__name__}",
            }
        )
    except Exception:
        return
