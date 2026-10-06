"""Transport stamps for a chat turn's provider request (h-chatperf, 2026-10-03).

**The question this answers.** Cold turn ``1e4c06ba`` (Windows, 2026-10-03)
spent 9.0 s between "request client created" and the first parsed SSE event,
with nothing on the record inside that span. That window holds four different
things -- the TCP connect, the TLS handshake, the upload of a 31k-token body,
and the provider's own wait -- and only the last one is the provider's. These
stamps split it, so "the provider is slow" and "hermes could not get the request
out" stop being one number.

**How.** httpcore reports its connection lifecycle to a ``trace`` callable it
finds in ``request.extensions``. An httpx ``request`` event hook runs before the
transport sees the request, so it can put that callable there. The callable maps
three httpcore events onto three phase marks and announces each through the
same timing-marker payload the conversation loop already uses
(``conversation_observability._emit_phase_marker``), because this layer cannot
hold the turn's :class:`~agent_runtime.mission_chat_phases.TurnPhaseMarks`.

* ``connection.start_tls.complete`` -> ``tls_done``. A request that rode a
  pooled connection never does a handshake, so its turn has NO ``tls_done`` --
  the absence is the connection-reuse receipt, not a gap.
* ``http11|http2 .send_request_body.complete`` -> ``request_sent``.
* ``http11|http2 .receive_response_headers.complete`` -> ``response_headers``.

``client_built`` is announced by :func:`install_transport_phase_trace` itself:
it is called where the stream is opened, by which point the request client
exists.

**Cost and failure.** One dict lookup per httpcore event; nothing per SSE
frame. Every path is fail-open -- an instrument must never be the reason a
request fails -- and an already-present ``trace`` (a caller's own) is chained,
never replaced.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from agent_runtime.conversation_observability import (
    TRANSPORT_CLIENT_BUILT_STEP,
    TRANSPORT_REQUEST_SENT_STEP,
    TRANSPORT_RESPONSE_HEADERS_STEP,
    TRANSPORT_TLS_DONE_STEP,
    _emit_phase_marker,
)
from agent_runtime.prewarmed_system_prompt import run_deferred_turn_persist
from agent_runtime.send_window_receipt import SendWindow
from agent_runtime.stream_gap_receipt import begin_send_window, begin_stream_gap_receipt

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: httpcore trace event -> the timing-marker step it announces. Closed: every
#: other event (connect started, headers sent, body chunks, ...) is ignored.
TRACE_EVENT_STEPS: dict[str, str] = {
    "connection.start_tls.complete": TRANSPORT_TLS_DONE_STEP,
    "http11.send_request_body.complete": TRANSPORT_REQUEST_SENT_STEP,
    "http2.send_request_body.complete": TRANSPORT_REQUEST_SENT_STEP,
    "http11.receive_response_headers.complete": TRANSPORT_RESPONSE_HEADERS_STEP,
    "http2.receive_response_headers.complete": TRANSPORT_RESPONSE_HEADERS_STEP,
}

_HOOK_MARK = "_hermes_transport_phase_trace_hook"
#: The agent whose turn the client's next request belongs to, re-pointed on
#: every install: the hook outlives the agent that installed it (h-send-window).
_CLIENT_AGENT_ATTR = "_hermes_transport_trace_agent"


def phase_trace_for(
    agent: Any, chained: Callable[..., Any] | None = None, window: SendWindow | None = None,
) -> Callable[[str, Any], None]:
    """The httpcore ``trace`` callable that announces this agent's stamps.

    Every event also reaches *window* (h-send-window), the request's
    ``send_window_receipt``.
    """

    def _trace(event_name: str, info: Any) -> None:
        if chained is not None:
            try:
                chained(event_name, info)
            except Exception:
                logger.debug("chained transport trace raised", exc_info=True)
        if window is not None:
            try:
                window.on_trace(event_name)
            except Exception:
                logger.debug("send window trace stamp failed", exc_info=True)
        step = TRACE_EVENT_STEPS.get(event_name)
        if step is not None:
            _emit_phase_marker(agent, step)
        if step == TRANSPORT_REQUEST_SENT_STEP and agent is not None:
            # h-turn1-conn: the first turn's held persist writes, now that the request is out.
            run_deferred_turn_persist(agent)

    return _trace


def install_transport_phase_trace(agent: Any, client: Any) -> None:
    """Announce ``client_built`` and hook *client*'s httpx requests. Never raises.

    Idempotent per httpx client: the hook is marked, and a second install on
    the same client re-announces ``client_built`` (which the turn's
    first-mark-wins rule then ignores) and re-points the hook at *agent*.
    """

    _emit_phase_marker(agent, TRANSPORT_CLIENT_BUILT_STEP)
    begin_stream_gap_receipt(agent, client)  # h-stream-gap: a fresh receipt per opened stream
    try:
        http_client = getattr(client, "_client", None)
        hooks = getattr(http_client, "event_hooks", None)
        if not isinstance(hooks, dict):
            return
        setattr(http_client, _CLIENT_AGENT_ATTR, agent)
        if any(getattr(hook, _HOOK_MARK, False) for hook in hooks.get("request", ())):
            return

        def _on_request(request: Any) -> None:
            try:
                extensions = request.extensions
                window = begin_send_window(http_client, request)  # h-send-window
                current = getattr(http_client, _CLIENT_AGENT_ATTR, None)
                extensions["trace"] = phase_trace_for(current, extensions.get("trace"), window)
            except Exception:
                logger.debug("transport phase trace not attached", exc_info=True)

        setattr(_on_request, _HOOK_MARK, True)
        # httpx copies on assignment; rebuild the mapping (the served-model
        # capture in ``agent/served_model.py`` installs its hook the same way).
        http_client.event_hooks = {**hooks, "request": [*hooks.get("request", ()), _on_request]}
    except Exception:
        logger.debug("transport phase trace install skipped", exc_info=True)


__all__ = ["TRACE_EVENT_STEPS", "install_transport_phase_trace", "phase_trace_for"]
