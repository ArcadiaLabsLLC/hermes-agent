"""The progress adapter: agent callbacks -> progress payloads (the
``callback_event`` routing lives here).
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.profile_runner.errors import RunBudgetExceeded
from agent_runtime.profile_runner.budget import _ToolBudgetGuard
from agent_runtime.profile_runner.tool_payloads import (
    _safe_label,
    _safe_reasoning_summary,
    _tool_finished_payload,
    _tool_started_payload,
)
from agent_runtime.profile_runner.operator_redaction import _is_error_result

__layer__ = "stores"

__all__ = [
    "_progress_adapter",
    "_progress_payload_from_callback",
]


def _progress_adapter(
    callback: Callable[[dict[str, Any]], None] | None,
    event_type: str,
    *,
    guard: _ToolBudgetGuard | None = None,
):
    if callback is None and guard is None:
        return None
    callback = callback or (lambda _payload: None)
    guard = guard or _ToolBudgetGuard()

    def emit(*args, **kwargs):
        try:
            payload = _progress_payload_from_callback(event_type, args, kwargs)
            callback(payload)
            tool_name = str(payload.get("tool_name") or "")
            step = str(payload.get("step") or payload.get("type") or "")
            key = (step, tool_name)
            # Wall-budget gate, evaluated BEFORE a tool execution starts. Unlike
            # every other guard here it does not raise: engaging the checkpoint
            # lands the turn (final reply, typed terminal state) rather than
            # tripping it. The already-signalled tool still runs — this stops
            # the NEXT loop iteration from launching more.
            if guard.wall_checkpoint is not None and step == "tool_started":
                guard.wall_checkpoint.gate()
            if event_type == "run.progress" and tool_name and step in {"tool_started", "tool_finished"}:
                guard.repeated_counts[key] = guard.repeated_counts.get(key, 0) + 1
                if tool_name == "skill_view" and guard.repeated_counts[key] >= guard.skill_warning_threshold and key not in guard.warned:
                    guard.warned.add(key)
                    callback(
                        {
                            "type": event_type,
                            "phase": "runaway_warning",
                            "severity": "warning",
                            "step": "skill_loading_fanout",
                            "tool_name": tool_name,
                            "status": "warning",
                            "summary": "Repeated skill_view calls detected; stop loading additional skills and pivot to the single most relevant skill, proof collection, a bounded handoff, or an exact blocker.",
                            "skill_load_limit": guard.skill_warning_threshold - 1,
                            "next_expected": "stop_skill_loading_and_produce_proof_or_block",
                        }
                    )
                    return None
                if guard.repeated_counts[key] >= 6 and key not in guard.warned:
                    guard.warned.add(key)
                    callback(
                        {
                            "type": event_type,
                            "phase": "runaway_warning",
                            "severity": "warning",
                            "step": "repeated_tool_event",
                            "tool_name": tool_name,
                            "status": "warning",
                            "summary": f"Repeated {step.replace('_', ' ')} for {tool_name}; inspect for a tool loop.",
                        }
                    )
        except RunBudgetExceeded:
            raise
        except Exception:
            return None

    return emit


def _progress_payload_from_callback(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    callback_event = str(args[0]) if args else event_type
    if event_type == "run.tool.started":
        tool_name = _safe_label(args[1]) if len(args) > 1 else None
        invocation = args[2] if len(args) > 2 else kwargs.get("input") or kwargs.get("tool_input")
        return _tool_started_payload(event_type, tool_name, invocation=invocation)
    if event_type == "run.tool.finished":
        tool_name = _safe_label(args[1]) if len(args) > 1 else None
        invocation = args[2] if len(args) > 2 else None
        result = args[3] if len(args) > 3 else None
        return _tool_finished_payload(event_type, tool_name, duration=None, is_error=_is_error_result(result), result=result, invocation=invocation)

    tool_name = _safe_label(args[1]) if len(args) > 1 else None
    if callback_event == "tool.started":
        invocation = args[3] if len(args) > 3 else kwargs.get("input") or kwargs.get("tool_input")
        return _tool_started_payload(event_type, tool_name, invocation=invocation)
    if callback_event == "tool.completed":
        return _tool_finished_payload(event_type, tool_name, duration=kwargs.get("duration"), is_error=bool(kwargs.get("is_error")), result=kwargs.get("result"), invocation=kwargs.get("input") or kwargs.get("tool_input"))
    if callback_event in {"reasoning.available", "_thinking"}:
        payload = {
            "type": event_type,
            "phase": "thinking_process",
            "step": "reasoning_summary",
            "status": "running",
            "summary": "Agent thinking process updated",
        }
        reasoning = _safe_reasoning_summary(args, kwargs)
        if reasoning:
            payload["reasoning_summary"] = reasoning
        return payload
    return {"type": event_type, "phase": "tool", "step": "progress", "status": "running", "summary": "Run progress update"}
