"""h-chatperf: the provider span's stamps reach the turn record and the receipt.

Three guarantees, each pinned where it lives:

1. every new timing-marker step converts into its phase mark
   (``mission_chat_phases.mark_from_trace_payload``) and the marks project onto
   the terminal ``timing`` block under their ``*_ms`` names;
2. the transport hook announces ``client_built`` / ``request_sent`` /
   ``response_headers`` from a REAL httpx request (a local server, so the
   positive control is a real round trip, not a stubbed trace call), and NO
   ``tls_done`` on a plain-HTTP connection -- the absence the reuse receipt
   relies on;
3. a pre-existing ``trace`` extension is chained, not replaced.

Named sabotage: drop ``"http11.send_request_body.complete"`` from
``transport_phase_trace.TRACE_EVENT_STEPS`` -- the live-request row loses
``request_sent`` and reds.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime.conversation_observability import CONVERSATION_MARKER_STEPS
from agent_runtime.mission_chat_phases import (
    PHASE_ORDER,
    TURN_TIMING_ORDER,
    TurnPhaseMarks,
    mark_from_trace_payload,
    turn_timing_block,
)
from agent_runtime.transport_phase_trace import install_transport_phase_trace

_NEW_MARKS = (
    "conversation_started",
    "turn_context_built",
    "preflight_done",
    "request_built",
    "client_built",
    "tls_done",
    "request_sent",
    "response_headers",
    "provider_returned",
)


def test_every_marker_step_becomes_its_mark_and_its_timing_key():
    clock = iter(float(i) for i in range(100))
    marks = TurnPhaseMarks(monotonic=lambda: next(clock), wall_now=lambda: "t")
    for step in CONVERSATION_MARKER_STEPS:
        mark_from_trace_payload(marks, {"type": "run.progress", "phase": "timing", "step": step})
    snapshot = marks.snapshot()
    for mark in _NEW_MARKS:
        assert mark in PHASE_ORDER, mark
        assert isinstance(snapshot.get(mark), int), (mark, snapshot)
    block = turn_timing_block(phases=snapshot, profile_timing={})
    for mark in _NEW_MARKS:
        assert f"{mark}_ms" in TURN_TIMING_ORDER
        assert block[f"{mark}_ms"] == snapshot[mark], (mark, block)


def test_phase_order_puts_the_stamps_inside_the_provider_span():
    order = list(PHASE_ORDER)
    inside = order[order.index("provider_request_started") + 1 : order.index("provider_first_byte")]
    assert inside == [
        "conversation_started", "turn_context_built", "preflight_done", "request_built",
        "request_assembled", "client_built", "tls_done", "request_sent", "response_headers",
    ]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        body = b"{}"
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _agent(steps: list[str]):
    return SimpleNamespace(status_callback=lambda payload: steps.append(payload.get("step")))


def test_a_live_request_announces_client_sent_and_headers_but_no_tls(local_server):
    steps: list[str] = []
    http = httpx.Client()
    client = SimpleNamespace(_client=http)
    try:
        install_transport_phase_trace(_agent(steps), client)
        http.post(f"{local_server}/v1/responses", json={"input": "x" * 4096})
    finally:
        http.close()
    marks = [CONVERSATION_MARKER_STEPS[s] for s in steps if s in CONVERSATION_MARKER_STEPS]
    assert marks == ["client_built", "request_sent", "response_headers"], steps


def test_an_uninstalled_client_announces_nothing(local_server):
    """Positive control for the row above: the same request with no hook."""

    steps: list[str] = []
    http = httpx.Client()
    try:
        http.post(f"{local_server}/v1/responses", json={})
    finally:
        http.close()
    assert steps == []


def test_install_is_idempotent_and_chains_a_callers_trace(local_server):
    steps: list[str] = []
    seen: list[str] = []
    agent = _agent(steps)

    def _callers_hook(request):
        request.extensions["trace"] = lambda name, info: seen.append(name)

    http = httpx.Client(event_hooks={"request": [_callers_hook]})
    client = SimpleNamespace(_client=http)
    try:
        install_transport_phase_trace(agent, client)
        install_transport_phase_trace(agent, client)
        assert len(http.event_hooks["request"]) == 2
        http.post(f"{local_server}/v1/responses", json={})
    finally:
        http.close()
    assert "http11.send_request_body.complete" in seen, seen
    assert steps.count("conversation_request_sent") == 1, steps


def test_the_native_history_reload_rides_the_pre_admit_fold():
    """The handler's history reload is folded beside the context sub-spans."""

    from hermes_cli.harness_parts.persona.chat_admission import _safe_pre_admit_timings

    assert _safe_pre_admit_timings({"context_native_history_ms": 41, "unlisted_ms": 9}) == {
        "context_native_history_ms": 41
    }
