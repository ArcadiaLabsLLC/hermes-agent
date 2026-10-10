"""Fork turn timing and dispatch receipts, shared by upstream turn phases."""
import logging
import time
from typing import Any, Optional

__layer__ = "policy"

CONVERSATION_REQUEST_ASSEMBLED_STEP = "conversation_request_assembled"

#: h-chatperf (2026-10-03): the instants that split the turn's
#: ``provider_request_started -> provider_first_byte`` span, which on cold turn
#: ``1e4c06ba`` was 12.4 s with only ``request_assembled`` inside it. Each step
#: is ``conversation_<mark>`` and the mission-chat handler converts it into the
#: phase mark of that name (``mission_chat_phases._trace_marker_steps``).
#:
#: * ``conversation_started`` -- ``run_conversation`` entered; the gap before it
#:   is the runner's own hand-off.
#: * ``turn_context_built`` -- ``build_turn_context`` returned.
#: * ``preflight_done`` -- the loop's pre-dispatch phases (iteration prep,
#:   request assembly, the preflight gate) are done.
#: * ``request_built`` -- ``build_api_request`` returned; the gap to
#:   ``request_assembled`` is the ``llm_execution`` chain ahead of dispatch.
#: * ``client_built`` -- the request client exists and the stream open begins.
#: * ``tls_done`` -- the TLS handshake completed. ABSENT on a turn whose request
#:   rode a pooled connection, which is itself the reuse receipt.
#: * ``request_sent`` -- the request body left the process.
#: * ``response_headers`` -- the provider's response headers arrived.
#: * ``provider_returned`` -- the ``llm_execution`` call returned (a streamed
#:   attempt has consumed its stream by then). Fired on EVERY provider path,
#:   transport hook or not, so it is also what ends a provider-wait window.
CONVERSATION_STARTED_STEP = "conversation_conversation_started"
CONVERSATION_TURN_CONTEXT_BUILT_STEP = "conversation_turn_context_built"
CONVERSATION_PREFLIGHT_DONE_STEP = "conversation_preflight_done"
CONVERSATION_REQUEST_BUILT_STEP = "conversation_request_built"
TRANSPORT_CLIENT_BUILT_STEP = "conversation_client_built"
TRANSPORT_TLS_DONE_STEP = "conversation_tls_done"
TRANSPORT_REQUEST_SENT_STEP = "conversation_request_sent"
TRANSPORT_RESPONSE_HEADERS_STEP = "conversation_response_headers"
CONVERSATION_PROVIDER_RETURNED_STEP = "conversation_provider_returned"

#: step -> the phase mark it becomes. ONE table, read by the converter in
#: ``mission_chat_phases``; a step absent here is not a timing marker.
CONVERSATION_MARKER_STEPS: dict[str, str] = {
    CONVERSATION_STARTED_STEP: "conversation_started",
    CONVERSATION_TURN_CONTEXT_BUILT_STEP: "turn_context_built",
    CONVERSATION_PREFLIGHT_DONE_STEP: "preflight_done",
    CONVERSATION_REQUEST_BUILT_STEP: "request_built",
    CONVERSATION_REQUEST_ASSEMBLED_STEP: "request_assembled",
    TRANSPORT_CLIENT_BUILT_STEP: "client_built",
    TRANSPORT_TLS_DONE_STEP: "tls_done",
    TRANSPORT_REQUEST_SENT_STEP: "request_sent",
    TRANSPORT_RESPONSE_HEADERS_STEP: "response_headers",
    CONVERSATION_PROVIDER_RETURNED_STEP: "provider_returned",
}

logger = logging.getLogger(__name__)

#: One line per provider dispatch beside upstream's ``API call #N`` line, which names model and
#: provider but not the effort the request carried; ``chat_turn_effort`` is per run, this per call.
API_CALL_EFFORT_RECEIPT = "api_call_effort call=%s model=%s provider=%s effort=%s"

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

def _emit_phase_marker(agent: Any, step: str) -> None:
    """Announce one of :data:`CONVERSATION_MARKER_STEPS`' instants. Never raises.

    The same payload shape as :func:`_emit_request_assembled_marker` (an
    INSTANT: no ``duration_ms``/``timing_key``, so the profile-timing collector
    never sees it), for the loop and transport seams that cannot hold the
    turn's marks. A step outside the table is dropped here rather than sent:
    the converter would ignore it anyway, and a typo should cost nothing.
    """

    if step not in CONVERSATION_MARKER_STEPS:
        return
    if step == CONVERSATION_PREFLIGHT_DONE_STEP:
        # h-turn1 A5: the request-build split's ``lead_in`` starts here.
        from agent_runtime.request_build_timing import note_preflight_done

        note_preflight_done(agent)
    callback = getattr(agent, "status_callback", None)
    if callback is None:
        return
    try:
        callback({"type": "run.progress", "phase": "timing", "step": step, "status": "reached"})
    except Exception:
        logger.debug("phase marker callback failed", exc_info=True)


def _dispatch_streams(agent: Any) -> bool:
    try:
        from ._upstream_doors import dispatch_streams

        return dispatch_streams(agent)
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

    from agent_runtime.persona_turn_binding import current_persona_turn_agent
    from agent_runtime.request_effort import request_effort

    logger.info(API_CALL_EFFORT_RECEIPT, api_call_count, model or "-", provider or "-", request_effort(request))
    agent = current_persona_turn_agent()
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
        _emit_phase_marker(agent, CONVERSATION_PROVIDER_RETURNED_STEP)
