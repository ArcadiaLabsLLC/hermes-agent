"""Sub-stamps for the turn's ``preflight_done -> request_built`` span.

h-turn1 A5 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
On every first turn on record that span is 0.57-2.3 s and on every later turn
30-96 ms, and nothing said where it went. :class:`RequestBuildLaps` splits it into
:data:`REQUEST_BUILD_PARTS`, in the order upstream's
``agent/turn_api_request.py::build_api_request`` runs them, and hands the split to
the run's status callback as ONE ``timing_values`` payload, which the runner
records as ``profile_conversation_request_<part>_ms`` in the turn's
``profile_timing`` (``profile_runner/status.py::StatusEmitter``).

``lead_in`` is the stretch before ``build_api_request`` itself (``announce_api_call``
and the Nous rate guard): it runs from the instant the ``preflight_done`` marker
left (:func:`note_preflight_done`, called by
``conversation_observability._emit_phase_marker``), so the parts sum to the span.

Names only: no payload text, no tool names, no sizes. An instrument never fails a
turn -- every entry point swallows.
"""

from __future__ import annotations

import logging
import time
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The parts, in the order they run. ``lead_in`` -- announce + rate guard;
#: ``redecorate`` -- reasoning echo, prompt-cache redecoration, image strip;
#: ``observe_tools`` -- the shared-metrics tool snapshot; ``kwargs`` --
#: ``agent._build_api_kwargs``; ``preflight`` -- outbound sanitize + the
#: transport preflight; ``middleware`` -- the ``llm_request`` middleware chain;
#: ``hook`` -- the ``pre_api_request`` hook, the debug dump and the MoA hand-off.
REQUEST_BUILD_PARTS = ("lead_in", "redecorate", "observe_tools", "kwargs", "preflight", "middleware", "hook")

REQUEST_BUILD_STEP = "conversation_request_build"

#: Attribute the ``preflight_done`` marker leaves on the agent (a ``perf_counter``).
PREFLIGHT_DONE_AT_ATTR = "_fork_preflight_done_at"


def timing_value_key(part: str) -> str:
    return f"conversation_request_{part}_ms"


def note_preflight_done(agent: Any) -> None:
    """Remember the ``preflight_done`` instant for the next :class:`RequestBuildLaps`."""

    try:
        setattr(agent, PREFLIGHT_DONE_AT_ATTR, time.perf_counter())
    except Exception:
        pass


class RequestBuildLaps:
    """One attempt's split of the request build. ``lap(part)`` closes ``part``."""

    __slots__ = ("_agent", "_last", "_values")

    def __init__(self, agent: Any) -> None:
        now = time.perf_counter()
        self._agent = agent
        self._values: dict[str, int] = {}
        preflight_at = getattr(agent, PREFLIGHT_DONE_AT_ATTR, None)
        if isinstance(preflight_at, float) and preflight_at <= now:
            self._values[timing_value_key("lead_in")] = int((now - preflight_at) * 1000)
            try:
                setattr(agent, PREFLIGHT_DONE_AT_ATTR, None)  # a retry attempt has no lead-in
            except Exception:
                pass
        self._last = now

    def lap(self, part: str) -> None:
        now = time.perf_counter()
        self._values[timing_value_key(part)] = max(0, int((now - self._last) * 1000))
        self._last = now

    def finish(self, part: str) -> None:
        """Close the last part and emit the attempt's split. Never raises."""

        try:
            self.lap(part)
            callback = getattr(self._agent, "status_callback", None)
            if callback is None:
                return
            total = sum(self._values.values())
            callback(
                {
                    "type": "run.progress",
                    "phase": "timing",
                    "step": REQUEST_BUILD_STEP,
                    "status": "completed",
                    "summary": f"Conversation request build completed in {total}ms.",
                    "timing_values": dict(self._values),
                }
            )
        except Exception:
            logger.debug("request-build timing callback failed", exc_info=True)

    @property
    def values(self) -> dict[str, int]:
        return dict(self._values)


__all__ = [
    "PREFLIGHT_DONE_AT_ATTR",
    "REQUEST_BUILD_PARTS",
    "REQUEST_BUILD_STEP",
    "RequestBuildLaps",
    "note_preflight_done",
    "timing_value_key",
]
