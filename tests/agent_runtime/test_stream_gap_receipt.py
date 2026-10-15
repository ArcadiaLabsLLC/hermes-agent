"""h-stream-gap: the ``stream_gap_receipt`` tells provider silence, provider reasoning and a local stall apart.

Every case drives the REAL path: ``agent.codex_runtime.run_codex_stream`` with a
real ``openai.OpenAI`` client against a fake SSE server in a SEPARATE process (so
its bytes leave on time even while this process is starved of the GIL). The
receipt is installed by the transport hook (``install_transport_phase_trace``)
and fed by the fork seam in ``run_codex_stream``'s ``_on_event``.

(a) silent provider for 3 s   -> no bytes in the window, zero lag;
(b) reasoning deltas for 3 s  -> events counted, zero lag;
(c) bytes on time, reader starved by a GIL hog -> large lag and late wake-ups.

Named sabotage (each reds a row): drop the ``observe_stream_event`` seam line in
``agent/codex_runtime.py`` (no receipt line at all); stop wrapping the response
stream in ``begin_stream_gap_receipt`` (chunks=0 in (b), lag ``na``); never
start the probe (``stall_max_ms=na`` in (c)).
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
    protocol_version = "HTTP/1.0"
    def log_message(self, *a):
        pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        w = self.wfile
        def send(obj):
            w.write(ev(obj)); w.flush()
        send({"type": "response.created", "sequence_number": 0,
              "response": {"id": "r1", "object": "response", "status": "in_progress", "output": []}})
        if MODE == "silent":
            time.sleep(3.0)
        elif MODE == "reasoning":
            for i in range(30):
                time.sleep(0.1)
                send({"type": "response.reasoning_summary_text.delta", "delta": "think ",
                      "item_id": "rs1", "output_index": 0, "summary_index": 0, "sequence_number": i + 1})
        elif MODE == "hog":
            # in_progress frames echo the request's tools, as the live provider's do: each one is
            # milliseconds of SDK model building, long enough for a competing thread to take the GIL
            tools = [{"type": "function", "name": "tool_%d" % n, "description": "d" * 40, "strict": False,
                      "parameters": {"type": "object", "properties": {"a%d" % k: {"type": "string"} for k in range(8)}}}
                     for n in range(300)]
            for i in range(10):
                time.sleep(0.1)
                send({"type": "response.in_progress", "sequence_number": i + 1,
                      "response": {"id": "r1", "object": "response", "status": "in_progress", "output": [],
                                   "tools": tools}})
        send({"type": "response.output_text.delta", "delta": "Hi", "item_id": "m1",
              "output_index": 0, "content_index": 0, "sequence_number": 100})
        send({"type": "response.output_item.done", "output_index": 0, "item": MSG, "sequence_number": 101})
        send({"type": "response.completed", "sequence_number": 102,
              "response": {"id": "r1", "object": "response", "status": "completed", "output": [MSG],
                           "usage": {"input_tokens": 5, "output_tokens": 40, "total_tokens": 45,
                                     "output_tokens_details": {"reasoning_tokens": 12}}}})

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
        session_id="", provider="openai-codex", model="gap-fixture", _current_api_request_id="req-1",
        _interrupt_requested=False, _last_api_first_chunk_at=None, _touch_activity=lambda *_: None,
        _fire_stream_delta=lambda *_: None, _fire_reasoning_delta=lambda *_: None, _client_log_context=lambda: "",
    )


def _run(base_url: str, caplog, agent: SimpleNamespace | None = None) -> dict[str, str]:
    client = OpenAI(api_key="fixture-not-a-key", base_url=base_url, max_retries=0)
    with caplog.at_level(logging.INFO, logger="agent_runtime.stream_gap_receipt"):
        result = run_codex_stream(agent or _agent(), {"model": "gap-fixture", "input": "hi"}, client=client)
    assert result.output_text == "Hi"
    lines = [m for m in caplog.messages if m.startswith(STREAM_GAP_RECEIPT + " ")]
    assert len(lines) == 1, caplog.messages
    print(lines[0])
    return dict(re.findall(r"(\w+)=(\S+)", lines[0]))


def _num(fields: dict[str, str], key: str) -> float:
    assert fields[key] != "na", (key, fields)
    return float(fields[key])


@pytest.mark.timeout(60)
def test_silent_provider_shows_no_bytes_and_no_lag(fake_sse, caplog):
    fields = _run(fake_sse("silent"), caplog)
    assert fields["end"] == "text"
    assert 2000 <= _num(fields, "gap_ms") <= 6000  # minus the first event's cold parse (first_lag_ms)
    assert fields["chunks"] == "0" and fields["bytes"] == "0"
    assert fields["kinds"] == "response.created:1"
    # the text's own bytes arrived ~3 s after the first event's (window times start at its parse)
    assert _num(fields, "text_chunk_ms") + _num(fields, "first_lag_ms") >= 2800
    assert _num(fields, "max_lag_ms") < 50
    assert _num(fields, "stall_over50_ms") < 100  # Windows timer jitter stays under the floor
    assert fields["reasoning_tokens"] == "12" and fields["output_tokens"] == "40"
    assert fields["reasoning_summary_chars"] == "0"
    assert _num(fields, "gap_ms_per_reasoning_token") == pytest.approx(_num(fields, "gap_ms") / 12, abs=0.1)


@pytest.mark.timeout(60)
def test_reasoning_deltas_are_counted_with_no_lag(fake_sse, caplog):
    fields = _run(fake_sse("reasoning"), caplog)
    assert fields["end"] == "text"
    assert 2800 <= _num(fields, "gap_ms") <= 6000
    assert "response.reasoning_summary_text.delta:30" in fields["kinds"]
    assert _num(fields, "events") == 31
    assert _num(fields, "chunks") >= 25 and _num(fields, "bytes") > 0
    assert _num(fields, "first_chunk_ms") < 400 and _num(fields, "last_chunk_ms") >= 2700
    assert _num(fields, "max_lag_ms") < 50
    assert _num(fields, "stall_over50_ms") < 100  # Windows timer jitter stays under the floor
    assert fields["reasoning_summary_chars"] == str(30 * len("think "))


@pytest.mark.timeout(120)
def test_starved_reader_shows_lag_and_late_wakeups(fake_sse, caplog):
    """The hog runs only inside the window: it starts on the first event and stops on the first text."""
    base_url = fake_sse("hog")
    big = 3 ** 700_000
    stop = threading.Event()

    def hog() -> None:  # each multiply holds the GIL ~70 ms in one C call
        while not stop.is_set():
            _ = big * big

    thread = threading.Thread(target=hog, daemon=True)

    def first_event(*_args) -> None:
        if not thread.is_alive() and not stop.is_set():
            thread.start()

    def first_text(*_args) -> None:
        stop.set()

    agent = _agent()
    agent._touch_activity, agent._fire_stream_delta = first_event, first_text
    try:
        fields = _run(base_url, caplog, agent)
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=10)
    assert fields["end"] == "text"
    assert _num(fields, "events") == 11
    assert _num(fields, "max_lag_ms") >= 150
    assert _num(fields, "stall_max_ms") >= 150
    assert _num(fields, "stall_over50_ms") >= 500
