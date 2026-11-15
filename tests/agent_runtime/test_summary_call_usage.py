"""RT-ITERATION-SUMMARY-CALL-UNCOUNTED — the iteration-summary call's tokens are counted.

Upstream's summary request fires no ``post_api_request``; ``agent_runtime/summary_call_usage.py``
reads its usage at the httpx client ``transport_phase_trace`` already hooks. Real httpx clients over
a ``MockTransport``; no provider, no serve.

Gates and their killing mutations (each red recorded in the commit):

* the hook rides the existing transport-trace install — killed by dropping the
  ``install_summary_usage_hook`` call from ``install_transport_phase_trace`` (no row recorded);
* only a request whose LAST message is the nudge counts (a later turn's history holds it too) —
  killed by matching the nudge in any message (the history request records a row);
* Anthropic's split usage merges input and output — killed by letting a 0 overwrite in ``_merge``;
* the turn record's totals take in the rows past ``api_calls`` — killed by dropping the
  ``_fold_uncounted_calls`` call from ``turn_usage_block``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST as NUDGE
from agent_runtime.summary_call_usage import is_summary_request, usage_from_body

USAGE = {"prompt_tokens": 1_990, "completion_tokens": 10, "total_tokens": 2_000}


def _body(*messages: dict) -> dict:
    return {"model": "m", "messages": list(messages), "tools": [{"type": "function"}]}


def _client(responder) -> httpx.Client:
    from agent_runtime.transport_phase_trace import install_transport_phase_trace

    http = httpx.Client(transport=httpx.MockTransport(responder))
    agent = SimpleNamespace(provider="custom", api_mode="chat_completions")
    install_transport_phase_trace(agent, SimpleNamespace(_client=http))
    return http


def _rows(http: httpx.Client, body: dict, *, stream: bool = False) -> list[dict]:
    from agent_runtime.usage_ledger import bind_usage_ledger

    with bind_usage_ledger() as rows:
        if stream:
            with http.stream("POST", "https://provider.invalid/v1/chat/completions", json=body) as response:
                b"".join(response.iter_bytes())
        else:
            http.post("https://provider.invalid/v1/chat/completions", json=body).json()
    return rows


def test_the_summary_request_is_the_one_whose_last_message_is_the_nudge():
    assert is_summary_request(_body({"role": "user", "content": "hi"}, {"role": "user", "content": NUDGE}))
    assert is_summary_request({"input": [{"role": "user", "content": [{"type": "input_text", "text": NUDGE}]}]})
    later = _body({"role": "user", "content": NUDGE}, {"role": "assistant", "content": "summary"},
                  {"role": "user", "content": "next question"})
    assert not is_summary_request(later)


def test_a_json_summary_response_is_recorded_once_and_a_main_call_is_not():
    payload = json.dumps({"choices": [], "usage": USAGE}).encode()
    # A wire response: its body is a stream the client reads (``json=`` would pre-read it).
    http = _client(lambda request: httpx.Response(200, stream=httpx.ByteStream(payload),
                                                  headers={"content-type": "application/json"}))

    [row] = _rows(http, _body({"role": "user", "content": NUDGE}))
    assert (row["prompt_tokens"], row["output_tokens"]) == (1_990, 10)
    assert _rows(http, _body({"role": "user", "content": "investigate"})) == []
    history = _body({"role": "user", "content": NUDGE}, {"role": "assistant", "content": "s"},
                    {"role": "user", "content": "again"})
    assert _rows(http, history) == []


def test_a_streamed_summary_is_read_from_its_last_usage_event_and_still_streams():
    sse = (f"data: {json.dumps({'choices': [{'delta': {'content': 'Report'}}]})}\n\n"
           f"data: {json.dumps({'choices': [], 'usage': USAGE})}\n\ndata: [DONE]\n\n").encode()
    http = _client(lambda request: httpx.Response(200, stream=httpx.ByteStream(sse), headers={"content-type": "text/event-stream"}))

    [row] = _rows(http, _body({"role": "user", "content": NUDGE}), stream=True)
    assert row["prompt_tokens"] == 1_990


def test_usage_reads_the_responses_and_anthropic_shapes():
    completed = {"type": "response.completed", "response": {"usage": {"input_tokens": 50, "output_tokens": 5}}}
    assert usage_from_body(f"data: {json.dumps(completed)}\n\n".encode()) == {"input_tokens": 50, "output_tokens": 5}
    start = {"type": "message_start", "message": {"usage": {"input_tokens": 70, "output_tokens": 1}}}
    delta = {"type": "message_delta", "usage": {"input_tokens": 0, "output_tokens": 9}}
    body = f"data: {json.dumps(start)}\n\ndata: {json.dumps(delta)}\n\n".encode()
    assert usage_from_body(body) == {"input_tokens": 70, "output_tokens": 9}
    assert usage_from_body(b"") is None and usage_from_body(b'{"choices": []}') is None


def test_the_turn_record_totals_take_in_the_calls_past_api_calls():
    from agent_runtime.turn_usage import turn_usage_block

    row = {"call_index": 1, "prompt_tokens": 2_000, "input_tokens": 2_000, "output_tokens": 10,
           "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0}
    result = SimpleNamespace(provider="custom", model="m", api_calls=1, input_tokens=2_000, output_tokens=10,
                             cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, total_tokens=2_010,
                             usage_ledger=[row, {**row, "call_index": 2}, {**row, "call_index": 3}])
    block = turn_usage_block(result)
    assert (block["api_calls"], block["input_tokens"], block["output_tokens"], block["total_tokens"]) == (
        3, 6_000, 30, 6_030)
    result.usage_ledger = [row]
    assert turn_usage_block(result)["api_calls"] == 1 and turn_usage_block(result)["total_tokens"] == 2_010
