"""The SDK-free Anthropic client (``agent.transports.httpx_anthropic``) against the ``anthropic`` SDK it replaces.

Every parity claim feeds the real SDK and the SDK-free client the SAME bytes through the
same ``httpx`` mock transport and compares what the loop reads: each streamed event's
``model_dump()``, the final message's, the transport's normalization, the Relay
accumulator, and the error classifier's verdict. Nothing is compared to a hand-written
expectation. The clients are built by upstream's own builder (``build_anthropic_client``)
with the profile switch on (SDK) and off (SDK-free), so the seam is under test as well.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_Snapshot._input_json`` stores the raw buffer instead of parsing it     -> tool_use parity red.
* ``_UsageFill`` stops filling ``message_start`` usage                     -> usage-null parity red.
* ``raw_events`` dispatches unnamed events too                              -> ignored-events parity red.
* ``_delta_events`` derives no ``text`` event                               -> text/thinking parity red.
* ``_merge_headers`` keeps an ``Omit`` value                                -> request parity red.
* the ``_require_sdk`` seam returns the SDK regardless of the switch        -> selection test red.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

anthropic = pytest.importorskip("anthropic")

KEY = "sk-ant-api03-fixture-never-emitted"
OAUTH = "sk-ant-oat01-fixture-never-emitted"
BASE = "https://api.anthropic.com"


def _sse(*events) -> bytes:
    out = []
    for name, data in events:
        if name is not None:
            out.append(f"event: {name}")
        out.append("data: " + (data if isinstance(data, str) else json.dumps(data)))
        out.append("")
    return ("\n".join(out) + "\n").encode()


def _start(usage=None, **extra):
    usage = {"input_tokens": 12, "output_tokens": 1, "cache_read_input_tokens": 3} if usage is None else usage
    message = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x", "content": [],
               "stop_reason": None, "stop_sequence": None, "usage": usage, **extra}
    return ("message_start", {"type": "message_start", "message": message})


def _block(index, block):
    return ("content_block_start", {"type": "content_block_start", "index": index, "content_block": block})


def _delta(index, delta):
    return ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta})


def _stop(index):
    return ("content_block_stop", {"type": "content_block_stop", "index": index})


def _end(stop_reason="end_turn", usage=None):
    usage = {"output_tokens": 20} if usage is None else usage
    return [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                               "usage": usage}),
            ("message_stop", {"type": "message_stop"})]


STREAMS = {
    "text_and_thinking": _sse(
        _start(), _block(0, {"type": "thinking", "thinking": "", "signature": ""}),
        _delta(0, {"type": "thinking_delta", "thinking": "Let me "}), _delta(0, {"type": "thinking_delta", "thinking": "think."}),
        _delta(0, {"type": "signature_delta", "signature": "sig-abc"}), _stop(0),
        _block(1, {"type": "text", "text": ""}), _delta(1, {"type": "text_delta", "text": "Hello "}),
        ("ping", {"type": "ping"}), _delta(1, {"type": "text_delta", "text": "world"}), _stop(1), *_end()),
    "tool_use": _sse(
        _start(), _block(0, {"type": "text", "text": ""}), _delta(0, {"type": "text_delta", "text": "Reading."}), _stop(0),
        _block(1, {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}),
        _delta(1, {"type": "input_json_delta", "partial_json": '{"path": "a'}),
        _delta(1, {"type": "input_json_delta", "partial_json": '.txt", "limit": [1, 2'}),
        _delta(1, {"type": "input_json_delta", "partial_json": "]}"}), _stop(1), *_end("tool_use")),
    "citations_and_server_tools": _sse(
        _start(), _block(0, {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}}),
        _delta(0, {"type": "input_json_delta", "partial_json": '{"query": "eternia"}'}), _stop(0),
        _block(1, {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
            {"type": "web_search_result", "url": "https://example.test/a", "title": "A", "encrypted_content": "enc",
             "page_age": None}]}), _stop(1),
        _block(2, {"type": "text", "text": "", "citations": None}),
        _delta(2, {"type": "citations_delta", "citation": {
            "type": "web_search_result_location", "url": "https://example.test/a", "title": "A",
            "encrypted_index": "ix", "cited_text": "quoted"}}),
        _delta(2, {"type": "text_delta", "text": "Cited."}), _stop(2),
        *_end(usage={"output_tokens": 30, "server_tool_use": {"web_search_requests": 1}})),
    "usage_null": _sse(  # MiniMax (#60683): the loop's normalize_stream_usage fills it for the SDK
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_2", "type": "message", "role": "assistant", "model": "MiniMax-M2", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": None}}),
        _block(0, {"type": "text", "text": ""}), _delta(0, {"type": "text_delta", "text": "hi"}), _stop(0),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": None}),
        ("message_stop", {"type": "message_stop"})),
    "ignored_events_and_extras": _sse(
        _start(provider_note="kept as an extra"),
        (None, {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "unnamed"}}),
        ("vendor_heartbeat", {"type": "vendor_heartbeat"}),
        _block(0, {"type": "text", "text": "", "cache_control": {"type": "ephemeral"}}),
        _delta(0, {"type": "text_delta", "text": "ok"}), _stop(0), *_end()),
}
REQUEST = {"model": "claude-x", "max_tokens": 64, "messages": [{"role": "user", "content": "Hello"}],
           "system": [{"type": "text", "text": "Be brief."}], "metadata": {"user_id": "u1"},
           "thinking": {"type": "enabled", "budget_tokens": 1024}}


def _profile(sdk_free: bool) -> None:
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": not sdk_free}}), encoding="utf-8")


def _clients(handler, key=KEY, base=BASE):
    """(SDK client, SDK-free client), both from upstream's builder, over one mock transport (both
    keep their ``httpx`` client on ``_client``, so one swap covers both)."""
    from agent import anthropic_adapter
    from agent.transports.httpx_anthropic import SdkFreeAnthropicClient

    built = []
    for sdk_free in (False, True):
        _profile(sdk_free)
        client = anthropic_adapter.build_anthropic_client(key, base)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        built.append(client)
    assert isinstance(built[0], anthropic.Anthropic) and isinstance(built[1], SdkFreeAnthropicClient)
    return built


def _stream_through(client, **kwargs):
    from agent.anthropic_adapter import normalize_stream_usage

    with client.messages.stream(**kwargs) as stream:
        stream = normalize_stream_usage(stream)  # as the loop always does
        events = [event.model_dump() for event in stream]
        return events, stream.get_final_message()


@pytest.mark.parametrize("name", sorted(STREAMS))
def test_a_stream_reads_exactly_as_the_sdk_reads_it(name):
    from agent.transports.anthropic import AnthropicTransport

    sdk, free = _clients(lambda _r: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                   content=STREAMS[name]))
    expected_events, expected_final = _stream_through(sdk, **REQUEST)
    events, final = _stream_through(free, **REQUEST)
    assert events == expected_events
    assert final.model_dump() == expected_final.model_dump()
    transport = AnthropicTransport()
    assert asdict(transport.normalize_response(final)) == asdict(transport.normalize_response(expected_final))
    assert expected_final.content and len(expected_events) > 4, name  # control: the fixture reached the SDK


def test_the_relay_accumulator_rebuilds_the_same_message_from_either_stream():
    from agent.relay_llm import AnthropicStreamAccumulator

    finals = []
    for client in _clients(lambda _r: httpx.Response(200, content=STREAMS["tool_use"])):
        accumulator = AnthropicStreamAccumulator()
        with client.messages.stream(**REQUEST) as stream:
            for event in stream:
                accumulator.observe(event)
        finals.append(accumulator.finalize())
    assert finals[1] == finals[0]
    assert finals[0]["content"][1]["input"] == {"path": "a.txt", "limit": [1, 2]}  # control


def test_create_anthropic_message_returns_the_same_message_on_either_client():
    from agent.anthropic_adapter import create_anthropic_message

    seen = []
    messages = []
    for client in _clients(lambda r: (seen.append(r), httpx.Response(200, content=STREAMS["text_and_thinking"]))[1]):
        messages.append(create_anthropic_message(client, dict(REQUEST)).model_dump())
    assert messages[1] == messages[0] and messages[0]["content"][1]["text"] == "Hello world"


def test_a_non_streamed_message_is_the_sdks():
    from agent.transports.anthropic import AnthropicTransport

    body = {"id": "msg_3", "type": "message", "role": "assistant", "model": "claude-x", "stop_reason": "tool_use",
            "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 7, "service_tier": "standard"},
            "content": [{"type": "text", "text": "Using a tool."},
                        {"type": "tool_use", "id": "toolu_2", "name": "terminal", "input": {"command": "ls"}},
                        {"type": "future_block_type", "payload": 1}]}
    sdk, free = _clients(lambda _r: httpx.Response(200, json=body))
    expected, actual = (client.messages.create(**REQUEST) for client in (sdk, free))
    assert actual.model_dump(warnings=False) == expected.model_dump(warnings=False)
    transport = AnthropicTransport()
    assert asdict(transport.normalize_response(actual)) == asdict(transport.normalize_response(expected))


@pytest.mark.parametrize("key", [KEY, OAUTH])
def test_the_request_on_the_wire_is_the_sdks(key):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=STREAMS["text_and_thinking"])

    for client in _clients(handler, key=key, base=BASE + "/v1"):
        with client.messages.stream(**REQUEST, extra_headers={"x-trace": "t1"}) as stream:
            stream.until_done()
    sdk, free = seen
    assert str(free.url) == str(sdk.url) == BASE + "/v1/messages"
    assert json.loads(free.content) == json.loads(sdk.content)
    for header in ("x-api-key", "authorization", "anthropic-version", "anthropic-beta", "x-app", "x-trace"):
        assert free.headers.get(header) == sdk.headers.get(header), header
    # control: exactly one credential header, the one the key's style selects
    assert (sdk.headers.get("x-api-key") is None) != (sdk.headers.get("authorization") is None)


ERRORS = {
    "rate_limit": (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}}),
    "overloaded": (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    "context": (400, {"type": "error", "error": {"type": "invalid_request_error",
                                                 "message": "prompt is too long: 250000 tokens > 200000 maximum"}}),
    "auth": (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}),
}


@pytest.mark.parametrize("name", sorted(ERRORS))
def test_http_errors_classify_as_the_sdks_do(name):
    from agent.error_classifier import classify_api_error

    status, body = ERRORS[name]
    sdk, free = _clients(lambda _r: httpx.Response(status, json=body, headers={"retry-after": "2"}))
    errors = []
    for client in (sdk, free):
        with pytest.raises(Exception) as caught:
            _stream_through(client, **REQUEST)
        errors.append(caught.value)
    assert errors[1].status_code == errors[0].status_code == status and errors[1].body == errors[0].body
    expected, actual = (classify_api_error(e, provider="anthropic", model="claude-x") for e in errors)
    assert (actual.reason, actual.retryable, actual.status_code) == (expected.reason, expected.retryable,
                                                                     expected.status_code)


def test_an_error_event_inside_the_stream_raises_and_classifies_as_the_sdks_does():
    from agent.error_classifier import classify_api_error

    content = _sse(_start(), ("error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))
    errors = []
    for client in _clients(lambda _r: httpx.Response(200, content=content)):
        with pytest.raises(Exception) as caught:
            _stream_through(client, **REQUEST)
        errors.append(caught.value)
    assert (errors[1].status_code, errors[1].body) == (errors[0].status_code, errors[0].body)
    expected, actual = (classify_api_error(e, provider="anthropic", model="claude-x") for e in errors)
    assert (actual.reason, actual.retryable) == (expected.reason, expected.retryable)


def test_an_out_of_order_stream_fails_with_the_sdks_words():
    """The loop's stream fallback (``_is_stream_unavailable_error``) keys on ``unexpected event order``."""
    from agent.anthropic_adapter import _is_stream_unavailable_error

    content = _sse(_block(0, {"type": "text", "text": ""}), *_end())
    messages = []
    for client in _clients(lambda _r: httpx.Response(200, content=content)):
        with pytest.raises(RuntimeError) as caught:
            _stream_through(client, **REQUEST)
        messages.append(str(caught.value))
    assert messages[1] == messages[0] and _is_stream_unavailable_error(RuntimeError(messages[1]))


