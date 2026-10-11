"""The progress adapter: agent callbacks -> progress payloads (the
``callback_event`` routing lives here).
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
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
from agent_runtime.thinking_echo import is_reply_echo

__layer__ = "stores"

__all__ = [
    "CALLBACK_EVENTS",
    "JOINED_CALLBACK_EVENTS",
    "ProgressBuilder",
    "RUN_EVENTS",
    "ToolFinishJoin",
    "_progress_adapter",
    "_progress_payload_from_callback",
]


#: Upstream callback events that are NOT published on their own: each is one
#: half of a fact whose other half arrives on a ``run.tool.*`` lane, and is
#: folded into that lane's single event by :class:`ToolFinishJoin`.
JOINED_CALLBACK_EVENTS = frozenset({"tool.completed"})


class ToolFinishJoin:
    """One finished tool call, ONE published event.

    Upstream reports a finished call twice, back to back on the thread that
    committed the result: the ``tool.completed`` progress callback (duration and
    the executor's own failure verdict, no call id) and then
    ``tool_complete_callback`` (call id, args, raw result). Both used to be
    published -- ``run.progress`` step ``tool_finished`` and ``run.tool.finished``
    -- and on 2026-10-01 they disagreed about one 160 s build ("failed in
    160297ms" against "passed"). Now the first is HELD here and the second, the
    one every reader folds, claims it: ``run.tool.finished`` is the only
    finished event, carrying the call id, the duration and one verdict.

    Keyed on (thread, tool name) because upstream fires the pair on one thread
    with nothing between them; a FIFO per key so a held half is never claimed
    by a call of another name or on another thread. A held half nobody claims
    (a runtime that fires only ``tool.completed``) dies with the run -- it is
    never published as a second verdict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[tuple[int, str], deque[dict[str, Any]]] = {}

    def hold(self, tool_name: str | None, kwargs: dict[str, Any]) -> None:
        half = {key: kwargs[key] for key in ("duration", "is_error") if key in kwargs}
        with self._lock:
            self._held.setdefault((threading.get_ident(), tool_name or ""), deque()).append(half)

    def claim(self, tool_name: str | None) -> dict[str, Any]:
        key = (threading.get_ident(), tool_name or "")
        with self._lock:
            held = self._held.get(key)
            if not held:
                return {}
            half = held.popleft()
            if not held:
                del self._held[key]
            return half


def _progress_adapter(
    callback: Callable[[dict[str, Any]], None] | None,
    event_type: str,
    *,
    guard: _ToolBudgetGuard | None = None,
    observe: Callable[[tuple[Any, ...], dict[str, Any]], None] | None = None,
    join: ToolFinishJoin | None = None,
):
    """The agent-callback adapter for one event label.

    ``observe(args, payload)`` sees every built payload with the raw callback
    args BEFORE the sink does — the runner's live-turn registry rides it (the
    ``run.tool.*`` args lead with the tool-call id, which no payload carried).
    An observer that raises is swallowed: it is bookkeeping, never the turn.

    ``join`` is the run's :class:`ToolFinishJoin`, shared by the progress and
    the completion adapter: a :data:`JOINED_CALLBACK_EVENTS` callback is held
    there and never published, and ``run.tool.finished`` claims it.
    """

    if callback is None and guard is None:
        return None
    callback = callback or (lambda _payload: None)
    guard = guard or _ToolBudgetGuard()

    def emit(*args, **kwargs):
        try:
            if event_type not in RUN_EVENTS and args and str(args[0]) in JOINED_CALLBACK_EVENTS:
                if join is not None:
                    join.hold(_safe_label(args[1]) if len(args) > 1 else None, kwargs)
                return None
            if event_type not in RUN_EVENTS and args and str(args[0]) == "reasoning.available" and is_reply_echo():
                return None  # the reply relayed as thinking: no Thinking row that repeats the reply
            if join is not None and event_type == "run.tool.finished":
                kwargs = {**join.claim(_safe_label(args[1]) if len(args) > 1 else None), **kwargs}
            payload = _progress_payload_from_callback(event_type, args, kwargs)
            if observe is not None:
                try:
                    observe(args, payload)
                except Exception:
                    pass
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


#: A payload builder: the adapter label, the callback args, the callback kwargs.
ProgressBuilder = Callable[[str, tuple[Any, ...], dict[str, Any]], dict[str, Any]]


def _with_call_id(payload: dict[str, Any], args: tuple[Any, ...]) -> dict[str, Any]:
    """Stamp the tool-call id the ``run.tool.*`` callbacks lead with (``args[0]``)."""

    call_id = _safe_label(args[0]) if args else None
    if call_id:
        payload["tool_call_id"] = call_id
    return payload


def _run_tool_started(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    tool_name = _safe_label(args[1]) if len(args) > 1 else None
    invocation = args[2] if len(args) > 2 else kwargs.get("input") or kwargs.get("tool_input")
    return _with_call_id(_tool_started_payload(event_type, tool_name, invocation=invocation), args)


def _run_tool_finished(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """The ``tool_complete_callback`` lane — the ONLY finished-tool event, and
    the one the chat stream and the conversation's ``tool_call`` rows fold.

    Upstream hands this callback the tool's RESULT STRING (``function_result``,
    the JSON the model reads), never a dict. Read raw, the verdict, exit code
    and output were all invisible: a 160 s ``flutter build`` that FAILED was
    recorded ``passed`` with no exit code, no output and no duration while its
    ``run.progress`` twin said ``failed in 160297ms`` (RW5, live receipts
    2026-10-01). The verdict now reads the decoded envelope, and that twin is
    gone (:class:`ToolFinishJoin`): its ``duration`` and the executor's
    ``is_error`` arrive here as kwargs, and the one verdict is ``failed`` when
    EITHER the executor or the envelope says so -- no second event is left to
    say otherwise.
    """

    tool_name = _safe_label(args[1]) if len(args) > 1 else None
    invocation = args[2] if len(args) > 2 else None
    result = args[3] if len(args) > 3 else None
    verdict = _decoded_envelope(result)
    is_error = kwargs.get("is_error") is True or _is_error_result(verdict)
    return _with_call_id(
        _tool_finished_payload(
            event_type, tool_name, duration=kwargs.get("duration"), is_error=is_error,
            result=result, invocation=invocation, verdict_result=verdict,
        ),
        args,
    )


def _decoded_envelope(result: Any) -> Any:
    """A JSON-object result string as its dict; anything else unchanged."""

    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            decoded = json.loads(result)
        except (TypeError, ValueError):
            return result
        if isinstance(decoded, dict):
            return decoded
    return result


def _tool_started(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    tool_name = _safe_label(args[1]) if len(args) > 1 else None
    invocation = args[3] if len(args) > 3 else kwargs.get("input") or kwargs.get("tool_input")
    return _tool_started_payload(event_type, tool_name, invocation=invocation)


def _reasoning(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
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


def _progress_default(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, "phase": "tool", "step": "progress", "status": "running", "summary": "Run progress update"}


#: One payload builder per callback, keyed on the name it arrives under (rule 12).
#: TWO vocabularies ride one callback: the adapter's own event label (the
#: ``run.tool.*`` labels the runner binds, checked FIRST) and the agent's
#: callback event (``args[0]``). An event neither table names is the default
#: progress payload — the boundary, not a third arm. ``tool.completed`` is in
#: neither: it is :data:`JOINED_CALLBACK_EVENTS`, never published on its own.
RUN_EVENTS: Mapping[str, ProgressBuilder] = {
    "run.tool.started": _run_tool_started,
    "run.tool.finished": _run_tool_finished,
}
CALLBACK_EVENTS: Mapping[str, ProgressBuilder] = {
    "tool.started": _tool_started,
    "reasoning.available": _reasoning,
    "_thinking": _reasoning,
}


def _progress_payload_from_callback(event_type: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    build = RUN_EVENTS.get(event_type)
    if build is None:
        callback_event = str(args[0]) if args else event_type
        build = CALLBACK_EVENTS.get(callback_event, _progress_default)
    return build(event_type, args, kwargs)
