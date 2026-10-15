"""h-conn-pool: a chat turn never opens a connection while a warm one exists.

A local keep-alive server speaks the Codex Responses SSE shape and counts the
TCP connections it accepts, so every guarantee here is a real round trip through
the real AIAgent request path, not a stubbed transport:

1. the pre-connect warms the client the turn checks out (one object), and the
   turn's request rides the pre-connected connection;
2. consecutive turns ride one connection even with the auxiliary title call
   (``_CodexCompletionsAdapter``) between them -- the reconnect on turns 2-3;
3. a prewarmed first turn's ``lead_in`` is not the locale-catalog parse.

Named sabotage: drop the ``drain_settled_stream`` block from
``agent/auxiliary_client.py::_CodexCompletionsAdapter.create`` -- row 2 reads a
new connection after each title call and reds.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent import process_bootstrap
from agent_runtime import provider_preconnect

MODEL = "gpt-5.6-luna"


def _sse(events: list[dict]) -> bytes:
    return b"".join(
        b"event: " + e["type"].encode() + b"\ndata: " + json.dumps(e).encode() + b"\n\n" for e in events
    )


def _completed_stream(model: str) -> bytes:
    message = {"type": "message", "id": "m1", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "hi", "annotations": []}]}
    response = {"id": "r1", "object": "response", "status": "completed", "model": model, "output": [message],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    return _sse([
        {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "output_index": 0,
         "item": {**message, "content": [], "status": "in_progress"}},
        {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": "m1", "delta": "hi"},
        {"type": "response.output_item.done", "output_index": 0, "item": message},
        {"type": "response.completed", "response": response},
    ])


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.connections: list[int] = []
        self.requests: list[tuple[str, str, int]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: a connection lives until a side closes it

    def setup(self):
        super().setup()
        self.server.connections.append(self.client_address[1])

    def _record(self):
        self.server.requests.append((self.command, self.path.split("?")[0], self.client_address[1]))

    def do_GET(self):  # noqa: N802 - the agent's init-time model probes
        self._record()
        self.send_response(404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_HEAD(self):  # noqa: N802 - the pre-connect
        self._record()
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802 - a turn or the title call
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        self._record()
        payload = _completed_stream(body.get("model") or MODEL)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for start in range(0, len(payload), 256):  # the terminal event lands before the terminator
            part = payload[start:start + 256]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, *_args):
        pass


@pytest.fixture
def server(monkeypatch):
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    process_bootstrap.close_shared_transports()
    srv = _Server()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        process_bootstrap.close_shared_transports()


def _base(srv) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}/backend-api/codex"


def _agent(srv, **extra):
    from run_agent import AIAgent

    return AIAgent(api_key="test-key", base_url=_base(srv), model=MODEL, provider="openai-codex",
                   api_mode="codex_responses", quiet_mode=True, skip_context_files=True, skip_memory=True,
                   enabled_toolsets=[], **extra)


def _preconnect(monkeypatch, agent) -> str:
    # The pre-connect skips loopback providers; the local server stands in for the edge.
    monkeypatch.setattr(provider_preconnect, "_is_loopback", lambda host: False)
    return provider_preconnect.preopen_provider_connection(agent, {})


@pytest.mark.timeout(120)
def test_the_preconnect_warms_the_client_the_turn_checks_out(server, monkeypatch):
    agent = _agent(server)
    assert _preconnect(monkeypatch, agent) == "404"
    from agent.client_lifecycle import _OPENAI_SLOT

    warmed = agent._request_slot(_OPENAI_SLOT)["client"]
    turn_client = agent._create_request_openai_client(reason="codex_stream_request")
    try:
        assert turn_client is not agent.client
        assert warmed is turn_client, "the pre-connect warmed a client the turn does not send on"
    finally:
        agent._close_request_openai_client(turn_client, reason="request_complete")


@pytest.mark.timeout(120)
def test_the_first_turn_rides_the_preconnected_connection(server, monkeypatch):
    agent = _agent(server)
    assert _preconnect(monkeypatch, agent) == "404"
    opened = len(server.connections)
    assert agent.run_conversation("hi").get("final_response") == "hi"
    assert len(server.connections) == opened, server.requests
    head_port = next(port for method, _path, port in server.requests if method == "HEAD")
    assert [port for method, _path, port in server.requests if method == "POST"] == [head_port]


@pytest.mark.timeout(120)
def test_consecutive_turns_ride_one_connection_across_the_title_call(server, monkeypatch):
    import openai

    from agent.auxiliary_client import _CodexCompletionsAdapter

    agent = _agent(server)
    assert _preconnect(monkeypatch, agent) == "404"
    title = _CodexCompletionsAdapter(
        openai.OpenAI(api_key="test-key", base_url=_base(server), max_retries=0,
                      http_client=process_bootstrap.build_keepalive_http_client(_base(server))),
        MODEL,
    )
    opened = len(server.connections)
    for turn in range(3):
        assert agent.run_conversation(f"turn {turn}").get("final_response") == "hi"
        if turn < 2:  # a placeholder title is retried after turns 1 and 2
            title.create(model=MODEL, messages=[{"role": "user", "content": "name this chat"}])
    posts = [port for method, _path, port in server.requests if method == "POST"]
    assert len(posts) == 5
    assert len(server.connections) == opened, f"new connections after the pre-connect: {server.requests}"
    assert len(set(posts)) == 1


@pytest.mark.timeout(120)
def test_a_prewarmed_first_turn_has_no_lead_in(server):
    from agent import i18n
    from agent_runtime.first_turn_warmup import PREWARM_FIRST_TURN_WARMUP_MS, warm_first_turn_paths

    values: list[dict] = []

    def _status(payload):
        if isinstance(payload, dict) and isinstance(payload.get("timing_values"), dict):
            values.append(payload["timing_values"])

    agent = _agent(server, status_callback=_status)
    i18n.reset_language_cache()
    timing: dict = {}
    warm_first_turn_paths(agent, timing)
    assert isinstance(timing.get(PREWARM_FIRST_TURN_WARMUP_MS), int)
    home = i18n._current_home()
    assert (home, i18n.get_language()) in i18n._catalog_cache, "the warm-up left the spinner catalog cold"

    agent.run_conversation("hi")
    lead_in = [v["conversation_request_lead_in_ms"] for v in values if "conversation_request_lead_in_ms" in v]
    assert lead_in and lead_in[0] < 100, lead_in
