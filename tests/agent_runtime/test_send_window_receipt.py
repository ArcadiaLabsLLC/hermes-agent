"""h-send-window: the ``send_window_receipt`` tells this process, the network and the provider apart.

Every case drives the REAL path: ``agent.codex_runtime.run_codex_stream`` with a
real ``openai.OpenAI`` client over the keep-alive client the serve builds
(``build_keepalive_http_client``) against a fake SSE server in a SEPARATE process
(HTTP/1.1, chunked, keep-alive), so its bytes leave on time even while this
process is starved of the GIL. The window opens at the httpx request hook
(``install_transport_phase_trace``) and closes on the first parsed event.

(a) the server holds its headers 1 s -> ``wait_on=server``, zero local stall;
(b) a GIL hog inside the send window -> the stall probe shows it, ``wait_on=local``;
(c) a cold connection vs a reused one -> ``conn=new`` with ``connect_ms``, then
    ``conn=reused`` with none -- and the second request, sent for ANOTHER agent on
    the client the first one hooked, still gets its own bytes and window;
(d) a stream whose content type is not ``text/event-stream`` still gets its
    bytes stamped (every live 2026-10-06 receipt read ``chunks=0``).

Named sabotage (each reds a row): drop the ``window.on_trace`` forward in
``phase_trace_for`` (no ``server_wait_ms``/``conn``: a, c); never start the send
window's probe (``stall_max_ms=na``: b); put the ``text/event-stream`` test back
on the byte wrap (``first_lag_ms=na``: d); read the receipt from the agent the hook
was installed for instead of the client (no second window: c).
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from openai import OpenAI

from agent.codex_runtime import run_codex_stream
from agent.process_bootstrap import build_keepalive_http_client
from agent_runtime.send_window_receipt import SEND_WINDOW_RECEIPT
from agent_runtime.stream_gap_receipt import STREAM_GAP_RECEIPT

_SERVER = r'''
import json, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = sys.argv[1]

def ev(obj):
    return ("event: %s\ndata: %s\n\n" % (obj["type"], json.dumps(obj))).encode()

MSG = {"type": "message", "id": "m1", "status": "completed", "role": "assistant",
       "content": [{"type": "output_text", "text": "Hi", "annotations": []}]}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        if MODE == "slow_headers":
            time.sleep(1.0)
        elif MODE == "hog":
            time.sleep(0.3)
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8" if MODE == "plain_type" else "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        w = self.wfile
        def send(obj):
            data = ev(obj)
            w.write(b"%x\r\n%s\r\n" % (len(data), data)); w.flush()
        send({"type": "response.created", "sequence_number": 0,
              "response": {"id": "r1", "object": "response", "status": "in_progress", "output": []}})
        time.sleep(0.05)
        send({"type": "response.output_text.delta", "delta": "Hi", "item_id": "m1",
              "output_index": 0, "content_index": 0, "sequence_number": 1})
        send({"type": "response.output_item.done", "output_index": 0, "item": MSG, "sequence_number": 2})
        send({"type": "response.completed", "sequence_number": 3,
              "response": {"id": "r1", "object": "response", "status": "completed", "output": [MSG],
                           "usage": {"input_tokens": 5, "output_tokens": 4, "total_tokens": 9}}})
        w.write(b"0\r\n\r\n"); w.flush()

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
print(srv.server_address[1], flush=True)
srv.serve_forever()
'''


@pytest.fixture
def fake_sse():
    procs = []

    def start(mode: str) -> str:
        proc = subprocess.Popen([sys.executable, "-c", _SERVER, mode], stdout=subprocess.PIPE, text=True)
        procs.append(proc)
        port = int(proc.stdout.readline().strip())
        return f"http://127.0.0.1:{port}/v1"

    yield start
    for proc in procs:
        proc.kill()
        proc.wait(timeout=10)


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="", provider="openai-codex", model="send-fixture", _current_api_request_id="req-1",
        _interrupt_requested=False, _last_api_first_chunk_at=None, _touch_activity=lambda *_: None,
        _fire_stream_delta=lambda *_: None, _fire_reasoning_delta=lambda *_: None, _client_log_context=lambda: "",
    )


def _client(base_url: str) -> OpenAI:
    http_client = build_keepalive_http_client(base_url)
    assert http_client is not None
    return OpenAI(api_key="fixture-not-a-key", base_url=base_url, max_retries=0, http_client=http_client)


def _run(client: OpenAI, caplog, agent: SimpleNamespace | None = None) -> tuple[dict, dict]:
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="agent_runtime"):
        result = run_codex_stream(agent or _agent(), {"model": "send-fixture", "input": "hi"}, client=client)
    assert result.output_text == "Hi"
    found = {}
    for prefix in (SEND_WINDOW_RECEIPT, STREAM_GAP_RECEIPT):
        lines = [m for m in caplog.messages if m.startswith(prefix + " ")]
        assert len(lines) == 1, caplog.messages
        print(lines[0])
        found[prefix] = dict(re.findall(r"(\w+)=(\S+)", lines[0]))
    return found[SEND_WINDOW_RECEIPT], found[STREAM_GAP_RECEIPT]


def _num(fields: dict[str, str], key: str) -> float:
    assert fields[key] != "na", (key, fields)
    return float(fields[key])


@pytest.mark.timeout(60)
def test_held_headers_are_the_servers_wait_with_no_local_stall(fake_sse, caplog):
    send, _gap = _run(_client(fake_sse("slow_headers")), caplog)
    assert send["wait_on"] == "server"
    assert 900 <= _num(send, "server_wait_ms") <= 3000
    assert _num(send, "request_sent_ms") < 300
    assert _num(send, "response_headers_ms") >= _num(send, "request_sent_ms") + 900
    assert _num(send, "first_byte_ms") >= _num(send, "response_headers_ms")
    assert _num(send, "first_event_ms") >= _num(send, "first_byte_ms")
    assert _num(send, "body_bytes") > 0 and send["http"] == "1.1"
    assert _num(send, "stall_samples") > 10
    assert _num(send, "stall_over50_ms") < 100  # Windows timer jitter stays under the floor


@pytest.mark.timeout(120)
def test_a_gil_hog_in_the_send_window_shows_as_a_local_stall(fake_sse, caplog):
    """The hog starts at the request hook and stops on the first parsed event."""
    client = _client(fake_sse("hog"))
    big = 3 ** 700_000
    stop = threading.Event()

    def hog() -> None:  # each multiply holds the GIL ~70 ms in one C call
        while not stop.is_set():
            _ = big * big

    thread = threading.Thread(target=hog, daemon=True)

    def on_request(_request) -> None:
        if not thread.is_alive() and not stop.is_set():
            thread.start()

    hooks = client._client.event_hooks
    client._client.event_hooks = {**hooks, "request": [*hooks["request"], on_request]}
    agent = _agent()
    agent._touch_activity = lambda *_: stop.set()  # the first parsed event closes the window
    try:
        send, _gap = _run(client, caplog, agent)
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=10)
    # The hog also inflates the stamps httpcore takes on this thread (connect, upload on a
    # loopback): only the probe tells that time from the network's.
    assert _num(send, "stall_max_ms") >= 50
    assert _num(send, "stall_over50_ms") >= 500
    assert send["wait_on"] == "local"


@pytest.mark.timeout(60)
def test_a_cold_connection_and_a_reused_one_are_named(fake_sse, caplog):
    client = _client(fake_sse("fast"))
    cold, _gap = _run(client, caplog)
    warm, warm_gap = _run(client, caplog)  # a fresh agent on the client the first one hooked
    assert cold["conn"] == "new" and _num(cold, "connect_ms") >= 0
    assert warm["conn"] == "reused" and warm["connect_ms"] == "na" and warm["tls_ms"] == "na"
    assert _num(warm, "pool_ms") < 100
    assert warm_gap["first_lag_ms"] != "na" and _num(warm, "first_byte_ms") <= _num(warm, "first_event_ms")


@pytest.mark.timeout(60)
def test_a_stream_not_typed_event_stream_still_has_its_bytes_stamped(fake_sse, caplog):
    send, gap = _run(_client(fake_sse("plain_type")), caplog)
    assert send["content_type"] == "text/plain"
    assert gap["first_lag_ms"] != "na" and gap["text_chunk_ms"] != "na"
    assert _num(send, "first_byte_ms") <= _num(send, "first_event_ms")