def test_a_malformed_tool_stream_takes_the_loops_parse_retry_path():
    from agent.api_error_summary import is_provider_stream_parse_error

    content = _sse(_start(), _block(0, {"type": "tool_use", "id": "t", "name": "cronjob", "input": {}}),
                   _delta(0, {"type": "input_json_delta", "partial_json": '{"names": cronjob_manage}'}), _stop(0), *_end())
    errors = []
    for client in _clients(lambda _r: httpx.Response(200, content=content)):
        with pytest.raises(ValueError) as caught:
            _stream_through(client, **REQUEST)
        errors.append(caught.value)
    assert str(errors[1]) == str(errors[0])
    assert is_provider_stream_parse_error(errors[1]) and is_provider_stream_parse_error(errors[0])


def test_a_provider_echoing_the_key_never_puts_it_in_the_error():
    _, free = _clients(lambda _r: httpx.Response(401, text=f"bad credential {KEY}"))
    with pytest.raises(Exception) as caught:
        _stream_through(free, **REQUEST)
    assert KEY not in str(caught.value) and "bad credential" in str(caught.value)


def test_the_profile_switch_picks_the_client_at_the_one_builder():
    from agent import anthropic_adapter
    from agent.transports.httpx_anthropic import SdkFreeAnthropicClient

    _profile(sdk_free=False)
    assert isinstance(anthropic_adapter.build_anthropic_client(KEY, BASE), anthropic.Anthropic)  # positive control
    _profile(sdk_free=True)
    assert isinstance(anthropic_adapter.build_anthropic_client(KEY, BASE), SdkFreeAnthropicClient)
    copy = anthropic_adapter.build_anthropic_client(KEY, BASE).with_options(default_headers={"x-extra": "1"})
    assert isinstance(copy, SdkFreeAnthropicClient) and copy._default_headers["x-extra"] == "1"
