"""Request timing and the profile status callback, the profile binding lookup,
and the small numeric coercions they use.
"""

from __future__ import annotations

import time
from typing import Any

from hermes_cli.profiles import get_profile_dir, normalize_profile_name, profile_exists
from agent_runtime.profile_home import PersonaProfileBinding

from agent_runtime.profile_runner.models import AgentRunRequest

__layer__ = "policy"

__all__ = [
    "StatusEmitter",
    "_binding_for_profile",
    "_elapsed_ms",
    "_emit_request_timing",
    "_profile_status_callback",
]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _emit_request_timing(request: AgentRunRequest, timing_key: str, started: float, *, status: str = "completed") -> int:
    duration_ms = _elapsed_ms(started)
    callback = request.progress_callback
    if callback is not None:
        try:
            callback(
                {
                    "type": "run.progress",
                    "phase": "timing",
                    "step": f"profile_{timing_key}",
                    "status": status,
                    "summary": f"Profile {timing_key.replace('_', ' ').title()} {status} in {duration_ms}ms.",
                    "duration_ms": duration_ms,
                    "timing_key": f"profile_{timing_key}_ms",
                }
            )
        except Exception:
            pass
    return duration_ms


class StatusEmitter:
    """The run's status callback: records the agent's profile timings into the
    run's ``timing`` and forwards every payload to the request's progress
    callback (a forwarding failure is swallowed — an instrument never fails a run).
    """

    def __init__(self, request: AgentRunRequest, timing: dict[str, Any]) -> None:
        self.request = request
        self.timing = timing

    def emit(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._record_timing_key(payload)
            self._record_timing_values(payload.get("timing_values"))
        callback = self.request.progress_callback
        if callback is not None:
            try:
                callback(payload)
            except Exception:
                pass

    def _record_timing_key(self, payload: dict) -> None:
        timing_key = payload.get("timing_key")
        if not (
            isinstance(timing_key, str)
            and timing_key.endswith("_ms")
            and timing_key.startswith(("agent_init_", "conversation_", "provider_"))
        ):
            return
        try:
            parsed = int(payload.get("duration_ms"))
        except (TypeError, ValueError):
            parsed = -1
        if parsed >= 0:
            self.timing[f"profile_{timing_key}"] = parsed

    def _record_timing_values(self, timing_values: Any) -> None:
        if not isinstance(timing_values, dict):
            return
        for key, value in timing_values.items():
            if not isinstance(key, str) or not key.startswith(("conversation_", "provider_")):
                continue
            if not key.endswith(("_ms", "_count")):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                self.timing[f"profile_{key}"] = parsed


def _profile_status_callback(request: AgentRunRequest, timing: dict[str, Any]):
    return StatusEmitter(request, timing).emit


def _binding_for_profile(profile: str | None) -> PersonaProfileBinding:
    if not profile:
        return PersonaProfileBinding(
            persona_id="profile_runner",
            hermes_profile=None,
            profile_home=None,
            readiness="ready",
            summary="inherits active Hermes profile",
        )
    name = normalize_profile_name(profile)
    if not profile_exists(name):
        return PersonaProfileBinding(
            persona_id="profile_runner",
            hermes_profile=name,
            profile_home=None,
            readiness="missing_profile",
            summary=f"Hermes profile '{name}' does not exist",
        )
    return PersonaProfileBinding(
        persona_id="profile_runner",
        hermes_profile=name,
        profile_home=get_profile_dir(name),
        readiness="ready",
        summary="profile exists",
    )
