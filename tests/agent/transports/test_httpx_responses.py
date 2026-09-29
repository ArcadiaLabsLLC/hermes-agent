"""The SDK-free ``codex_responses`` wire (``responses.create`` on ``SdkFreeClient``) against the ``openai`` SDK.

Same bytes into the real SDK and the SDK-free client through one ``httpx`` mock
transport; compared on what the loop reads: each streamed event's ``model_dump()``, the
response the Codex runtime assembles from them (``_consume_codex_event_stream``) as the
Responses transport normalizes it, the non-streamed ``Response`` (``output_text``
included), the request on the wire, and the error classifier's verdict.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_kind_for`` never falls back to a union's first model (an unknown tag -> KeyError) -> unknown-item parity red.
* ``_ResponseRecord.output_text`` returns ``""``                                      -> non-streamed parity red.
* (``Accept``: the SDK sends ``application/json`` on streams too; the request test compares it.)
* ``sdk_free_client`` refuses ``codex_responses`` again                                -> selection test red.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from agent.transports.httpx_client import ProviderStreamError, SdkFreeClient

openai = pytest.importorskip("openai")

BASE = "https://chatgpt.example/backend-api/codex"
KEY = "fixture-codex-token-never-emitted"


def _sse(*events) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


_USAGE = {"input_tokens": 40, "input_tokens_details": {"cached_tokens": 32}, "output_tokens": 9,
          "output_tokens_details": {"reasoning_tokens": 4}, "total_tokens": 49}
_REASONING = {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "Plan it."}],
              "encrypted_content": "gAAA-opaque"}
_MESSAGE = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": "Hello world", "annotations": [], "logprobs": []}]}
_CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file",
         "arguments": '{"path": "a.txt"}', "status": "completed"}


def _response(status="completed", output=(), **extra):
    return {"id": "resp_1", "object": "response", "created_at": 1, "model": "gpt-5-codex", "status": status,
            "output": None if output is None else list(output), "usage": _USAGE, "parallel_tool_calls": True, "tool_choice": "auto",
            "tools": [], **extra}


STREAMS = {
    "reasoning_then_text": _sse(
        {"type": "response.created", "sequence_number": 0, "response": _response("in_progress")},
        {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0,
         "item": {**_REASONING, "summary": []}},
        {"type": "response.reasoning_summary_text.delta", "sequence_number": 2, "item_id": "rs_1", "output_index": 0,
         "summary_index": 0, "delta": "Plan "},
        {"type": "response.reasoning_summary_text.delta", "sequence_number": 3, "item_id": "rs_1", "output_index": 0,
         "summary_index": 0, "delta": "it."},
        {"type": "response.output_item.done", "sequence_number": 4, "output_index": 0, "item": _REASONING},
        {"type": "response.output_item.added", "sequence_number": 5, "output_index": 1,
         "item": {**_MESSAGE, "status": "in_progress", "content": []}},
        {"type": "response.content_part.added", "sequence_number": 6, "item_id": "msg_1", "output_index": 1,
         "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
        {"type": "response.output_text.delta", "sequence_number": 7, "item_id": "msg_1", "output_index": 1,
         "content_index": 0, "delta": "Hello ", "logprobs": []},
        {"type": "response.output_text.delta", "sequence_number": 8, "item_id": "msg_1", "output_index": 1,
         "content_index": 0, "delta": "world", "logprobs": []},
        {"type": "response.output_item.done", "sequence_number": 9, "output_index": 1, "item": _MESSAGE},
        {"type": "response.completed", "sequence_number": 10, "response": _response(output=[_REASONING, _MESSAGE])}),
    "function_call": _sse(
        {"type": "response.output_item.added", "sequence_number": 0, "output_index": 0,
         "item": {**_CALL, "arguments": "", "status": "in_progress"}},
        {"type": "response.function_call_arguments.delta", "sequence_number": 1, "item_id": "fc_1", "output_index": 0,
         "delta": '{"path": '},
        {"type": "response.function_call_arguments.delta", "sequence_number": 2, "item_id": "fc_1", "output_index": 0,
         "delta": '"a.txt"}'},
        {"type": "response.function_call_arguments.done", "sequence_number": 3, "item_id": "fc_1", "output_index": 0,
         "arguments": '{"path": "a.txt"}'},
        {"type": "response.output_item.done", "sequence_number": 4, "output_index": 0, "item": _CALL},
        {"type": "response.completed", "sequence_number": 5, "response": _response(output=None)}),
    "unknown_items_and_extras": _sse(
        {"type": "response.output_item.added", "sequence_number": 0, "output_index": 0,
         "item": {"type": "future_item", "id": "x_1", "vendor": {"k": 1}}},
        {"type": "response.vendor.progress", "sequence_number": 1, "note": "a frame no SDK types"},
        {"type": "response.output_text.delta", "sequence_number": 2, "item_id": "msg_1", "output_index": 1,
         "content_index": 0, "delta": "ok", "logprobs": [], "obfuscation": "pad"},
        {"type": "response.completed", "sequence_number": 3, "response": _response(output=[], vendor_meta={"a": 1})}),
    "failed": _sse(
        {"type": "response.failed", "sequence_number": 0,
         "response": _response("failed", error={"code": "server_error", "message": "The model failed."})}),
}
REQUEST = {"model": "gpt-5-codex", "instructions": "Be brief.", "store": False,
           "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}],
           "reasoning": {"effort": "medium", "summary": "auto"}, "include": ["reasoning.encrypted_content"]}


def _clients(handler):
    def http():
        return httpx.Client(transport=httpx.MockTransport(handler))

    return (openai.OpenAI(api_key=KEY, base_url=BASE, http_client=http(), max_retries=0),
            SdkFreeClient(api_key=KEY, base_url=BASE, http_client=http()))


@pytest.mark.parametrize("name", sorted(STREAMS))
def test_a_stream_reads_exactly_as_the_sdk_reads_it(name):
    from agent.codex_runtime import _consume_codex_event_stream

    events, finals = [], []
    for client in _clients(lambda _r: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                     content=STREAMS[name])):
        stream = list(client.responses.create(stream=True, **REQUEST))
        events.append([event.model_dump() for event in stream])
        finals.append(_consume_codex_event_stream(iter(stream), model="gpt-5-codex"))
    assert events[1] == events[0] and events[0], name  # control: the fixture reached the SDK
    assert _normalized(finals[1]) == _normalized(finals[0])


def _normalized(final):
    """What the loop gets from the Responses transport: the normalized turn, or the error it raises."""
    from agent.transports.codex import ResponsesApiTransport

    try:
        return asdict(ResponsesApiTransport().normalize_response(final))
    except Exception as exc:  # noqa: BLE001 — the failed fixture raises on both sides; compare it
        return type(exc).__name__, str(exc)


def test_a_non_streamed_response_is_the_sdks():
    from agent.transports.codex import ResponsesApiTransport

    body = _response(output=[_REASONING, _MESSAGE, _CALL],
                     text={"format": {"type": "json_schema", "name": "s", "schema": {"type": "object"}}})
    sdk, free = _clients(lambda _r: httpx.Response(200, json=body))
    expected, actual = (client.responses.create(**REQUEST) for client in (sdk, free))
    assert actual.model_dump() == expected.model_dump()
    assert actual.output_text == expected.output_text == "Hello world"
    assert actual.text.format.schema_ == expected.text.format.schema_  # the SDK's one aliased field
    transport = ResponsesApiTransport()
    assert asdict(transport.normalize_response(actual)) == asdict(transport.normalize_response(expected))


def test_the_request_on_the_wire_is_the_sdks():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=STREAMS["function_call"])

    for client in _clients(handler):
        list(client.responses.create(stream=True, extra_headers={"originator": "codex_cli_rs"}, **REQUEST))
    sdk, free = seen
    assert str(free.url) == str(sdk.url) == BASE + "/responses"
    assert json.loads(free.content) == json.loads(sdk.content)
    for header in ("authorization", "originator", "accept"):
        assert free.headers.get(header) == sdk.headers.get(header), header


def test_http_errors_classify_as_the_sdks_do():
    from agent.error_classifier import classify_api_error

    body = {"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached", "resets_in_seconds": 60}}
    errors = []
    for client in _clients(lambda _r: httpx.Response(429, json=body, headers={"retry-after": "60"})):
        with pytest.raises(Exception) as caught:
            list(client.responses.create(stream=True, **REQUEST))
        errors.append(caught.value)
    assert errors[1].status_code == errors[0].status_code == 429 and errors[1].body == errors[0].body
    expected, actual = (classify_api_error(e, provider="openai-codex", model="gpt-5-codex") for e in errors)
    assert (actual.reason, actual.retryable, actual.status_code) == (expected.reason, expected.retryable,
                                                                     expected.status_code)


def test_an_error_key_in_the_stream_raises_as_the_sdks_does():
    content = b'data: {"error": {"message": "stream broke", "code": "server_error"}}\n\n'
    errors = []
    for client in _clients(lambda _r: httpx.Response(200, content=content)):
        with pytest.raises(Exception) as caught:
            list(client.responses.create(stream=True, **REQUEST))
        errors.append(caught.value)
    assert isinstance(errors[0], openai.APIError) and isinstance(errors[1], ProviderStreamError)
    assert errors[1].body == errors[0].body and errors[1].status_code is None


def test_the_profile_switch_serves_the_codex_wire_at_the_one_chokepoint():
    from types import SimpleNamespace

    from agent.agent_runtime_helpers import create_openai_client
    from hermes_constants import get_hermes_home

    def build():
        agent = SimpleNamespace(provider="openai-codex", api_mode="codex_responses", _client_log_context=lambda: "",
                                _build_keepalive_http_client=lambda *a, **k: None)
        return create_openai_client(agent, {"api_key": KEY, "base_url": BASE}, reason="t", shared=False)

    assert isinstance(build(), openai.OpenAI)  # positive control: desktop keeps the SDK
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False}}), encoding="utf-8")
    client = build()
    assert isinstance(client, SdkFreeClient) and callable(client.responses.create)
