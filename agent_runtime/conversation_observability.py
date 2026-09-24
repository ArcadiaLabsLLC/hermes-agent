"""Fork turn timing and dispatch receipts, shared by upstream turn phases."""
import logging
import time
from typing import Any, Optional
CONVERSATION_REQUEST_ASSEMBLED_STEP = "conversation_request_assembled"
logger = logging.getLogger(__name__)

def _emit_conversation_timing(
    agent: Any,
    step: str,
    started: float,
    *,
    status: str = "completed",
    **extra: Any,
) -> int:
    duration_ms = max(0, int((time.perf_counter() - started) * 1000))
    callback = getattr(agent, "status_callback", None)
    if callback is not None:
        try:
            callback(
                {
                    "type": "run.progress",
                    "phase": "timing",
                    "step": f"conversation_{step}",
                    "status": status,
                    "summary": f"Conversation {step.replace('_', ' ')} {status} in {duration_ms}ms.",
                    "duration_ms": duration_ms,
                    "timing_key": f"conversation_{step}_ms",
                    **extra,
                }
            )
        except Exception:
            logger.debug("conversation timing callback failed", exc_info=True)
    return duration_ms

def _emit_request_assembled_marker(agent: Any, **extra: Any) -> None:
    """Announce the dispatch instant: every byte hermes will send now exists.

    Not an :func:`_emit_conversation_timing` span — it names an INSTANT, not a
    duration, so it carries no ``duration_ms``/``timing_key`` (which also keeps
    it out of the profile-timing dict, whose collector only reads ``*_ms``
    keys). The mission-chat handler converts it into the ``request_assembled``
    phase mark (``agent_runtime/mission_chat_phases.py:mark_from_trace_payload``)
    that splits the turn record's "provider" span into hermes assembly vs
    genuine client-init + network + provider wait.

    Fired once per PHYSICAL dispatch attempt, right after the transport
    preflight (so a codex token refresh lands on the hermes side of the split)
    and right before the provider call. On a retry ladder the consumer's
    first-mark-wins keeps the first attempt's instant.
    """

    callback = getattr(agent, "status_callback", None)
    if callback is None:
        return
    try:
        callback(
            {
                "type": "run.progress",
                "phase": "timing",
                "step": CONVERSATION_REQUEST_ASSEMBLED_STEP,
                "status": "reached",
                "summary": "Provider request assembled; dispatching.",
                **extra,
            }
        )
    except Exception:
        logger.debug("request-assembled marker callback failed", exc_info=True)

class ProviderDispatchTiming:
    """The ``request_assembled`` instant and the ``provider_dispatch`` span of one attempt.

    Wraps the dispatch callable handed to the LLM middleware instead of
    re-indenting upstream's ``_perform_api_call`` body. ``mark()`` runs inside
    that body right after the transport preflight (so a Codex token refresh is
    charged to hermes, not the provider); the wrapper times from that mark to
    the provider's return. Provider first-byte time is upstream's
    ``agent._last_api_first_chunk_at``, carried by ``post_api_request`` as
    ``first_chunk_at`` (e17276c7b4) — this class keeps no second copy of it.
    """

    def __init__(self, agent: Any, **meta: Any) -> None:
        self.agent = agent
        self.meta = meta
        self.started: Optional[float] = None

    def mark(self) -> None:
        _emit_request_assembled_marker(self.agent, **self.meta)
        self.started = time.perf_counter()

    def wrap(self, perform: Any, *, streaming: bool) -> Any:
        def _timed(next_api_kwargs: Any) -> Any:
            self.started = None
            status = "failed"
            try:
                result = perform(next_api_kwargs)
                status = "completed"
                return result
            finally:
                if self.started is not None:
                    _emit_conversation_timing(
                        self.agent, "provider_dispatch", self.started,
                        status=status, streaming=streaming, **self.meta)

        return _timed
