"""Fork turn timing and dispatch receipts, shared by upstream turn phases."""
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional
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

#: The agent whose ``status_callback`` receives the dispatch timing of the current turn.
#: Bound by the persona runner around ``run_conversation`` (``profile_runner``, which
#: builds that callback); the ``llm_execution`` middleware runs synchronously in the turn
#: thread, so it reads the binding without the middleware context having to carry it.
_TIMING_AGENT: ContextVar[Any] = ContextVar("eternia_timing_agent", default=None)


@contextmanager
def bind_timing_agent(agent: Any) -> Iterator[None]:
    token = _TIMING_AGENT.set(agent)
    try:
        yield
    finally:
        _TIMING_AGENT.reset(token)


def _dispatch_streams(agent: Any) -> bool:
    try:
        from agent.turn_api_call import _should_stream

        return bool(_should_stream(agent))
    except Exception:
        return False


def time_provider_dispatch(
    request: Any = None,
    next_call: Any = None,
    *,
    api_call_count: Any = None,
    api_mode: Any = None,
    provider: Any = None,
    model: Any = None,
    **_context: Any,
) -> Any:
    """``llm_execution`` middleware: the ``request_assembled`` instant and the
    ``provider_dispatch`` span of one physical attempt.

    Wraps exactly the callable upstream hands the chain (``_perform_api_call``), so the
    span runs from here to the provider's return. One loss against the old in-body mark:
    the instant lands BEFORE the Codex transport preflight, so a Codex token refresh is
    charged to the provider side. Provider first-byte time stays upstream's
    ``post_api_request`` ``first_chunk_at`` — no second copy here. Unbound (no persona
    turn) -> a pass-through.
    """

    agent = _TIMING_AGENT.get()
    if agent is None:
        return next_call()
    meta = {"api_call_count": api_call_count, "api_mode": api_mode, "provider": provider, "model": model}
    streaming = _dispatch_streams(agent)
    _emit_request_assembled_marker(agent, **meta)
    started = time.perf_counter()
    status = "failed"
    try:
        result = next_call()
        status = "completed"
        return result
    finally:
        _emit_conversation_timing(
            agent, "provider_dispatch", started, status=status, streaming=streaming, **meta)
